"""M-04 runoff and flood layers for one area, on the M-03 UTM 30 m grid.

    .venv/bin/python pipeline/03_runoff_flood.py nyando [--k K] [--alpha 0.4]

Reads  $RMS_DATA/processed/<area>/model/{hand,hand_index,slope,flowdir,channels,perm_water}.tif (M-03),
       $RMS_DATA/raw/<area>/{worldcover_2021,soilgrids_clay_0-30cm,soilgrids_sand_0-30cm}.tif,
       $RMS_DATA/raw/<area>/chirps/monthly/YYYY-MM.tif.
Writes $RMS_DATA/processed/<area>/model/{cn,hsg}.tif, scenarios/<rain>_<enso>_depth.tif (float32 m, NaN = dry,
       UTM; AGENTS.md model -> exposure interface), runoff_flood.json, flood_<rain>_<enso>.png.

Method (plan §4.2-4.5):
  CN      = TR-55 row for the WorldCover class x NEH 630 hydrologic soil group from SoilGrids topsoil texture.
  P       = scenario rain (mm in 24 h, uniform over the catchment); El Nino: P x CHIRPS OND ratio over the AOI.
  Q       = SCS-CN runoff per cell; V_up = runoff VOLUME over each cell's upstream area (sum Q x cell km2, 1000 m3, D8).
  h       = k * V_up^alpha at the drainage cell each cell drains to (hand_index); alpha 0.4 = downstream depth-
            discharge exponent (Leopold & Maddock 1953), so stage grows with catchment size (F4.2; the plan's mean-
            depth form gave every channel the same stage).
  flooded = HAND < h, slope < 15 deg, 8-connected to a channel or water, water itself excluded (water = JRC >= 80 %
            OR WorldCover 2021 class 80).
  depth   = h - HAND; risk per docs/DATA_CONTRACT.md (< 0.3 low, 0.3-1 medium, > 1 high).
HAND is raw-DEM height above the FILLED level of the drainage cell (F2.10/F2.13); closed depressions have HAND 0
and flood in every scenario with depth = h, not pond depth (F2.14). k is UNCALIBRATED until M-05 (Sentinel-1 2023).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.warp import Resampling
from shapely import box, ops

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.lib import config, runoff, terrain  # noqa: E402
from pipeline.lib.paths import model_dir, provenance, raw_dir, refuse_if_posted  # noqa: E402
from pipeline.lib.rio import grid_of, read, to_utm, write  # noqa: E402

RAINS = (50, 100, 150, 200, 250)        # docs/DATA_CONTRACT.md
ENSO = ("normal", "elnino")
CLIM = (1991, 2020)                     # WMO standard normal period
EVENT_YEAR = 2023
SEASON = (10, 11, 12)                   # OND short rains
ALPHA = 0.4                             # Leopold & Maddock 1953 (USGS PP 252 p.16), downstream f
# UNCALIBRATED until M-05. Arbitrary anchor, not an observation: the Nyando outlet (3,422 km2) stage at 150 mm/24 h
# normal = 3.05 m, the stage the R4 mean-depth form gave every channel (auditor F4.2). 3.05 / 321,970^0.4 = 0.0191.
K_PROVISIONAL = 0.0191


def calibrated_k(area: str):
    """M-05: k from processed/<area>/model/backtest/backtest.json (05_backtest.py, best F1 against the Sentinel-1
    mask), or None when the area has no backtest yet (then K_PROVISIONAL, tagged calibrated=false)."""
    f = model_dir(area) / "backtest" / "backtest.json"
    if not f.exists():
        return None
    b = json.loads(f.read_text())
    if b["best"].get("on_grid_edge", b["best"]["k"] in (b["curve"][0]["k"], b["curve"][-1]["k"])):
        return None   # argmax on the edge of the k grid is not an optimum: k is not identified by this backtest
    return {"k": b["best"]["k"], "f1": b["best"]["all"]["f1"], "iou": b["best"]["all"]["iou"],
            "precision": b["best"]["all"]["precision"], "recall": b["best"]["all"]["recall"],
            "commit": b["provenance"]["git_commit"]}


def aoi_mask(cfg, grid) -> np.ndarray:
    """Same construction as 02_terrain.py (F2.15: one AOI mask definition for every reported number)."""
    to_utm_xy = Transformer.from_crs(4326, grid["crs"], always_xy=True).transform
    return rasterize([(ops.transform(to_utm_xy, box(*cfg["bbox"])), 1)], out_shape=(grid["height"], grid["width"]),
                     transform=grid["transform"]).astype(bool)


def chirps_ratio(area: str, bbox) -> dict:
    """OND EVENT_YEAR total / mean OND total CLIM, both averaged over CHIRPS pixels whose centre is in bbox."""
    d = raw_dir(area) / "chirps" / "monthly"
    years = sorted({int(p.stem[:4]) for p in d.glob("*.tif")})
    totals, n_px = {}, None
    for y in years:
        files = [d / f"{y}-{m:02d}.tif" for m in SEASON]
        if not all(f.exists() for f in files):
            continue
        acc = None
        for f in files:
            with rasterio.open(f) as ds:
                a = ds.read(1).astype("float64")
                if ds.nodata is not None:
                    a[a == ds.nodata] = np.nan
                a[a < 0] = np.nan
                rows, cols = np.mgrid[0:ds.height, 0:ds.width]
                xs, ys = rasterio.transform.xy(ds.transform, rows.ravel(), cols.ravel())
                xs, ys = np.asarray(xs).reshape(a.shape), np.asarray(ys).reshape(a.shape)
                inside = (xs >= bbox[0]) & (xs <= bbox[2]) & (ys >= bbox[1]) & (ys <= bbox[3])
                a = np.where(inside, a, np.nan)
            acc = a if acc is None else acc + a
        totals[y] = acc
        n_px = int(np.isfinite(acc).sum())
    clim_years = [y for y in totals if CLIM[0] <= y <= CLIM[1]]
    clim = np.nanmean(np.stack([totals[y] for y in clim_years]), axis=0)
    ratio = runoff.season_ratio(totals[EVENT_YEAR], clim)
    area_mean = {y: float(np.nanmean(t)) for y, t in totals.items()}
    rank, n_years = runoff.season_rank(area_mean, EVENT_YEAR, CLIM[0], EVENT_YEAR)   # F5.8: fixed start, not min(totals)
    wetter = sorted((y for y in area_mean if area_mean[y] > area_mean[EVENT_YEAR]), key=area_mean.get, reverse=True)
    return {"ratio": round(ratio, 4), "event": f"OND {EVENT_YEAR}", "event_mm": round(area_mean[EVENT_YEAR], 1),
            "clim_mm": round(float(np.nanmean(clim)), 1), "clim_years": [min(clim_years), max(clim_years)],
            "n_clim_years": len(clim_years), "pixels": n_px, "rank_wettest": rank, "of_years": n_years, "wetter_years": wetter,
            "wetter_mm": {str(y): round(area_mean[y], 1) for y in wetter},
            "years": [min(totals), max(totals)], "bbox": list(bbox),
            "source": "CHIRPS v2.0 monthly 0.05 deg (Funk et al. 2015, doi:10.1038/sdata.2015.66), UCSB CHC"}


def png(path, depth, aoi, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    rows, cols = np.where(aoi)
    win = (slice(rows.min(), rows.max() + 1), slice(cols.min(), cols.max() + 1))
    r = runoff.risk_class(depth[win]).astype(float)
    r[r == 0] = np.nan
    fig, ax = plt.subplots(figsize=(9, 8))
    im = ax.imshow(r, cmap=ListedColormap(["#fde725", "#f98e09", "#bc3754"]), vmin=0.5, vmax=3.5,
                   interpolation="nearest")
    cb = fig.colorbar(im, ax=ax, shrink=0.7, ticks=[1, 2, 3])
    cb.ax.set_yticklabels(["low < 0.3 m", "medium 0.3-1 m", "high > 1 m"])
    ax.set_title(title, fontsize=9)
    ax.set_axis_off()
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def choose_k(area: str, cfg: dict, k: float | None):
    """(k, own calibration or None, transferred calibration or None). An explicit k wins (uncalibrated); else this
    area's backtest; else the config's k_transfer_from area's backtest (tagged uncalibrated); else K_PROVISIONAL."""
    if k is not None:
        return k, None, None
    cal = calibrated_k(area)
    if cal:
        return cal["k"], cal, None
    if cfg.get("k_transfer_from"):
        transfer = calibrated_k(cfg["k_transfer_from"])
        if transfer is None:
            sys.exit(f"REFUSED: k_transfer_from {cfg['k_transfer_from']} has no valid calibration")
        return transfer["k"], None, transfer
    return K_PROVISIONAL, None, None


def main(area: str, k: float | None, alpha: float):
    prov = provenance()   # at START (see 02_terrain.py)
    cfg = config.load(area)
    k, cal, transfer = choose_k(area, cfg, k)
    m, raw = model_dir(area), raw_dir(area)
    grid = grid_of(m / "hand.tif")
    # One DEM per area (operator ruling 2026-11-06): the terrain this run builds on must come from the configured DEM.
    dem = json.loads((m / "terrain.json").read_text()).get("dem") or {}
    if dem.get("file") != cfg["dem_file"]:
        sys.exit(f"REFUSED: terrain built from {dem.get('file')} but config says {cfg['dem_file']}; re-run 02 first")
    epsg = cfg["utm_epsg"]
    hand = read(m / "hand.tif")
    hidx = read(m / "hand_index.tif").astype("int64")
    slope = read(m / "slope.tif")
    fd = read(m / "flowdir.tif").astype("int64")
    fd[fd == terrain.FDIR_NODATA] = 0
    channels = read(m / "channels.tif") == 1
    perm = read(m / "perm_water.tif") == 1
    aoi = aoi_mask(cfg, grid)
    cell_km2 = abs(grid["transform"].a * grid["transform"].e) / 1e6

    lc, _ = to_utm(raw / "worldcover_2021.tif", epsg, Resampling.mode, like=grid)
    clay, _ = to_utm(raw / "soilgrids_clay_0-30cm.tif", epsg, Resampling.bilinear, like=grid)
    sand, _ = to_utm(raw / "soilgrids_sand_0-30cm.tif", epsg, Resampling.bilinear, like=grid)
    soil_filled = None
    if cfg.get("soil_gap_fill") == "nearest":
        # M-07: SoilGrids has no texture under most of central Nairobi (55 % of the AOI had HSG unknown -> CN NaN ->
        # no runoff). Take the nearest SoilGrids prediction. Off for Nyando (its posted rasters were built without it).
        clay, gap = runoff.fill_nearest(clay)
        sand, _ = runoff.fill_nearest(sand)
        soil_filled = gap
    hsg = runoff.hsg_from_texture(clay, sand)
    cn = runoff.curve_number(lc, hsg)
    # Water never "floods": JRC occurrence >= 80 % (perm, from M-03) OR WorldCover 2021 permanent water (class 80).
    # The JRC rule alone let 5.22 km2 of Lake Victoria margin near (34.826, -0.314) — DEM flattened at 1133.00 m,
    # WorldCover 80, JRC occurrence 69 % — show as "flooded" in every scenario (found in the M-06 map).
    water = runoff.water_mask(perm, lc)
    write(m / "cn.tif", cn, grid)
    write(m / "hsg.tif", np.where(hsg < 0, 255, hsg.astype("int16")), grid, "uint8", 255)

    report = {"provenance": prov, "area": area, "k": k, "alpha": alpha, "k_calibrated": cal is not None,
              "k_note": (f"calibrated in M-05 against the Sentinel-1 Nov 2023 flood mask (05_backtest.py at {cal['commit']}): "
                         f"best F1 {cal['f1']}, IoU {cal['iou']}, precision {cal['precision']}, recall {cal['recall']}"
                         if cal else
                         f"NOT calibrated here: this area's own backtest did not identify k (see backtest/backtest.json); "
                         f"k transferred from the {cfg['k_transfer_from']} calibration (05_backtest.py at {transfer['commit']}, "
                         f"F1 {transfer['f1']} there)" if transfer else "provisional, NOT calibrated (anchor: outlet stage 3.05 m at 150 mm normal); "
                         "M-05 calibrates k on a Sentinel-1 flood mask"),
              "stage_form": "h = k * V_up^alpha, V_up = upstream runoff volume (1000 m3); alpha 0.4 Leopold & Maddock 1953 USGS PP 252 p.16",
              "aoi_cells": int(aoi.sum()), "cell_km2": cell_km2, "max_slope_deg": 15.0,
              "cn_table": {str(c): {"tr55": t, "A_B_C_D": list(v)} for c, (t, v) in runoff.CN_TABLE.items()}}
    lcv = lc[aoi]
    report["aoi_landcover_share"] = {str(int(c)): round(float((lcv == c).mean()), 4) for c in np.unique(lcv[np.isfinite(lcv)])}
    report["aoi_hsg_share"] = {runoff.HSG[i]: round(float((hsg[aoi] == i).mean()), 4) for i in range(4)}
    report["aoi_hsg_share"]["unknown"] = round(float((hsg[aoi] < 0).mean()), 4)
    report["aoi_water_km2"] = {"jrc_ge80": round(float((perm & aoi).sum()) * cell_km2, 2),
                               "worldcover80_not_jrc": round(float(((lc == 80) & ~perm & aoi).sum()) * cell_km2, 2)}
    report["soil_gap_fill"] = ({"method": "nearest SoilGrids cell", "aoi_share_filled": round(float(soil_filled[aoi].mean()), 4)}
                               if soil_filled is not None else None)
    report["aoi_cn"] = {"mean": round(float(np.nanmean(cn[aoi])), 2), "nan_share": round(float(np.isnan(cn[aoi]).mean()), 5)}
    report["elnino"] = chirps_ratio(area, cfg["bbox"])
    ratio = report["elnino"]["ratio"]

    report["scenarios"] = {}
    for enso in ENSO:
        for rain in RAINS:
            p = rain * (ratio if enso == "elnino" else 1.0)
            depth, h, q = runoff.scenario_depth(p, cn, fd, grid["transform"], grid["crs"], hand, hidx, slope,
                                                channels | water, water, k, alpha, cell_km2)
            write(m / "scenarios" / f"{rain}_{enso}_depth.tif", depth, grid,
                  tags={"calibrated": str(cal is not None).lower(), "dem": dem["file"], "dem_product": dem["product"],
                        "dem_licence": dem["licence"], "k": k, "alpha": alpha, "rain_mm": rain, "enso": enso, "p_mm": round(p, 1),
                        "elnino_ratio": ratio, "git_commit": report["provenance"]["git_commit"],
                        "dirty": report["provenance"]["dirty"], "producer": "pipeline/03_runoff_flood.py",
                        "units": "m", "nodata": "NaN = dry"})
            r = runoff.risk_class(depth[aoi])
            report["scenarios"][f"{rain}_{enso}"] = {
                "rain_mm": rain, "p_mm": round(p, 1), "aoi_q_mean_mm": round(float(np.nanmean(q[aoi])), 2),
                "aoi_h_drain_m_p50_p99": [round(float(np.nanpercentile(h[aoi & np.isfinite(depth)], x)), 2)
                                          if np.isfinite(depth[aoi]).any() else None for x in (50, 99)],
                "flooded_km2": round(float((r > 0).sum()) * cell_km2, 2),
                "low_km2": round(float((r == 1).sum()) * cell_km2, 2),
                "medium_km2": round(float((r == 2).sum()) * cell_km2, 2),
                "high_km2": round(float((r == 3).sum()) * cell_km2, 2),
                "depth_m_max": round(float(np.nanmax(depth[aoi])), 2) if np.isfinite(depth[aoi]).any() else None}
            print(json.dumps({f"{rain}_{enso}": report["scenarios"][f"{rain}_{enso}"]}), flush=True)
            if (rain, enso) in ((150, "normal"), (150, "elnino")):
                png(m / f"flood_{rain}_{enso}.png", depth, aoi,
                    f"{cfg['name']} — {rain} mm/24 h, {enso} (P = {p:.0f} mm) — k = {k} UNCALIBRATED, alpha = {alpha} "
                    f"— screening level")
    (m / "runoff_flood.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k_: report[k_] for k_ in ("aoi_landcover_share", "aoi_hsg_share", "aoi_cn", "elnino")}, indent=1))


def elnino_only(area: str):
    """Refresh runoff_flood.json["elnino"] (ratio, rank) without touching any raster. The ratio itself is applied
    to the posted depth rasters; refuse if it changed (that would need a full, announced rewrite)."""
    cfg = config.load(area)
    f = model_dir(area) / "runoff_flood.json"
    rep = json.loads(f.read_text())
    new = chirps_ratio(area, cfg["bbox"])
    if new["ratio"] != rep["elnino"]["ratio"]:
        sys.exit(f"REFUSED: ratio {rep['elnino']['ratio']} -> {new['ratio']} changes the depth rasters; full re-run needed")
    new["provenance"] = provenance()
    rep["elnino"] = new
    f.write_text(json.dumps(rep, indent=2))
    print(json.dumps(new, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("area")
    ap.add_argument("--k", type=float, default=None,
                    help="override; default = backtest k if backtest.json exists (calibrated), else K_PROVISIONAL")
    ap.add_argument("--alpha", type=float, default=ALPHA)
    ap.add_argument("--rewrite-posted", action="store_true", help="operator was told 'about to rewrite <area> rasters'")
    ap.add_argument("--elnino-only", action="store_true",
                    help="recompute only the El Nino block of runoff_flood.json; writes NO raster")
    a = ap.parse_args()
    if a.elnino_only:
        elnino_only(a.area)
    else:
        refuse_if_posted(a.area, a.rewrite_posted)
        main(a.area, a.k, a.alpha)
