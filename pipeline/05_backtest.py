"""M-05 backtest and calibration of k against the Sentinel-1 November 2023 flood mask.

    .venv/bin/python pipeline/05_backtest.py nyando

Reads only local files (raw/<area>/s1/ from 04_s1_export.py; the M-03/M-04 rasters in processed/<area>/model/;
CHIRPS daily). Writes processed/<area>/model/backtest/{backtest.json, observed.tif, backtest.png}.

OBSERVED mask — UN-SPIDER Recommended Practice "Flood mapping and damage assessment using Sentinel-1 SAR data in
Google Earth Engine" (step-by-step page, read 2026-11-06):
https://www.un-spider.org/advisory-support/recommended-practices/recommended-practice-google-earth-engine-flood-mapping/step-by-step
  smoothing "50 m circles" (here: mean over a 3x3 window of 30 m pixels), after/before ratio of the dB mosaics,
  "threshold of 1.25", JRC water "for more than 10 months per year" masked (here: the model's own water mask, JRC
  occurrence >= 80 % or WorldCover 80, so model and observation exclude the same cells), "areas with over 5 % slope"
  removed, flood pixels "connected to eight or fewer neighbors" removed. Polarisation VH (the practice's default);
  VV reported alongside.
  Limits: C-band misses water under vegetation and in built-up areas; two event acquisitions (one orbit) only.

MODEL — the same h = k V_up^alpha / HAND mask as 03_runoff_flood.py, with a uniform P per acquisition date: the
AOI-mean CHIRPS total over the WINDOW_DAYS days ending on that date. The event composite is the minimum over both
dates, so the model mask is the union of the two dates' masks. k is chosen to maximise F1 over a log grid.
Evaluated over the AOI (bbox) inside the S1 footprint, water cells excluded. Spatial hold-out: 2-fold on a ~5 km
checkerboard (calibrate k on one colour, score on the other, and the reverse). Secondary score: the same without the
model's channel cells (streams narrower than S1 can resolve).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import from_bounds
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.lib import config, runoff, terrain  # noqa: E402
from pipeline.lib.paths import model_dir, provenance, raw_dir  # noqa: E402
from pipeline.lib.rio import grid_of, read, to_utm, write  # noqa: E402

RATIO_THR = 1.25          # UN-SPIDER
SLOPE_MAX_PCT = 5.0       # UN-SPIDER "over 5 % slope"
MIN_NEIGHBOURS = 8        # UN-SPIDER: drop patches "connected to eight or fewer neighbors" -> keep >= 10 px patches
WINDOW_DAYS = 10
TILE_PX = 167            # ~5 km tiles for the checkerboard hold-out
K_GRID = np.round(np.geomspace(0.0005, 0.05, 41), 6)


def _rf():
    spec = importlib.util.spec_from_file_location("rf", Path(__file__).resolve().parent / "03_runoff_flood.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def observed(before_db, event_db, water, slope_deg):
    """UN-SPIDER change detection on one polarisation (dB mosaics). Returns a bool mask."""
    k = np.ones((3, 3)) / 9.0
    b = ndimage.convolve(before_db, k, mode="nearest")
    a = ndimage.convolve(event_db, k, mode="nearest")
    with np.errstate(invalid="ignore", divide="ignore"):
        flood = (a / b) > RATIO_THR            # both negative dB: ratio > 1.25 = event darker by > 25 % of |dB|
    flood &= ~water & (np.tan(np.radians(slope_deg)) * 100 <= SLOPE_MAX_PCT) & np.isfinite(a) & np.isfinite(b)
    lab, n = ndimage.label(flood, structure=np.ones((3, 3), bool))
    size = np.bincount(lab.ravel())
    size[0] = 0
    return size[lab] > MIN_NEIGHBOURS + 1      # a pixel with <= 8 connected neighbours is in a patch of <= 9


def scores(model, obs, dom) -> dict:
    m, o = model & dom, obs & dom
    tp, fp, fn = int((m & o).sum()), int((m & ~o).sum()), int((~m & o).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(p, 4), "recall": round(r, 4),
            "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0, "iou": round(tp / (tp + fp + fn), 4) if tp + fp + fn else 0.0,
            "model_km2": round((tp + fp) * 900 / 1e6, 2), "observed_km2": round((tp + fn) * 900 / 1e6, 2)}


def aoi_rain(area: str, bbox, end: str, days: int) -> float:
    d0 = date.fromisoformat(end)
    tot = 0.0
    for i in range(days):
        f = raw_dir(area) / "chirps" / "daily" / f"{(d0 - timedelta(days=i)).isoformat()}.tif"
        with rasterio.open(f) as ds:
            a = ds.read(1).astype(float)
            a[a < 0] = np.nan
            r, c = np.mgrid[0:ds.height, 0:ds.width]
            xs, ys = rasterio.transform.xy(ds.transform, r.ravel(), c.ravel())
            xs, ys = np.array(xs).reshape(a.shape), np.array(ys).reshape(a.shape)
            inside = (xs >= bbox[0]) & (xs <= bbox[2]) & (ys >= bbox[1]) & (ys <= bbox[3])
            tot += float(np.nanmean(a[inside]))
    return tot


def main(area: str):
    prov = provenance()
    cfg = config.load(area)
    m, raw = model_dir(area), raw_dir(area)
    out = m / "backtest"
    out.mkdir(exist_ok=True)
    s1 = json.loads((raw / "s1" / "s1.json").read_text())
    grid = grid_of(m / "hand.tif")
    hand = read(m / "hand.tif")
    hidx = read(m / "hand_index.tif").astype("int64")
    slope = read(m / "slope.tif")
    fd = read(m / "flowdir.tif").astype("int64")
    fd[fd == terrain.FDIR_NODATA] = 0
    channels = read(m / "channels.tif") == 1
    perm = read(m / "perm_water.tif") == 1
    lc, _ = to_utm(raw / "worldcover_2021.tif", cfg["utm_epsg"], Resampling.mode, like=grid)
    water = runoff.water_mask(perm, lc)
    cn = read(m / "cn.tif")
    cell_km2 = abs(grid["transform"].a * grid["transform"].e) / 1e6
    aoi = _rf().aoi_mask(cfg, grid)

    # S1 composites sit on the model grid (same crs + transform phase): place them by window
    with rasterio.open(raw / "s1" / "s1_before.tif") as b, rasterio.open(raw / "s1" / "s1_event.tif") as e:
        w = from_bounds(*e.bounds, transform=grid["transform"]).round_offsets().round_lengths()
        assert b.bounds == e.bounds and b.transform.a == 30
        r0, c0, hh, ww = w.row_off, w.col_off, w.height, w.width
        bef = np.full((2,) + hand.shape, np.nan)
        evt = np.full((2,) + hand.shape, np.nan)
        bef[:, r0:r0 + hh, c0:c0 + ww] = b.read().astype(float)
        evt[:, r0:r0 + hh, c0:c0 + ww] = e.read().astype(float)
    bef[~np.isfinite(bef)] = np.nan
    evt[~np.isfinite(evt)] = np.nan
    obs = {pol: observed(bef[i], evt[i], water, slope) for i, pol in enumerate(("VV", "VH"))}
    dom = aoi & np.isfinite(evt[1]) & np.isfinite(bef[1]) & ~water
    write(out / "observed.tif", np.where(obs["VH"], 1, 0).astype("uint8"), grid, "uint8", 255,
          tags={"method": "UN-SPIDER S1 change detection, VH, ratio>1.25", "git_commit": prov["git_commit"]})

    dates = sorted({a["date"] for a in s1["products"]["event"]["acquisitions"]})
    p = {d: round(aoi_rain(area, cfg["bbox"], d, WINDOW_DAYS), 1) for d in dates}
    print(json.dumps({"event_dates": dates, f"P_{WINDOW_DAYS}d_mm": p}), flush=True)
    # V_up does not depend on k: h = k * V^alpha, so compute V once per date and scale
    alpha = _rf().ALPHA
    vpow = {}
    for d in dates:
        q = runoff.scs_runoff(p[d], cn)
        v = terrain.upstream_sum(fd, grid["transform"], grid["crs"], np.nan_to_num(q) * cell_km2)
        hv = np.full(hand.shape, np.nan)
        ok = hidx >= 0
        hv[ok] = (v ** alpha).ravel()[hidx[ok]]
        vpow[d] = hv

    def model_mask(k):
        mk = np.zeros(hand.shape, bool)
        for d in dates:
            mk |= np.isfinite(runoff.flood_depth(hand, k * vpow[d], slope, channels | water, water))
        return mk

    # Spatial 2-fold hold-out on a checkerboard of TILE_PX tiles (a west/east split was degenerate: 0.06 km2 of the
    # observed flood lies east of the AOI centre — it is all on the Kano plains)
    rr, cc = np.indices(hand.shape)
    black = ((rr // TILE_PX + cc // TILE_PX) % 2) == 0
    narrow = dom & ~channels       # secondary: channel cells themselves (streams below S1's resolution) not scored
    curve = []
    for k in list(K_GRID) + [_rf().K_PROVISIONAL]:
        mk = model_mask(float(k))
        row = {"k": float(k), "all": scores(mk, obs["VH"], dom), "all_vv": scores(mk, obs["VV"], dom),
               "no_channel_cells": scores(mk, obs["VH"], narrow),
               "black": scores(mk, obs["VH"], dom & black), "white": scores(mk, obs["VH"], dom & ~black)}
        curve.append(row)
        print(json.dumps({"k": row["k"], **{s: row[s]["f1"] for s in ("all", "all_vv", "no_channel_cells", "black",
                                                                      "white")},
                          "model_km2": row["all"]["model_km2"]}), flush=True)
    grid_rows = curve[:-1]
    best = max(grid_rows, key=lambda r: r["all"]["f1"])
    bb = max(grid_rows, key=lambda r: r["black"]["f1"])
    bw = max(grid_rows, key=lambda r: r["white"]["f1"])
    holdout = {"tile_km": TILE_PX * 30 / 1000,
               "calibrate_black_k": bb["k"], "score_white": bb["white"], "white_own_best_f1": bw["white"]["f1"],
               "calibrate_white_k": bw["k"], "score_black": bw["black"], "black_own_best_f1": bb["black"]["f1"]}
    f1s = [r["all"]["f1"] for r in grid_rows]
    rep = {"provenance": prov, "area": area, "s1": {k: s1[k] for k in ("product", "licence", "route", "eecu_seconds",
                                                                       "eecu_note")},
           "before": s1["products"]["before"]["acquisitions"], "event": s1["products"]["event"]["acquisitions"],
           "observed_method": {"ratio_threshold": RATIO_THR, "slope_max_pct": SLOPE_MAX_PCT,
                               "min_neighbours_dropped": MIN_NEIGHBOURS, "smoothing": "3x3 mean (30 m px)",
                               "polarisation": "VH (VV alongside)"},
           "observed_km2_in_domain": {pol: round(float((o & dom).sum()) * 900 / 1e6, 2) for pol, o in obs.items()},
           "domain_km2": round(float(dom.sum()) * 900 / 1e6, 2),
           "rain": {"window_days": WINDOW_DAYS, "p_mm": p, "source": "CHIRPS v2.0 daily, AOI mean"},
           "alpha": alpha, "k_provisional": _rf().K_PROVISIONAL, "provisional": curve[-1],
           "best": best, "f1_range_over_k_grid": [min(f1s), max(f1s)], "holdout": holdout, "curve": grid_rows}
    (out / "backtest.json").write_text(json.dumps(rep, indent=1))
    figure(out / "backtest.png", obs["VH"], model_mask(best["k"]), dom, aoi, best)
    print(json.dumps({"best_k": best["k"], "best": best["all"], "provisional_k": curve[-1]["all"],
                      "holdout": holdout}, indent=1))


def figure(path, obs, mod, dom, aoi, best):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rows, cols = np.where(aoi)
    sl = (slice(rows.min(), rows.max() + 1), slice(cols.min(), cols.max() + 1))
    o, mm, d = obs[sl] & dom[sl], mod[sl] & dom[sl], dom[sl]
    cmp_ = np.full(o.shape, 0)
    cmp_[mm & o], cmp_[mm & ~o], cmp_[~mm & o] = 1, 2, 3
    fig, ax = plt.subplots(1, 3, figsize=(16, 5.6))
    from matplotlib.colors import ListedColormap
    ax[0].imshow(np.where(d, o, np.nan), cmap=ListedColormap(["#eeeeee", "#1f4e9c"]), interpolation="nearest")
    ax[0].set_title("Observed: Sentinel-1 flood, Nov 2023 (UN-SPIDER method)")
    ax[1].imshow(np.where(d, mm, np.nan), cmap=ListedColormap(["#eeeeee", "#c0392b"]), interpolation="nearest")
    ax[1].set_title(f"Model: HAND + SCS-CN, k = {best['k']}")
    ax[2].imshow(np.where(d, cmp_, np.nan), cmap=ListedColormap(["#eeeeee", "#2e7d32", "#e67e22", "#1f4e9c"]),
                 interpolation="nearest", vmin=0, vmax=3)
    s = best["all"]
    ax[2].set_title(f"Agree (green) / model only (orange) / S1 only (blue)\nF1 {s['f1']:.2f}  IoU {s['iou']:.2f}  "
                    f"precision {s['precision']:.2f}  recall {s['recall']:.2f}")
    for a in ax:
        a.set_xticks([]), a.set_yticks([])
    fig.suptitle("Nyando backtest, Nov 2023 — screening-level model vs satellite (grey = evaluated, water excluded)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)


if __name__ == "__main__":
    main(sys.argv[1])
