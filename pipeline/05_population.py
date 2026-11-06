"""05_population.py — census-scaled population and exposed people per scenario (E-04).

Method (plan §4.7, dasymetric):
  * Weights: WorldPop Kenya 2020 unconstrained, people per ~100 m pixel (ken_ppp_2020.tif, CC BY 4.0,
    doi:10.5258/SOTON/WP00645), downloaded from
    https://data.worldpop.org/GIS/Population/Global_2000_2020/2020/KEN/ken_ppp_2020.tif
  * Totals: Person B's web/public/data/<area>/population.json — one county unit, projected for the year
    (low / medium / high growth). Scale factor f_s = projection_s / (WorldPop sum over the county polygon), so the
    scaled pixels over the county sum to the projection exactly (printed both ways).
  * County polygons: OSM boundary=administrative admin_level=4 from the same md5-checked Geofabrik snapshot.
  * Exposed people (s) = f_s * sum of WorldPop people in flooded cells. The WorldPop grid (EPSG:4326, ~100 m) is
    carried onto the flood grid (UTM, 30 m) as a DENSITY (people per m², per-row pixel area on the WGS84 ellipsoid),
    nearest-neighbour, then times the 30 m cell area; the total is checked against the native-grid total.
  * LIMITATION: where the AOI extends beyond the county in population.json, the county's factor is applied to the
    whole AOI (an assumption). The share of AOI people outside that county is printed and stored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
PBF_NAME = "kenya-261104.osm.pbf"
WORLDPOP_URL = "https://data.worldpop.org/GIS/Population/Global_2000_2020/2020/KEN/ken_ppp_2020.tif"
WORLDPOP_NAME = "ken_ppp_2020.tif"
# population.json unit -> OSM admin_level=4 name (checked against boundaries output, not assumed)
COUNTY_OSM_NAME = {"nairobi": "Nairobi", "nyando": "Kisumu"}


def rms_data() -> Path:
    return Path(os.environ.get("RMS_DATA", "/Users/mac/IGAD/data"))


def load_area(area: str, data_dir: Path | None = None) -> dict:
    data_dir = data_dir or REPO / "web" / "public" / "data"
    for a in json.loads((data_dir / "areas.json").read_text()):
        if a["id"] == area:
            return a
    raise SystemExit(f"area {area!r} not in areas.json")


def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------
# county polygons from OSM
# ---------------------------------------------------------------------------------------------

def extract_admin(pbf: Path, admin_level: str = "4") -> list[dict]:
    """All boundary=administrative areas of one admin_level in the PBF, as GeoJSON features (WGS84)."""
    import osmium
    from shapely.geometry import MultiPolygon, Polygon, mapping
    from pyproj import Geod
    geod = Geod(ellps="WGS84")
    out = []
    for obj in osmium.FileProcessor(str(pbf)).with_locations().with_areas():
        if not obj.is_area():
            continue
        t = obj.tags
        if t.get("boundary") != "administrative" or t.get("admin_level") != admin_level:
            continue
        try:
            polys = [Polygon([(n.lon, n.lat) for n in ring], [[(n.lon, n.lat) for n in inner]
                                                              for inner in obj.inner_rings(ring)])
                     for ring in obj.outer_rings()]
        except osmium.InvalidLocationError:
            continue
        if not polys:
            continue
        geom = MultiPolygon(polys) if len(polys) > 1 else polys[0]
        osm = f"w{obj.orig_id()}" if obj.from_way() else f"r{obj.orig_id()}"
        out.append({"type": "Feature", "geometry": mapping(geom),
                    "properties": {"osm": osm, "name": t.get("name"), "admin_level": admin_level,
                                   "area_km2": round(abs(geod.geometry_area_perimeter(geom)[0]) / 1e6, 2)}})
    return out


def cmd_boundaries(args) -> int:
    pbf = Path(args.pbf or rms_data() / "raw" / "osm" / PBF_NAME)
    digest = md5(pbf)
    md5_file = pbf.with_suffix(pbf.suffix + ".md5")
    expected = md5_file.read_text().split()[0] if md5_file.exists() else None
    print(f"pbf {pbf} md5 {digest} expected {expected}")
    if expected and digest != expected:
        print("ERROR: PBF checksum mismatch", file=sys.stderr)
        return 1
    t0 = time.time()
    feats = extract_admin(pbf, args.admin_level)
    out = rms_data() / "raw" / "osm" / f"ken_admin{args.admin_level}.geojson"
    out.write_text(json.dumps({"type": "FeatureCollection", "pbf_md5": digest, "features": feats}))
    print(f"{len(feats)} admin_level={args.admin_level} areas in {time.time() - t0:.0f} s -> {out}")
    for f in sorted(feats, key=lambda f: f["properties"]["name"] or ""):
        p = f["properties"]
        print(f"  {p['osm']:>10} {p['name']!s:<30} {p['area_km2']:>10.2f} km2")
    return 0


# ---------------------------------------------------------------------------------------------
# scaling + carrying WorldPop onto a flood grid
# ---------------------------------------------------------------------------------------------

def pixel_area_m2(transform, height: int) -> np.ndarray:
    """Area (m²) of each row of a north-up EPSG:4326 grid on the WGS84 ellipsoid, shape (height, 1)."""
    from pyproj import Geod
    from shapely.geometry import box
    g = Geod(ellps="WGS84")
    x0, dx, y0, dy = transform.c, transform.a, transform.f, transform.e
    rows = [abs(g.geometry_area_perimeter(box(x0, y0 + (r + 1) * dy, x0 + dx, y0 + r * dy))[0]) for r in range(height)]
    return np.array(rows, dtype="float64")[:, None]


def read_people(path: Path, window=None) -> tuple[np.ndarray, object]:
    """People per pixel (float64, nodata -> 0) and the window's transform."""
    import rasterio
    with rasterio.open(path) as src:
        a = src.read(1, window=window).astype("float64")
        nod = src.nodata
        tf = src.window_transform(window) if window is not None else src.transform
    a[(a == nod) | ~np.isfinite(a) | (a < 0)] = 0.0
    return a, tf


def sum_in_polygon(path: Path, geom) -> float:
    """WorldPop people whose pixel CENTRE lies inside geom (EPSG:4326)."""
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.windows import from_bounds
    with rasterio.open(path) as src:
        win = from_bounds(*geom.bounds, transform=src.transform).round_offsets().round_lengths()
    a, tf = read_people(path, win)
    inside = ~geometry_mask([geom], out_shape=a.shape, transform=tf, all_touched=False)
    return float(a[inside].sum())


def scale_factors(projection: dict, county_sum: float) -> dict:
    """f_s = projected people / WorldPop people over the same county, per growth scenario."""
    if county_sum <= 0:
        raise ValueError("WorldPop sum over the county is 0")
    return {s: projection[s] / county_sum for s in ("low", "medium", "high")}


def people_on_grid(people, src_tf, dst_shape, dst_tf, dst_crs) -> np.ndarray:
    """Carry people-per-pixel from a north-up EPSG:4326 grid onto a projected grid (people per dst cell).
    Moved as density (people/m²) with nearest-neighbour, times the dst cell area, so totals are preserved up to
    edge and resampling effects (the caller checks them)."""
    from rasterio.warp import Resampling, reproject
    dens = people / pixel_area_m2(src_tf, people.shape[0])
    out = np.zeros(dst_shape, dtype="float64")
    reproject(dens, out, src_transform=src_tf, src_crs="EPSG:4326", dst_transform=dst_tf, dst_crs=dst_crs,
              resampling=Resampling.nearest, src_nodata=None, dst_nodata=None)
    return out * abs(dst_tf.a * dst_tf.e)


def ids_on_grid(ids, src_tf, dst_shape, dst_tf, dst_crs) -> np.ndarray:
    """Carry an integer label grid (EPSG:4326) onto a projected grid, nearest-neighbour; 0 where nothing maps."""
    from rasterio.warp import Resampling, reproject
    out = np.zeros(dst_shape, dtype=ids.dtype)
    reproject(ids, out, src_transform=src_tf, src_crs="EPSG:4326", dst_transform=dst_tf, dst_crs=dst_crs,
              resampling=Resampling.nearest, src_nodata=None, dst_nodata=None)
    return out


def exposed_people(people_grid: np.ndarray, wet: np.ndarray, factors: dict) -> dict:
    """Projected people in wet cells per growth scenario, rounded to whole people."""
    base = float(people_grid[wet].sum())
    return {s: int(round(base * f)) for s, f in factors.items()}


def county_feature(area: str, admin: list[dict]) -> dict:
    name = COUNTY_OSM_NAME[area]
    hits = [f for f in admin if f["properties"]["name"] == name]
    if len(hits) != 1:
        raise SystemExit(f"{area}: expected one admin_level=4 '{name}', found {len(hits)}: "
                         f"{sorted(str(f['properties']['name']) for f in admin)}")
    return hits[0]


# KNBS census county totals (enumerated population). 2009: "2009 KPHC Population Distribution by Sex, Number of
# Households, Area and Density by County and District", https://www.knbs.or.ke/wp-content/uploads/2023/09/2009-Kenya-
# population-and-Housing-Census-Population-Distribution-by-Sex-Number-of-Households-Area-and-Density-by-County-and-
# District.pdf (sha256 3f07b2ee31c286a3...). 2019: "2019 KPHC Volume I: Population by County and Sub-County", KNBS,
# copy at https://open.africa/dataset/9b94fe50-9d75-4b92-be00-6354c6e6cc88/resource/778659b5-c5ab-4d13-9f89-f61baf9cf32a/
# download/volume-1-kphc-2019.pdf (sha256 4d93b465d84b2b0d...). Keys are OSM admin_level=4 names.
KNBS = {
    "Nairobi": (3_138_369, 4_397_073), "Kisumu": (968_909, 1_155_574), "Kericho": (758_339, 901_777),
    "Homa Bay": (963_794, 1_131_950), "Nandi": (752_965, 885_711), "Nyamira": (598_252, 605_576),
    "Bomet": (724_186, 875_689),
}
CENSUS_YEAR = 2019


def project(p2009: int, p2019: int, assumptions: dict, year: int) -> dict:
    """Same method as Person B's population.json: r = (p2019/p2009)^(1/10) - 1 (geometric, per year);
    projection_s = p2019 * (1 + m_s * r)^(year - 2019), m_s from population.json "assumptions"."""
    r = (p2019 / p2009) ** 0.1 - 1
    return {s: int(round(p2019 * (1 + m * r) ** (year - CENSUS_YEAR))) for s, m in assumptions.items()}


def exposed_by_county(people_grid, county_grid, wet) -> dict:
    """WorldPop people in wet cells, per county id (0 = no county)."""
    ids, sums = np.unique(county_grid[wet], return_inverse=False), {}
    for c in ids:
        sums[int(c)] = float(people_grid[wet & (county_grid == c)].sum())
    return sums


def exposed_both_ways(sums_by_id: dict, man: dict) -> dict:
    """{"A": ..., "B": ...}: A = the population.json unit's factor on every pixel; B = each county's own factor
    (a pixel in no county, or in a county without KNBS figures, falls back to A's factor and is counted)."""
    fa = man["factors_A"]
    fb = {c["id"]: c["factors"] for c in man["counties"] if c.get("factors")}   # no KNBS figures -> falls back to A
    out = {"A": {}, "B": {}}
    for s in ("low", "medium", "high"):
        out["A"][s] = int(round(sum(v * fa[s] for v in sums_by_id.values())))
        out["B"][s] = int(round(sum(v * fb.get(i, fa)[s] for i, v in sums_by_id.items())))
    out["fallback_people_2020"] = round(sum(v for i, v in sums_by_id.items() if i not in fb), 1)
    return out


def exposed_building_weighted(b: dict, wet, county, mask, transform, crs, man: dict,
                              precision: str | None = None) -> dict:
    """W2 dasymetric weight: within each county's part of the AOI, people are placed in proportion to Open Buildings
    footprint area, not WorldPop pixels (unconstrained WorldPop puts people in farmland). The county's AOI total is
    still WorldPop 2020 over (AOI and county) x that county's factor (A or B). Exposed = that total x (footprint area
    in wet cells / footprint area in the AOI part of the county)."""
    from pyproj import Transformer
    from rasterio.transform import rowcol
    keep = b["conf"] >= b[f"thr{precision or OB_PRECISION}"]
    x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(b["lon"][keep], b["lat"][keep])
    r, c = rowcol(transform, x, y, op=np.floor)
    r, c = np.asarray(r).astype(np.int64), np.asarray(c).astype(np.int64)
    ok = (r >= 0) & (r < wet.shape[0]) & (c >= 0) & (c < wet.shape[1])
    r, c, area = r[ok], c[ok], b["area_m2"][keep][ok]
    inside = mask[r, c]
    r, c, area = r[inside], c[inside], area[inside]
    cid, w = county[r, c].astype(int), wet[r, c]
    fa = man["factors_A"]
    fb = {e["id"]: e["factors"] for e in man["counties"] if e.get("factors")}
    wp = {e["id"]: e["worldpop_aoi_2020"] for e in man["counties"]}
    out = {"A": dict.fromkeys(("low", "medium", "high"), 0.0), "B": dict.fromkeys(("low", "medium", "high"), 0.0)}
    for i in np.unique(cid):
        tot = float(area[cid == i].sum())
        if i == 0 or tot <= 0 or i not in wp:
            continue
        share = float(area[(cid == i) & w].sum()) / tot
        for s in out["A"]:
            out["A"][s] += wp[i] * fa[s] * share
            out["B"][s] += wp[i] * fb.get(i, fa)[s] * share
    return {m: {s: int(round(v)) for s, v in d.items()} for m, d in out.items()}


def cmd_prepare(args) -> int:
    import rasterio
    from rasterio.features import geometry_mask, rasterize
    from rasterio.windows import from_bounds
    from shapely.geometry import box, shape
    wp = Path(args.worldpop or rms_data() / "raw" / "worldpop" / WORLDPOP_NAME)
    admin = json.loads((rms_data() / "raw" / "osm" / "ken_admin4.geojson").read_text())["features"]
    for a in args.area:
        meta = load_area(a)
        pop = json.loads((REPO / "web" / "public" / "data" / a / "population.json").read_text())
        if len(pop["units"]) != 1:
            raise SystemExit(f"{a}: population.json has {len(pop['units'])} units; this step handles exactly one")
        unit = pop["units"][0]
        proj = unit["projections"][str(args.year)]
        cf = county_feature(a, admin)
        own = project(*KNBS[cf["properties"]["name"]], pop["assumptions"], args.year)
        if own != proj:  # our method must reproduce Person B's numbers for the unit county exactly
            raise SystemExit(f"{a}: projection method mismatch for {cf['properties']['name']}: {own} vs population.json {proj}")
        s_unit = sum_in_polygon(wp, shape(cf["geometry"]))
        fa = scale_factors(proj, s_unit)
        print(f"{a}: unit {unit['unit']!r} <- OSM {cf['properties']['osm']} {cf['properties']['name']}; "
              f"WorldPop 2020 over county {s_unit:,.0f}; projection reproduced from KNBS 2009/2019 exactly")
        for s in ("low", "medium", "high"):
            print(f"  {args.year} {s:<6} projection {proj[s]:>12,}  scaled WorldPop over county "
                  f"{s_unit * fa[s]:>14,.1f}  factor {fa[s]:.6f}")
        b = meta["bbox"]
        with rasterio.open(wp) as src:
            win = from_bounds(b[0] - .01, b[1] - .01, b[2] + .01, b[3] + .01, transform=src.transform)
            win = win.round_offsets().round_lengths()
            prof = src.profile.copy()
        people, tf = read_people(wp, win)
        outd = rms_data() / "processed" / a / "exposure"
        outd.mkdir(parents=True, exist_ok=True)
        prof.update(height=people.shape[0], width=people.shape[1], transform=tf, dtype="float32", nodata=None,
                    compress="deflate")
        with rasterio.open(outd / "worldpop_2020_aoi.tif", "w", **prof) as dst:
            dst.write(people.astype("float32"), 1)
        aoi = box(*b)
        in_bbox = ~geometry_mask([aoi], out_shape=people.shape, transform=tf, all_touched=False)
        aoi_sum = float(people[in_bbox].sum())
        counties, shapes_ = [], []
        for c in sorted(admin, key=lambda c: c["properties"]["name"] or ""):
            g = shape(c["geometry"])
            if not g.intersects(aoi):
                continue
            m = ~geometry_mask([g], out_shape=people.shape, transform=tf, all_touched=False) & in_bbox
            v = float(people[m].sum())
            if v <= 0:
                continue
            name = c["properties"]["name"]
            cid = len(counties) + 1
            entry = {"id": cid, "name": name, "osm": c["properties"]["osm"], "aoi_share": round(v / aoi_sum, 4),
                     "worldpop_aoi_2020": round(v, 1)}
            if name in KNBS:
                p09, p19 = KNBS[name]
                cproj = project(p09, p19, pop["assumptions"], args.year)
                csum = sum_in_polygon(wp, g)
                entry.update(p2009=p09, p2019=p19, r=round((p19 / p09) ** 0.1 - 1, 6), projection=cproj,
                             worldpop_county_2020=round(csum, 1), factors=scale_factors(cproj, csum))
            counties.append(entry)
            shapes_.append((g, cid))
        cgrid = rasterize(shapes_, out_shape=people.shape, transform=tf, fill=0, dtype="uint8") if shapes_ else \
            np.zeros(people.shape, "uint8")
        cprof = dict(prof, dtype="uint8")
        with rasterio.open(outd / "county_id_aoi.tif", "w", **cprof) as dst:
            dst.write(cgrid, 1)
        for c in counties:
            f = c.get("factors")
            print(f"  {c['name']:<10} AOI share {c['aoi_share']:.1%}  "
                  + (f"KNBS {c['p2009']:,}/{c['p2019']:,} r {c['r']:.4%}  {args.year} medium {c['projection']['medium']:,}  "
                     f"WorldPop county {c['worldpop_county_2020']:,.0f}  factor L/M/H "
                     f"{f['low']:.4f}/{f['medium']:.4f}/{f['high']:.4f}" if f else "NO KNBS FIGURES -> unit factor"))
        print(f"  WorldPop 2020 in AOI bbox {aoi_sum:,.0f} (unassigned to a county {1 - sum(c['aoi_share'] for c in counties):.4f})")
        man = {"area": a, "year": args.year, "unit": unit["unit"], "placeholder_population_json": pop.get("placeholder"),
               "unit_county": cf["properties"]["name"], "unit_county_osm": cf["properties"]["osm"],
               "worldpop_unit_county_2020": round(s_unit, 1), "projection": proj, "factors_A": fa,
               "worldpop_aoi_sum_2020": round(aoi_sum, 1), "counties": counties,
               "modes": {"A": "the population.json unit county's factor on every AOI pixel",
                         "B": "each county's own factor: KNBS 2009/2019 county totals, projected with population.json's "
                              "method and assumptions, divided by WorldPop 2020 over that county"},
               "sources": {"worldpop": WORLDPOP_URL, "worldpop_doi": "10.5258/SOTON/WP00645", "worldpop_file": str(wp),
                           "boundaries": "OSM admin_level=4, Geofabrik kenya-261104",
                           "projection": f"web/public/data/{a}/population.json", "knbs": "see 05_population.py KNBS"}}
        (outd / "population_manifest.json").write_text(json.dumps(man, indent=1))
    return 0


# ---------------------------------------------------------------------------------------------
# buildings: Google Open Buildings v3 points (centroid, area, confidence)
# ---------------------------------------------------------------------------------------------
OB_URL = "https://storage.googleapis.com/open-buildings-data/v3/points_s2_level_6_gzip_no_header/{t}_buildings.csv.gz"
OB_THRESHOLDS_URL = "https://storage.googleapis.com/open-buildings-data/v3/score_thresholds_s2_level_4.csv"
# S2 level-6 tiles covering each AOI (s2sphere RegionCoverer at level 6 on the bbox) -> their level-4 parent, whose
# row in score_thresholds_s2_level_4.csv gives the confidence threshold. Values copied from that file (v3).
OB_TILES = {"nairobi": {"182f": "183"}, "nyando": {"1781": "179", "182b": "183"}}
OB_THRESHOLD = {  # level-4 cell -> confidence threshold at 80 / 85 / 90 % precision
    "183": {"80": 0.667, "85": 0.716, "90": 0.778},
    "179": {"80": 0.674, "85": 0.730, "90": 0.768},
}
OB_PRECISION = "85"  # CHOICE: the middle published operating point; 80 and 90 are printed as a range


def read_buildings(paths_parent: list[tuple[Path, str]], bbox) -> dict:
    """Open Buildings points inside bbox: lon, lat, area_m2, confidence, and the threshold for each point's tile at
    every precision level. Columns of the no-header CSV: latitude, longitude, area_in_meters, confidence, plus_code."""
    import pandas as pd
    out = {k: [] for k in ("lon", "lat", "area_m2", "conf", "thr80", "thr85", "thr90")}
    for path, parent in paths_parent:
        thr = OB_THRESHOLD[parent]
        for ch in pd.read_csv(path, header=None, names=["lat", "lon", "area_m2", "conf", "pc"],
                              usecols=[0, 1, 2, 3], chunksize=2_000_000):
            m = (ch.lon >= bbox[0]) & (ch.lon <= bbox[2]) & (ch.lat >= bbox[1]) & (ch.lat <= bbox[3])
            ch = ch[m]
            for k in ("lon", "lat", "area_m2"):
                out[k].append(ch[k].to_numpy())
            out["conf"].append(ch.conf.to_numpy())
            for p in ("80", "85", "90"):
                out[f"thr{p}"].append(np.full(len(ch), thr[p]))
    return {k: (np.concatenate(v) if v else np.empty(0)) for k, v in out.items()}


def buildings_in_wet(b: dict, wet: np.ndarray, transform, crs, precision: str = OB_PRECISION) -> int:
    """Count buildings whose CENTROID falls in a wet cell (LIMITATION: a footprint that only overlaps a wet cell
    with its edge is not counted). Points outside the raster are not counted."""
    from pyproj import Transformer
    from rasterio.transform import rowcol
    keep = b["conf"] >= b[f"thr{precision}"]
    if not keep.any():
        return 0
    x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(b["lon"][keep], b["lat"][keep])
    r, c = rowcol(transform, x, y, op=np.floor)
    r, c = np.asarray(r).astype(np.int64), np.asarray(c).astype(np.int64)
    ok = (r >= 0) & (r < wet.shape[0]) & (c >= 0) & (c < wet.shape[1])
    return int(wet[r[ok], c[ok]].sum())


def cmd_buildings(args) -> int:
    for a in args.area:
        bbox = load_area(a)["bbox"]
        raw = rms_data() / "raw" / "open_buildings"
        paths = [(raw / f"{t}_buildings.csv.gz", parent) for t, parent in OB_TILES[a].items()]
        miss = [str(p) for p, _ in paths if not p.exists()]
        if miss:
            print(f"ERROR {a}: missing {miss} (download from {OB_URL})", file=sys.stderr)
            return 1
        t0 = time.time()
        b = read_buildings(paths, bbox)
        outd = rms_data() / "processed" / a / "exposure"
        outd.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(outd / "open_buildings_aoi.npz", **b)
        n = {p: int((b["conf"] >= b[f"thr{p}"]).sum()) for p in ("80", "85", "90")}
        print(f"{a}: {len(b['lon']):,} Open Buildings points in bbox ({time.time() - t0:.0f} s); kept at "
              f"80/85/90 % precision: {n['80']:,} / {n['85']:,} / {n['90']:,}  (used: {OB_PRECISION} %)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("buildings", help="Open Buildings points in the AOI bbox")
    s.add_argument("--area", action="append", required=True, choices=["nairobi", "nyando"])
    s.set_defaults(fn=cmd_buildings)
    s = sub.add_parser("prepare", help="scale factors + AOI WorldPop clip per area")
    s.add_argument("--area", action="append", required=True, choices=["nairobi", "nyando"])
    s.add_argument("--year", type=int, default=2026)
    s.add_argument("--worldpop", default=None)
    s.set_defaults(fn=cmd_prepare)
    s = sub.add_parser("boundaries", help="county polygons from the OSM snapshot")
    s.add_argument("--pbf", default=None)
    s.add_argument("--admin-level", default="4")
    s.set_defaults(fn=cmd_boundaries)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
