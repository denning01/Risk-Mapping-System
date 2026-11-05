#!/usr/bin/env python
"""07_scenarios.py — flood-depth rasters -> the four contract files per scenario (docs/DATA_CONTRACT.md).

Two subcommands:

  standin  Build a MOCK stand-in depth (+ arrival) raster set for an area by rasterising the app's
           current mock flood polygons into the area's UTM grid. Every raster is tagged MOCK=1.
           Used only until model's hand-off (rms-audit/handoffs/flood-<area>.md) exists.

  write    Read <rain>_<enso>_depth.tif (float32 metres, NaN or <=0 = dry, projected CRS in metres)
           and optional <rain>_<enso>_arrival.tif (hours) for all 20 scenarios and write, under
           --data-dir (default web/public/data):
             <area>/scenarios/<rain>_<enso>.geojson         dissolved by (risk, arrival bin), simplified, WGS84
             <area>/scenarios/<rain>_<enso>.exposure.json   flooded_area_km2 from the raster
             <area>/scenarios/<rain>_<enso>.shelters.json   `safe` recomputed from the raster
             <area>/scenarios/<rain>_<enso>.routes.json
           Population / buildings / roads_cut / year and routes are not computed here yet (E-04, E-05):
           they are CARRIED from the existing files in --data-dir, and the exposure `source` is "mock"
           unless every input is real. `--source model` is refused if any input is MOCK.

Risk classes (contract): depth < 0.3 m = low, 0.3 <= depth <= 1.0 m = medium, depth > 1.0 m = high.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyproj import CRS, Transformer
from rasterio.features import rasterize, shapes
from rasterio.transform import from_origin, rowcol
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

REPO = Path(__file__).resolve().parents[1]
RAIN_VALUES = (50, 100, 150, 200, 250)
ENSO_VALUES = ("normal", "elnino")
RISK_NAMES = {1: "low", 2: "medium", 3: "high"}
LOW_MAX_M = 0.3   # contract: under 0.3 m = low
MED_MAX_M = 1.0   # contract: 0.3-1 m = medium, over 1 m = high
COORD_DP = 5      # 1e-5 deg ~ 1.1 m at the equator


def rms_data() -> Path:
    return Path(os.environ.get("RMS_DATA", "/Users/mac/IGAD/data"))


def scenario_keys():
    return [f"{r}_{e}" for r in RAIN_VALUES for e in ENSO_VALUES]


def reproject(geom, src, dst):
    """Reproject a shapely geometry (lon/lat axis order for EPSG:4326)."""
    tr = Transformer.from_crs(src, dst, always_xy=True)
    return shapely.transform(geom, lambda x, y: tr.transform(x, y), interleaved=False)


def utm_epsg(lon: float, lat: float) -> int:
    """WGS84 UTM zone EPSG for a point (326xx north, 327xx south)."""
    zone = int((lon + 180) // 6) + 1
    return (32700 if lat < 0 else 32600) + zone


# ---------------------------------------------------------------------------------------------
# core: raster -> classes -> polygons
# ---------------------------------------------------------------------------------------------

def classify_risk(depth: np.ndarray) -> np.ndarray:
    """uint8: 0 dry (NaN or <= 0), 1 low, 2 medium, 3 high."""
    d = np.where(np.isfinite(depth), depth, 0.0)
    out = np.zeros(d.shape, dtype=np.uint8)
    wet = d > 0
    out[wet & (d < LOW_MAX_M)] = 1
    out[wet & (d >= LOW_MAX_M) & (d <= MED_MAX_M)] = 2
    out[wet & (d > MED_MAX_M)] = 3
    return out


def _round_coords(obj, dp=COORD_DP):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(float(v), dp) for v in obj]
        return [_round_coords(v, dp) for v in obj]
    return obj


def flood_features(depth: np.ndarray, transform, crs, arrival: np.ndarray | None = None,
                   arrival_bin_h: float = 1.0, simplify_m: float = 15.0) -> tuple[list[dict], dict]:
    """Polygonise a depth raster into contract features, one per (risk, arrival bin).

    Returns (features, stats). stats: flooded_cells, pixel_area_m2, flooded_area_m2,
    polygon_area_m2 (dissolved, before simplification, in the raster CRS).
    """
    crs = CRS.from_user_input(crs)
    if not crs.is_projected or crs.axis_info[0].unit_name not in ("metre", "meter"):
        raise ValueError(f"depth raster must be in a projected CRS in metres, got {crs.to_string()}")
    risk = classify_risk(depth)
    flooded = risk > 0
    if arrival is not None:
        abin = np.where(np.isfinite(arrival), np.round(arrival / arrival_bin_h), -1).astype(np.int64)
    else:
        abin = np.full(depth.shape, -1, dtype=np.int64)
    abin = np.where(abin < -1, -1, abin)  # negative hours make no sense; treat as unknown
    # one integer label per (risk, arrival bin) among flooded cells; 0 = dry
    keys = np.stack([risk[flooded].astype(np.int64), abin[flooded]], axis=1)
    label = np.zeros(depth.shape, dtype=np.int32)
    uniq = np.empty((0, 2), dtype=np.int64)
    if keys.size:
        uniq, inv = np.unique(keys, axis=0, return_inverse=True)
        label[flooded] = inv.reshape(-1).astype(np.int32) + 1
    px_area = abs(transform.a * transform.e - transform.b * transform.d)

    parts: dict[int, list] = {}
    for geom, val in shapes(label, mask=flooded, transform=transform, connectivity=4):
        parts.setdefault(int(val), []).append(shape(geom))

    feats, poly_area = [], 0.0
    for i, (r, b) in enumerate(uniq, start=1):
        geom = unary_union(parts[i])
        poly_area += geom.area
        sel = label == i
        if simplify_m > 0:
            geom = geom.simplify(simplify_m, preserve_topology=True)
        geom = shapely.make_valid(reproject(geom, crs, "EPSG:4326"))
        geom = shapely.set_precision(geom, 10 ** -COORD_DP)
        polys = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type in ("Polygon", "MultiPolygon")]
        geom = unary_union(polys) if polys else None
        if geom is None or geom.is_empty:
            continue  # sliver collapsed by simplification/precision; its cells still count in area
        gj = mapping(geom)
        feats.append({
            "type": "Feature",
            "geometry": {"type": gj["type"], "coordinates": _round_coords(gj["coordinates"])},
            "properties": {
                "risk": RISK_NAMES[int(r)],
                "depth_m": round(float(np.nanmean(depth[sel])), 2),
                "arrival_h": None if b < 0 else round(float(b * arrival_bin_h), 2),
            },
        })
    order = {"low": 0, "medium": 1, "high": 2}
    feats.sort(key=lambda f: (order[f["properties"]["risk"]], f["properties"]["arrival_h"] or -1))
    n = int(flooded.sum())
    stats = {"flooded_cells": n, "pixel_area_m2": px_area, "flooded_area_m2": n * px_area,
             "polygon_area_m2": poly_area,
             "cells_by_risk": {RISK_NAMES[k]: int((risk == k).sum()) for k in (1, 2, 3)}}
    return feats, stats


def shelters_safety(shelters: list[dict], depth: np.ndarray, transform, crs) -> list[dict]:
    """safe = the shelter's cell is not flooded. A shelter outside the raster keeps safe=True and
    gets flagged in the returned list's `_outside` (stripped before writing)."""
    to_utm = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    flooded = classify_risk(depth) > 0
    out = []
    for s in shelters:
        x, y = to_utm(s["lon"], s["lat"])
        row, col = rowcol(transform, x, y, op=np.floor)
        row, col = int(row), int(col)
        inside = 0 <= row < depth.shape[0] and 0 <= col < depth.shape[1]
        s2 = dict(s)
        s2["safe"] = not (inside and bool(flooded[row, col]))
        s2["_outside"] = not inside
        out.append(s2)
    return out


# ---------------------------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------------------------

def _read(path: Path):
    with rasterio.open(path) as ds:
        return ds.read(1).astype("float32"), ds.transform, ds.crs, ds.tags()


def _dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    path.write_text(txt, encoding="utf-8")
    return len(txt.encode("utf-8"))


def _load_area(data_dir: Path, area: str) -> dict:
    areas = json.loads((data_dir / "areas.json").read_text())
    for a in areas:
        if a["id"] == area:
            return a
    raise SystemExit(f"area {area!r} not in {data_dir/'areas.json'}")


def cmd_standin(args) -> int:
    data_dir = Path(args.data_dir)
    a = _load_area(data_dir, args.area)
    w, s, e, n = a["bbox"]
    epsg = utm_epsg((w + e) / 2, (s + n) / 2)
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform
    xs, ys = zip(*[to_utm(x, y) for x in (w, e) for y in (s, n)])
    res = args.res
    x0, y1 = np.floor(min(xs) / res) * res, np.ceil(max(ys) / res) * res
    width = int(np.ceil((max(xs) - x0) / res)); height = int(np.ceil((y1 - min(ys)) / res))
    tf = from_origin(x0, y1, res, res)
    out = Path(args.out_dir or rms_data() / "processed" / args.area / "exposure" / "standin_mock")
    out.mkdir(parents=True, exist_ok=True)
    prof = dict(driver="GTiff", width=width, height=height, count=1, dtype="float32", crs=f"EPSG:{epsg}",
                transform=tf, nodata=np.nan, compress="deflate")
    print(f"standin {args.area}: EPSG:{epsg} {width}x{height} @ {res} m -> {out}")
    for key in scenario_keys():
        fc = json.loads((data_dir / args.area / "scenarios" / f"{key}.geojson").read_text())
        geoms = [reproject(shape(f["geometry"]), "EPSG:4326", f"EPSG:{epsg}") for f in fc["features"]]
        depth = rasterize(((g, f["properties"]["depth_m"]) for g, f in zip(geoms, fc["features"])),
                          out_shape=(height, width), transform=tf, fill=np.nan, dtype="float32")
        arr = rasterize(((g, f["properties"]["arrival_h"]) for g, f in zip(geoms, fc["features"])
                         if f["properties"]["arrival_h"] is not None),
                        out_shape=(height, width), transform=tf, fill=np.nan, dtype="float32")
        for kind, band in (("depth", depth), ("arrival", arr)):
            with rasterio.open(out / f"{key}_{kind}.tif", "w", **prof) as ds:
                ds.write(band, 1)
                ds.update_tags(MOCK="1", SOURCE=f"MOCK stand-in: rasterised {args.area}/scenarios/{key}.geojson "
                               "(Person B's hand-made mock), NOT model output")
        print(f"  {key}: {len(fc['features'])} mock features -> {int(np.isfinite(depth).sum())} wet cells")
    return 0


def cmd_write(args) -> int:
    data_dir, depth_dir = Path(args.data_dir), Path(args.depth_dir)
    scen_dir = data_dir / args.area / "scenarios"
    missing = [k for k in scenario_keys() if not (depth_dir / f"{k}_depth.tif").exists()]
    if missing:
        print(f"ERROR: {len(missing)} depth raster(s) missing in {depth_dir}: {missing}", file=sys.stderr)
        return 1
    print(f"write {args.area}: depth from {depth_dir} -> {scen_dir}  (source={args.source})")
    print(f"{'scenario':<12}{'feat':>5}{'low/med/high cells':>22}{'px km2':>9}{'poly km2':>9}"
          f"{'safe/shel':>10}{'geojson KB':>11}")
    problems = []
    for key in scenario_keys():
        depth, tf, crs, tags = _read(depth_dir / f"{key}_depth.tif")
        is_mock = tags.get("MOCK") == "1"
        arrival = None
        ap = depth_dir / f"{key}_arrival.tif"
        if ap.exists():
            arrival, atf, acrs, atags = _read(ap)
            if atf != tf or acrs != crs or arrival.shape != depth.shape:
                raise SystemExit(f"{ap} grid differs from its depth raster")
            is_mock = is_mock or atags.get("MOCK") == "1"
        feats, st = flood_features(depth, tf, crs, arrival, args.arrival_bin_h, args.simplify_m)

        exp_old = json.loads((scen_dir / f"{key}.exposure.json").read_text())
        carried_mock = exp_old.get("source") != "model"
        if args.source == "model" and (is_mock or carried_mock):
            raise SystemExit(f"{key}: --source model refused: depth MOCK={is_mock}, carried exposure "
                             f"source={exp_old.get('source')!r}")
        exposure = {
            "year": exp_old["year"], "population": exp_old["population"], "buildings": exp_old["buildings"],
            "flooded_area_km2": round(st["flooded_area_m2"] / 1e6, 2), "roads_cut": exp_old["roads_cut"],
            "source": args.source,
        }
        shelters = shelters_safety(json.loads((scen_dir / f"{key}.shelters.json").read_text()), depth, tf, crs)
        for s in shelters:
            if s.pop("_outside"):
                problems.append(f"{key}: shelter {s['id']} is outside the depth raster (safe kept True)")
        safe_ids = {s["id"] for s in shelters if s["safe"]}
        routes = json.loads((scen_dir / f"{key}.routes.json").read_text())
        for r in routes:
            if r["shelter_id"] is not None and r["shelter_id"] not in safe_ids:
                problems.append(f"{key}: route {r['origin_id']} -> {r['shelter_id']} targets an UNSAFE shelter "
                                "(carried mock route; E-05 recomputes)")

        kb = _dump(scen_dir / f"{key}.geojson", {"type": "FeatureCollection", "features": feats}) / 1024
        _dump(scen_dir / f"{key}.exposure.json", exposure)
        _dump(scen_dir / f"{key}.shelters.json", shelters)
        _dump(scen_dir / f"{key}.routes.json", routes)
        c = st["cells_by_risk"]
        print(f"{key:<12}{len(feats):>5}{c['low']:>8}/{c['medium']}/{c['high']:<7}"
              f"{st['flooded_area_m2']/1e6:>9.2f}{st['polygon_area_m2']/1e6:>9.2f}"
              f"{len(safe_ids):>5}/{len(shelters):<4}{kb:>11.1f}")
        if kb > args.max_kb:
            problems.append(f"{key}: geojson {kb:.0f} KB exceeds --max-kb {args.max_kb}")
    print(f"\n{len(problems)} warning(s)")
    for p in problems:
        print("  WARN", p)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("standin", help="MOCK depth rasters from the app's current mock polygons")
    s.add_argument("--area", required=True, choices=["nairobi", "nyando"])
    s.add_argument("--data-dir", default=str(REPO / "web" / "public" / "data"))
    s.add_argument("--out-dir", default=None)
    s.add_argument("--res", type=float, default=30.0)
    s.set_defaults(fn=cmd_standin)
    w = sub.add_parser("write", help="depth rasters -> contract files for all 20 scenarios")
    w.add_argument("--area", required=True, choices=["nairobi", "nyando"])
    w.add_argument("--depth-dir", required=True)
    w.add_argument("--data-dir", default=str(REPO / "web" / "public" / "data"))
    w.add_argument("--source", choices=["mock", "model"], default="mock")
    w.add_argument("--simplify-m", type=float, default=15.0, help="Douglas-Peucker tolerance in metres")
    w.add_argument("--arrival-bin-h", type=float, default=1.0)
    w.add_argument("--max-kb", type=float, default=3072, help="warn above this geojson size")
    w.set_defaults(fn=cmd_write)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
