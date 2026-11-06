"""M-03 terrain for one area: DEM (WGS84) -> UTM 30 m -> conditioned DEM, D8, accumulation, channels, HAND, slope.

    .venv/bin/python pipeline/02_terrain.py nyando [--channel-km2 1.0] [--sweep]

Reads  $RMS_DATA/raw/<area>/dem_glo30.tif (export_bbox, so upstream catchment is included).
Writes $RMS_DATA/processed/<area>/model/{dem_utm,dem_cond,flowdir,acc,channels,hand,slope}.tif, terrain.json,
       and sanity PNGs terrain_{hand,slope,channels}.png.
--sweep reports, per channel threshold and inside the AOI only, the channel length and its agreement with
OpenStreetMap waterways (river|stream, Overpass, cached): share of channel cells within 60 m of an OSM
waterway, share of OSM waterway cells within 60 m of a channel, and their F1 — the evidence for the
threshold. Default 10 km2: the channel length closest to the mapped OSM length (rural OSM is incomplete,
so "agreement" is a floor, not an accuracy).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from rasterio.warp import Resampling
import requests
from pyproj import Transformer
from rasterio.features import rasterize
from scipy import ndimage
from shapely import LineString, box, ops

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.lib import config, terrain  # noqa: E402
from pipeline.lib.paths import model_dir, provenance, raw_dir  # noqa: E402
from pipeline.lib.rio import RES, to_utm, write  # noqa: E402,F401

PERM_WATER_PCT = 80   # JRC occurrence >= 80 % = permanent water (plan §3 skeleton); also excluded from floods (M-04)


def png(path, arr, title, cmap, vmin=None, vmax=None, label=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 7))
    im = ax.imshow(arr, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
    fig.colorbar(im, ax=ax, shrink=0.8, label=label)
    ax.set_title(title, fontsize=10)
    ax.set_axis_off()
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def osm_waterways(area: str, bbox, cache: Path) -> list:
    """OSM river|stream ways in bbox [w,s,e,n] via Overpass (cached; the public endpoint is often busy)."""
    f = cache / "osm_waterways.json"
    if not f.exists():
        w, s, e, n = bbox
        q = f'[out:json][timeout:90];way["waterway"~"^(river|stream)$"]({s},{w},{n},{e});out geom;'
        r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q},
                          headers={"User-Agent": "igad-flood-ews-mvp/0.1"}, timeout=180)
        r.raise_for_status()
        f.write_text(r.text)
    return json.loads(f.read_text())["elements"]


DIAGONAL = (128, 2, 8, 32)   # NE, SE, SW, NW in pysheds' dirmap


def channel_length_km(ch: np.ndarray, fdir: np.ndarray) -> float:
    """F3.8: each channel cell contributes its D8 link length — RES, or RES*sqrt(2) when it drains diagonally."""
    step = np.where(np.isin(fdir, DIAGONAL), RES * np.sqrt(2), RES)
    return float(step[ch].sum()) / 1000


def channel_vs_osm(acc_km2, thresholds, osm, aoi, fdir, tol_cells=2):
    rows = []
    osm_in = osm & aoi
    osm_near = ndimage.binary_dilation(osm, iterations=tol_cells)
    for t in thresholds:
        ch = (acc_km2 >= t) & aoi
        ch_near = ndimage.binary_dilation(ch, iterations=tol_cells)
        p = float((ch & osm_near).sum() / max(ch.sum(), 1))
        r = float((osm_in & ch_near).sum() / max(osm_in.sum(), 1))
        rows.append({"channel_km2": t, "channel_km": round(channel_length_km(ch, fdir), 1),
                     "on_osm": round(p, 3), "osm_found": round(r, 3),
                     "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0})
    return rows


def main(area: str, channel_km2: float, sweep: bool):
    cfg = config.load(area)
    out = model_dir(area)
    out.mkdir(parents=True, exist_ok=True)
    dem, grid = to_utm(raw_dir(area) / "dem_glo30.tif", cfg["utm_epsg"])
    write(out / "dem_utm.tif", dem, grid)
    jrc, _ = to_utm(raw_dir(area) / "jrc_occurrence.tif", cfg["utm_epsg"], Resampling.max, like=grid)
    perm = jrc >= PERM_WATER_PCT
    h = terrain.hydro(dem, grid["transform"], grid["crs"], channel_km2, extra_drainage=perm)
    slope = terrain.slope_deg(dem, RES, RES)
    report = {"provenance": provenance(), "flats_routed": h["flats_routed"], "sink_cells": int(h["sinks"].sum()), "perm_water_pct": PERM_WATER_PCT, "perm_water_cells": int(perm.sum()), "area": area, "utm_epsg": cfg["utm_epsg"], "res_m": RES, "shape": [grid["height"], grid["width"]],
              "channel_km2": channel_km2, "channel_cells": int(h["channels"].sum()),
              "hand_m": {q: float(np.nanpercentile(h["hand"], p)) for q, p in
                         (("p01", 1), ("p50", 50), ("p99", 99))},
              "hand_nan_share": float(np.isnan(h["hand"]).mean()),
              "slope_deg": {"p50": float(np.nanpercentile(slope, 50)), "p99": float(np.nanpercentile(slope, 99))},
              "fill_depth_m_max": float(np.nanmax(h["cond"] - dem))}
    to_utm_xy = Transformer.from_crs(4326, grid["crs"], always_xy=True).transform
    aoi = rasterize([(ops.transform(to_utm_xy, box(*cfg["bbox"])), 1)], out_shape=dem.shape,
                    transform=grid["transform"]).astype(bool)
    fill = h["cond"] - dem
    report["aoi"] = {"bbox": cfg["bbox"], "cells": int(aoi.sum()),
                     "hand_m": {q: float(np.nanpercentile(h["hand"][aoi], p)) for q, p in
                                (("p01", 1), ("p50", 50), ("p99", 99))},
                     "hand_nan_share": float(np.isnan(h["hand"][aoi]).mean()),
                     "fill_gt1m_km2": round(float((fill[aoi] > 1).sum()) * h["cell_km2"], 2),
                     "fill_max_m": float(np.nanmax(fill[aoi]))}
    ways = osm_waterways(area, cfg["bbox"], out)
    lines = [ops.transform(to_utm_xy, LineString([(p["lon"], p["lat"]) for p in w["geometry"]]))
             for w in ways if len(w.get("geometry", [])) > 1]
    osm = rasterize([(ln, 1) for ln in lines], out_shape=dem.shape, transform=grid["transform"],
                    all_touched=True).astype(bool)
    aoi_poly = ops.transform(to_utm_xy, box(*cfg["bbox"]).segmentize(0.001))
    report["osm"] = {"ways": len(lines), "cells_in_aoi": int((osm & aoi).sum()),
                     "length_km_in_aoi": round(sum(ln.intersection(aoi_poly).length for ln in lines) / 1000, 1),
                     "source": "OpenStreetMap contributors (ODbL), Overpass waterway=river|stream"}
    acc_km2 = h["acc"] * h["cell_km2"]
    thresholds = (0.25, 1, 2, 5, 10, 25, 50, 100) if sweep else ()
    report["sweep_vs_osm"] = channel_vs_osm(acc_km2, thresholds, osm, aoi, h["fdir"])
    report["chosen_vs_osm"] = channel_vs_osm(acc_km2, (channel_km2,), osm, aoi, h["fdir"])[0]
    write(out / "dem_cond.tif", h["cond"], grid)
    write(out / "flowdir.tif", terrain.fdir_for_disk(h["fdir"], dem), grid, "int16", terrain.FDIR_NODATA)
    write(out / "acc.tif", h["acc"], grid)
    write(out / "channels.tif", h["channels"], grid, "uint8", 255)
    write(out / "drainage.tif", h["drainage"], grid, "uint8", 255)
    write(out / "perm_water.tif", perm, grid, "uint8", 255)
    write(out / "hand.tif", h["hand"], grid)
    write(out / "hand_filled.tif", h["hand_filled"], grid)  # F2.10: pysheds HAND on the filled DEM, for comparison
    write(out / "hand_index.tif", h["hand_index"], grid, "int64", -1)
    write(out / "slope.tif", slope, grid)
    png(out / "terrain_hand.png", h["hand"], f"{cfg['name']} HAND (m), channels >= {channel_km2} km²",
        "viridis_r", 0, 30, "m")
    png(out / "terrain_slope.png", slope, f"{cfg['name']} slope (deg)", "magma", 0, 30, "deg")
    rows, cols = np.where(aoi)
    win = (slice(rows.min(), rows.max() + 1), slice(cols.min(), cols.max() + 1))
    for name, arr, title, cmap, lo, hi, lab in (
            ("hand", h["hand"], f"HAND (m), channels >= {channel_km2} km²", "viridis_r", 0, 30, "m"),
            ("slope", slope, "slope (deg)", "magma", 0, 30, "deg")):
        png(out / f"terrain_{name}.png", arr[win], f"{cfg['name']} AOI — {title} — GLO-30, UTM {cfg['utm_epsg']}",
            cmap, lo, hi, lab)
    # display only: thicken 1-cell lines so they survive downsampling in the PNG
    thick = lambda m: ndimage.binary_dilation(m, iterations=2)  # noqa: E731
    ch_t, osm_t = thick(h["channels"]), thick(osm)
    ch_img = np.where(ch_t & osm_t, 3.0, np.where(ch_t, 2.0, np.where(osm_t, 1.0, np.nan)))
    ch_img[perm & np.isnan(ch_img)] = 0.0
    png(out / "terrain_channels.png", ch_img[win],
        f"{cfg['name']} AOI — channels >= {channel_km2} km²: 3 both, 2 DEM only, 1 OSM only, 0 permanent water "
        "(lines thickened for display)",
        "viridis", 0, 3, "class")
    (out / "terrain.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("area")
    ap.add_argument("--channel-km2", type=float, default=10.0)
    ap.add_argument("--sweep", action="store_true")
    a = ap.parse_args()
    main(a.area, a.channel_km2, a.sweep)
