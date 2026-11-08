"""E-18: H3 hexagon layer of the AUDITED outputs, DATA ONLY ($RMS_DATA; nothing under web/).

Per area and scenario -> {out}/{rain}_{enso}.h3.json, one row per hex with any wet cell OR any exposed people or
buildings (operator ruling E-18; exposure is counted only in wet cells, so the two sets coincide -- asserted):
  h3                hex id (H3 v4 string), resolution --res (default 9)
  edge              true when the hex boundary is not wholly inside the AOI bbox ("partial hex": cells outside the
                    AOI are not in it, so its counts cover only part of its area)
  flooded_share     wet cells / AOI cells in the hex (cell COUNTS, not h3 area: no edge or projection bias)
  flooded_m2        wet cells x cell area (UTM)
  depth_mean_m      mean depth of the hex's wet cells; depth_max_m their max (2 dp)
  risk              contract class of depth_max_m (low < 0.3 <= medium <= 1.0 < high): the hex's worst cell
  people_low/medium/high  exposed people (exposure.json method: building-weighted, mode B, per projection),
                    integers by largest remainder so that the hex sums equal exposure.json exactly
  buildings_flooded Open Buildings footprints whose centroid cell is wet (exposure.json method)
  shelter_null_reason  only when the shelter fields are null by rule (RULING R19: a rural area until graph.json has
                    relocation targets -> "relocation sites not yet in graph")
  shelter_reachable / walk_min / shelter_id  the graph.json CLIENT (06 client_route, x3 near penalty): the MINIMUM
                    true walking minutes to the client's chosen usable safe shelter over every walk node INSIDE the hex
                    (a tap on the node); a hex with no walk node uses a tap at its centre. false/null: no route at all
RULES:
  * A 30 m cell belongs to the ONE hex containing its CENTRE (lon/lat of the UTM cell centre). Every AOI cell is
    therefore counted once; flooded area by hex == wet cells exactly.
  * A building belongs to the hex of the cell holding its centroid (the cell that decided it is flooded).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
RES = 9   # CHOICE (E-18 fit, R19): res 9 = ~128 cells of 30 m per hex at our latitudes; res 8 = ~900 (too coarse)


def _mod(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(HERE))
    spec.loader.exec_module(m)
    return m


def cell_hexes(mask: np.ndarray, transform, crs, res: int) -> np.ndarray:
    """uint64 H3 index (0 outside the mask) for every cell, by the cell CENTRE."""
    import h3.api.basic_int as h3i
    import rasterio.transform
    from pyproj import Transformer
    rr, cc = np.nonzero(mask)
    x, y = rasterio.transform.xy(transform, rr, cc)          # cell centres (offset="center")
    lon, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(np.asarray(x), np.asarray(y))
    out = np.zeros(mask.shape, np.uint64)
    out[rr, cc] = np.fromiter((h3i.latlng_to_cell(a, b, res) for a, b in zip(lat, lon)), np.uint64, len(rr))
    return out


def building_people(b: dict, county: np.ndarray, mask: np.ndarray, transform, crs, man: dict, mode: str,
                    precision: str):
    """Per kept building: (row, col, people[n, 3] low/medium/high) under the W2 rule of 05 exposed_building_weighted:
    a county's AOI total (WorldPop 2020 over AOI and county x the county factor) shared by footprint area. Buildings
    outside the raster or the mask, in county 0 or in a county without WorldPop, carry 0 people (as there)."""
    from pyproj import Transformer
    from rasterio.transform import rowcol
    keep = b["conf"] >= b[f"thr{precision}"]
    x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(b["lon"][keep], b["lat"][keep])
    r, c = rowcol(transform, x, y, op=np.floor)
    r, c = np.asarray(r).astype(np.int64), np.asarray(c).astype(np.int64)
    ok = (r >= 0) & (r < mask.shape[0]) & (c >= 0) & (c < mask.shape[1])
    area = b["area_m2"][keep].astype(float)
    inside = np.zeros(len(r), bool)
    inside[ok] = mask[r[ok], c[ok]]
    cid = np.zeros(len(r), int)
    cid[inside] = county[r[inside], c[inside]].astype(int)
    fa = man["factors_A"]
    fb = {e["id"]: e["factors"] for e in man["counties"] if e.get("factors")}
    wp = {e["id"]: e["worldpop_aoi_2020"] for e in man["counties"]}
    ppl = np.zeros((len(r), 3))
    for i in np.unique(cid[inside]):
        sel = inside & (cid == i)
        tot = float(area[sel].sum())
        if i == 0 or tot <= 0 or i not in wp:
            continue
        f = fa if mode == "A" else fb.get(i, fa)
        for j, s in enumerate(("low", "medium", "high")):
            ppl[sel, j] = wp[i] * f[s] * area[sel] / tot
    return r, c, ok, ppl


def largest_remainder(values: np.ndarray, keys: list, target: int) -> np.ndarray:
    """Integers summing to `target`: floors, then +1 to the largest fractional parts (ties: key order)."""
    fl = np.floor(values).astype(np.int64)
    k = int(target - fl.sum())
    if k < 0 or k > len(values):
        raise ValueError(f"largest_remainder: target {target} unreachable from sum {values.sum():.3f}")
    order = sorted(range(len(values)), key=lambda i: (-(values[i] - fl[i]), keys[i]))
    fl[order[:k]] += 1
    return fl


def hex_on_edge(h: str, bbox) -> bool:
    """The hex boundary (lon/lat) is not wholly inside the AOI bbox [W, S, E, N]: a partial hex."""
    import h3
    return not all(bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3] for lat, lon in h3.cell_to_boundary(h))


def aggregate(depth: np.ndarray, hexes: np.ndarray, cell_m2: float, bpos, ppl: np.ndarray | None,
              targets: dict | None, bbox) -> list[dict]:
    """Rows (without the shelter fields) for every hex with >= 1 wet cell. depth: NaN outside the AOI / dry.
    bpos = (r, c, ok) of the kept buildings; ppl their people (n, 3) or None; targets {low, medium, high} ints."""
    import h3
    sc = _mod("sc07", "07_scenarios.py")
    wet = np.isfinite(depth) & (depth > 0)
    aoi = hexes != 0
    if (wet & ~aoi).any():
        raise ValueError("a wet cell lies outside the AOI mask")
    hx_all, n_all = np.unique(hexes[aoi], return_counts=True)
    hw = hexes[wet]; dw = depth[wet]
    hx, inv = np.unique(hw, return_inverse=True)
    n_wet = np.bincount(inv)
    d_sum = np.bincount(inv, weights=dw)
    d_max = np.full(len(hx), -np.inf); np.maximum.at(d_max, inv, dw)
    n_aoi = n_all[np.searchsorted(hx_all, hx)]
    r, c, ok = bpos
    bw = np.zeros(len(r), bool); bw[ok] = wet[r[ok], c[ok]]
    bh = np.searchsorted(hx, hexes[r[bw], c[bw]])
    nb = np.bincount(bh, minlength=len(hx))
    rows = [{"h3": h3.int_to_str(int(h)), "edge": hex_on_edge(h3.int_to_str(int(h)), bbox), "flooded_share": round(int(w) / int(a), 3), "flooded_m2": int(round(w * cell_m2)),
             "depth_mean_m": round(float(s / w), 2), "depth_max_m": round(float(m), 2),
             "risk": ("dry", "low", "medium", "high")[int(sc.classify_risk(np.array([m]))[0])],
             "buildings_flooded": int(k)}
            for h, w, a, s, m, k in zip(hx, n_wet, n_aoi, d_sum, d_max, nb)]
    if ppl is not None:
        keys = [x["h3"] for x in rows]
        for j, s in enumerate(("low", "medium", "high")):
            v = np.bincount(bh, weights=ppl[bw, j], minlength=len(hx))
            ints = largest_remainder(v, keys, targets[s])
            for x, n in zip(rows, ints):
                x[f"people_{s}"] = int(n)
    return rows


NULL_RURAL = "relocation sites not yet in graph"


def shelter_null_reason(area_meta: dict, g: dict) -> str | None:
    """RULING R19 (2): a RURAL area's people are routed to relocation high ground, not only to OSM shelters. Until
    graph.json carries relocation targets (E-19: shelters with kind "relocation"), its hex shelter fields are null."""
    if area_meta.get("type") == "rural" and not any(s.get("kind") == "relocation" for s in g.get("shelters", [])):
        return NULL_RURAL
    return None


def walk_node_hexes(g: dict, res: int) -> dict:
    """{walk node index: H3 string} for every node used by a walk edge of graph.json."""
    import h3
    E = g["walk"]["edges"]
    return {n: h3.latlng_to_cell(g["nodes"][2 * n + 1], g["nodes"][2 * n], res) for n in set(E[0::3]) | set(E[1::3])}


def node_best(g: dict, field: dict, node_hex: dict) -> dict:
    """{hex: (minutes, shelter id)}: the lowest true walking minutes from a tap ON any walk node of the hex (snap 0 at
    the start), each node's shelter being the one client_route picks from it (client_field); ties: shelter id."""
    v = g["walk_kph"] / 3.6
    out = {}
    for n, (cost, sid, tr, sm) in field.items():
        h = node_hex.get(n)
        if h is None:
            continue
        m = (int(math.ceil(round((tr / 10 + sm / v) / 60.0, 6))), sid)
        if h not in out or m < out[h]:
            out[h] = m
    return out


def main(argv=None) -> int:
    import rasterio
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--area", required=True)
    ap.add_argument("--depth-dir", required=True, help="the audited model snapshot the app files were written from")
    ap.add_argument("--graph", required=True, help="graph.json v2 (E-16) for the shelter fields")
    ap.add_argument("--out-dir", required=True, help="under $RMS_DATA (never web/)")
    ap.add_argument("--res", type=int, default=RES)
    ap.add_argument("--population-mode", default="B", choices=["A", "B"])
    a = ap.parse_args(argv)
    out = Path(a.out_dir).resolve()
    if (REPO / "web").resolve() in out.parents or out == (REPO / "web").resolve():
        print("ERROR: --out-dir is inside web/ (E-18 is DATA ONLY)", file=sys.stderr)
        return 1
    sc, pop, rt = _mod("sc07", "07_scenarios.py"), _mod("pop05", "05_population.py"), _mod("rt06", "06_routing.py")
    import h3
    data = REPO / "web" / "public" / "data"
    area_meta = next(x for x in json.loads((data / "areas.json").read_text()) if x["id"] == a.area)
    bbox = area_meta["bbox"]
    pdir = sc.rms_data() / "processed" / a.area / "exposure"
    man = json.loads((pdir / "population_manifest.json").read_text())
    bld = dict(np.load(pdir / "open_buildings_aoi.npz"))
    with rasterio.open(pdir / "county_id_aoi.tif") as cds:
        ids, ids_tf = cds.read(1), cds.transform
    wp_people, wp_tf = pop.read_people(pdir / "worldpop_2020_aoi.tif")
    g = json.loads(Path(a.graph).read_text())
    node_hex = walk_node_hexes(g, a.res)
    hex_has_node = set(node_hex.values())
    out.mkdir(parents=True, exist_ok=True)
    grid = None
    print(f"h3 {a.area}: res {a.res}, depth {a.depth_dir} -> {out}")
    print(f"{'scenario':<12}{'hexes':>7}{'wet km2':>9}{'hex km2':>9}{'bld':>7}{'bld hex':>8}"
          f"{'people l/m/h (exposure.json)':>34}{'reach':>7}{'KiB':>7}{'gzKiB':>7}")
    bad = 0
    for key in sc.scenario_keys():
        depth, tf, crs, _ = sc._read(Path(a.depth_dir) / f"{key}_depth.tif")
        if grid != (tf, str(crs), depth.shape):
            grid = (tf, str(crs), depth.shape)
            mask = sc.aoi_mask(depth.shape, tf, crs, bbox)
            hexes = cell_hexes(mask, tf, crs, a.res)
            county = pop.ids_on_grid(ids, ids_tf, depth.shape, tf, crs)
            r, c, ok, ppl = building_people(bld, county, mask, tf, crs, man, a.population_mode, pop.OB_PRECISION)
            cell_m2 = abs(tf.a * tf.e)
        depth = np.where(mask, depth, np.nan)
        exp = json.loads((data / a.area / "scenarios" / f"{key}.exposure.json").read_text())
        # the exposure.json totals, recomputed here by the writer's own functions, must match the audited file
        wet = sc.classify_risk(depth) > 0
        w2 = pop.exposed_building_weighted(bld, wet, county, mask, tf, crs, man)[a.population_mode]
        nb = pop.buildings_in_wet(bld, wet, tf, crs)
        if w2 != exp["population"] or nb != exp["buildings"]:
            raise SystemExit(f"{key}: recomputed exposure {w2} / {nb} != exposure.json {exp['population']} / {exp['buildings']}")
        rows = aggregate(depth, hexes, cell_m2, (r, c, ok), ppl, exp["population"], bbox)
        reason = shelter_null_reason(area_meta, g)
        if reason:
            for x in rows:
                x["shelter_reachable"] = x["walk_min"] = x["shelter_id"] = None
                x["shelter_null_reason"] = reason
        else:
            field, cache = rt.client_field(g, key), {}
            best = node_best(g, field, node_hex)
            for x in rows:
                q = best.get(x["h3"])
                if q is None and x["h3"] not in hex_has_node:
                    lat, lon = h3.cell_to_latlng(x["h3"])
                    q = rt.client_from_field(g, field, lon, lat, cache)
                    q = None if "error" in q else (q["minutes"], q["shelter"])
                x["shelter_reachable"] = q is not None
                x["walk_min"], x["shelter_id"] = (q if q is not None else (None, None))
        # checks (each a SystemExit): hex sums == exposure.json; flooded area by hex == wet cells
        tot = {s: sum(x[f"people_{s}"] for x in rows) for s in ("low", "medium", "high")}
        hb, hm2 = sum(x["buildings_flooded"] for x in rows), sum(x["flooded_m2"] for x in rows)
        wet_m2 = float(wet.sum()) * cell_m2
        if tot != exp["population"] or hb != exp["buildings"] or abs(hm2 - wet_m2) > 0.005 * wet_m2:
            bad += 1
            print(f"  CHECK FAILED {key}: people {tot} vs {exp['population']}; buildings {hb} vs {exp['buildings']}; "
                  f"area {hm2} vs {wet_m2}")
        raw = json.dumps(rows, separators=(",", ":"))
        (out / f"{key}.h3.json").write_text(raw)
        import gzip
        gz = len(gzip.compress(raw.encode(), 9))
        p = exp["population"]
        print(f"{key:<12}{len(rows):>7,}{wet_m2 / 1e6:>9.3f}{hm2 / 1e6:>9.3f}{exp['buildings']:>7,}{hb:>8,}"
              f"{f'{p['low']:,}/{p['medium']:,}/{p['high']:,}':>34}{('null' if reason else f"{sum(bool(x['shelter_reachable']) for x in rows):,}"):>7}"
              f"{len(raw) / 1024:>7.0f}{gz / 1024:>7.0f}")
    print("CHECKS:", "ALL PASS (people, buildings == exposure.json; flooded area by hex == wet cells)" if not bad
          else f"{bad} scenario(s) FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
