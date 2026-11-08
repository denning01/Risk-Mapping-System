"""M-20 flood arrival time: how long water takes to reach each cell when it rains on the high ground upstream.

    .venv/bin/python pipeline/10_arrival.py nyando [--no-write]

Reads  $RMS_DATA/processed/<area>/model/{flowdir,dem_cond,acc,slope,cn,perm_water}.tif (M-03 / M-04 grid, UTM 30 m),
       $RMS_DATA/raw/<area>/worldcover_2021.tif (reprojected onto that grid, mode),
       $RMS_DATA/processed/<area>/model/osm_waterways.json (M-03 cache; names the sub-catchments of the second method).
Writes $RMS_DATA/processed/<area>/model/arrival_h.tif (float32 hours, NaN = no value), arrival.json, arrival.png.

METHOD (velocity method, NRCS NEH 630 ch. 15, May 2010, eq. 15-7: Tc = sum of segment travel times):
  every cell's D8 link (30 m, or 30*sqrt(2) diagonal) gets a travel time t = length / v, with
  - hillslope / shallow concentrated flow (upstream area < CHANNEL_START_KM2): v = k * sqrt(s), k from NEH 630 ch. 15
    table 15-3 by WorldCover class (paved = "pavement and small upland gullies", unpaved by cover), s = the link's slope
    on the conditioned DEM, floored at SLOPE_MIN;
  - channel (>= CHANNEL_START_KM2) and permanent water: Manning v = R^(2/3) s^(1/2) / n (NEH 630 eq. 15-10, SI), R by
    channel size (stated below), one n;
  - every velocity capped at V_MAX.
  arrival_h(cell) = the LONGEST travel time from any upstream cell to this cell along D8 = its time of concentration
  (the storm is uniform over the whole upstream catchment and starts at t = 0; the most remote water arrives last).
  Ridge cells (no upstream cell) are 0.
SECOND METHOD: for 3+ named sub-catchments, Kirpich (TxDOT Hydraulic Design Manual eq. 4-15, SI: t = 0.0195 L^0.770
  S^-0.385 min) and the SCS watershed lag method (NEH 630 eq. 15-4b: Tc = l^0.8 (S+1)^0.7 / (1140 Y^0.5) h, l ft,
  S = 1000/CN - 10 in, Y %), compared with arrival_h at the outlet.
SCREENING ESTIMATE: not calibrated against any observed hydrograph; no rainfall timing (no storm duration or intensity,
  no infiltration delay); no flood-wave routing or storage. It says how far upstream the water comes from, in hours.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from rasterio.warp import Resampling

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.lib import config  # noqa: E402
from pipeline.lib.paths import REPO_ROOT, model_dir, provenance, raw_dir  # noqa: E402
from pipeline.lib.rio import RES, grid_of, read, to_utm, write  # noqa: E402

FT = 0.3048
# NEH 630 ch. 15 table 15-3: shallow concentrated flow, V = k * s^0.5, V ft/s, s ft/ft (read from the NRCS PDF,
# directives.nrcs.usda.gov/sites/default/files2/1712930617/14081.pdf, p. 15-8)
K_FT_S = {
    "pavement": 20.328,         # pavement and small upland gullies
    "grassed_waterway": 16.135,
    "nearly_bare": 9.965,       # nearly bare and untilled (overland flow)
    "cultivated": 8.762,        # cultivated straight row crops
    "short_grass": 6.962,       # short-grass pasture
    "woodland": 5.032,          # minimum tillage cultivation, contour or strip-cropped, and woodlands
    "forest_litter": 2.516,     # forest with heavy ground litter and hay meadows
}
# CHOICE: ESA WorldCover 2021 class -> table 15-3 flow type (80 permanent water is routed as channel, not here)
WC_FLOW = {10: "forest_litter", 20: "woodland", 30: "short_grass", 40: "cultivated", 50: "pavement",
           60: "nearly_bare", 70: "nearly_bare", 90: "forest_litter", 95: "forest_litter", 100: "short_grass"}
WC_DEFAULT = "short_grass"        # CHOICE: a cell with no WorldCover class
SLOPE_MIN = 0.001                 # CHOICE: m/m floor on a link's slope (flats would give v = 0)
SLOPE_REACH_LINKS = 10            # CHOICE: a link's slope = drop over the next 10 D8 links (~300 m) / their length, so the
                                  # flats that depression filling leaves in dem_cond take the drop of the reach around them
CHANNEL_START_KM2 = 0.25          # CHOICE: Manning channel flow from this upstream area (shallow flow below it). NEH 630
                                  # 15-7: channels begin where "bluelines" appear; M-03's sweep (terrain.log): at 0.25 km2,
                                  # 0.796 of OSM river|stream cells are within 60 m of a DEM channel
MAIN_CHANNEL_KM2 = 10.0           # = the M-03 channel threshold (terrain.json channel_km2)
R_SMALL_M, R_MAIN_M = 0.3, 1.0    # CHOICE: hydraulic radius, small channels (0.25-10 km2) / main channels and lakes
N_CHANNEL = 0.040                 # CHOICE: one Manning n for natural channels
V_MAX = 3.0                       # CHOICE: m/s cap on any velocity
SUB_KM2 = (5.0, 49.0)             # second method: sub-catchment sizes; the lag method's upper limit is ~19 mi2 = 49 km2
                                  # (NEH 630 15-6, Folmar and Miller)
CN_RANGE = (50, 95)               # NEH 630 15-6: no CN below 50 or above 95 in eq. 15-4

# pysheds D8 codes (pipeline/lib/terrain.py _STEP): code -> (drow, dcol)
STEP = {64: (-1, 0), 128: (-1, 1), 1: (0, 1), 2: (1, 1), 4: (1, 0), 8: (1, -1), 16: (0, -1), 32: (-1, -1)}


def receivers(fdir: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Flat index of each cell's D8 downstream cell; -1 where none (pit, flat, nodata, off the grid, invalid target)."""
    h, w = fdir.shape
    rcv = np.full(h * w, -1, np.int64)
    rows, cols = np.indices((h, w))
    for code, (dr, dc) in STEP.items():
        m = (fdir == code) & valid
        r2, c2 = rows[m] + dr, cols[m] + dc
        ok = (r2 >= 0) & (r2 < h) & (c2 >= 0) & (c2 < w)
        src = np.flatnonzero(m)[ok]
        dst = r2[ok] * w + c2[ok]
        keep = valid.ravel()[dst]
        rcv[src[keep]] = dst[keep]
    return rcv


def reach_slope(rcv: np.ndarray, z: np.ndarray, length: np.ndarray, links: int) -> np.ndarray:
    """Slope of each cell's link, averaged over up to `links` D8 links downstream: (z - z at the end) / path length.
    Stops early at a terminal. 0 for a cell with no receiver."""
    cur = np.arange(rcv.size)
    dist = np.zeros(rcv.size)
    for _ in range(links):
        nxt = rcv[cur]
        go = nxt >= 0
        dist[go] += length[cur[go]]
        cur = np.where(go, nxt, cur)
    out = np.zeros(rcv.size)
    ok = dist > 0
    out[ok] = (z[ok] - z[cur[ok]]) / dist[ok]
    return out


def link_length(fdir: np.ndarray, res: float = RES) -> np.ndarray:
    diag = np.isin(fdir, (128, 2, 8, 32))
    return np.where(diag, res * np.sqrt(2), res)


def shallow_k_ms(wc: np.ndarray) -> np.ndarray:
    """m/s per sqrt(m/m), from table 15-3 by WorldCover class."""
    k = np.full(wc.shape, K_FT_S[WC_DEFAULT] * FT)
    for cls, flow in WC_FLOW.items():
        k[wc == cls] = K_FT_S[flow] * FT
    return k


def velocity(slope: np.ndarray, land_slope: np.ndarray, acc_km2: np.ndarray, k_ms: np.ndarray, perm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(v m/s, regime 0 = shallow, 1 = small channel, 2 = main channel or permanent water). Shallow flow uses the LAND
    slope (slope.tif, steepest descent on the unfilled DEM); channels the reach-averaged slope along the D8 path."""
    regime = np.where(perm | (acc_km2 >= MAIN_CHANNEL_KM2), 2, np.where(acc_km2 >= CHANNEL_START_KM2, 1, 0))
    s = np.maximum(np.where(regime == 0, np.nan_to_num(land_slope, nan=0.0), slope), SLOPE_MIN)
    r = np.where(regime == 2, R_MAIN_M, R_SMALL_M)
    v = np.where(regime == 0, k_ms * np.sqrt(s), r ** (2 / 3) * np.sqrt(s) / N_CHANNEL)
    return np.minimum(v, V_MAX), regime


def upstream_pass(rcv: np.ndarray, t: np.ndarray, length: np.ndarray, z: np.ndarray, valid: np.ndarray,
                  border: np.ndarray):
    """Topological pass from the ridges down (Kahn, in vectorised batches).
    -> T (s, longest travel time from any upstream cell), L (m, longest flow length), Zhead (elevation at the head of
       that longest-length path), truncated (some upstream cell lies on the grid border, so the catchment may be cut),
       batches (the topological batches of flat indices, upstream first)."""
    n = rcv.size
    vflat = valid.ravel()
    has = rcv >= 0
    indeg = np.bincount(rcv[has], minlength=n)
    T = np.zeros(n)
    L = np.zeros(n)
    Zh = z.ravel().astype("float64").copy()
    trunc = (border.ravel() & vflat).astype(np.uint8)
    frontier = np.flatnonzero(vflat & (indeg == 0))
    order = []
    while frontier.size:
        order.append(frontier)
        f = frontier[rcv[frontier] >= 0]
        if not f.size:
            break                                       # only terminals left in this batch: nothing downstream waits
        r = rcv[f]
        np.maximum.at(T, r, T[f] + t[f])
        np.maximum.at(trunc, r, trunc[f])
        cand = L[f] + length[f]
        o = np.lexsort((cand, r))                      # by receiver, then candidate length: the last of a group wins
        r_o, c_o, h_o = r[o], cand[o], Zh[f][o]
        last = np.r_[r_o[1:] != r_o[:-1], True]
        u, c, hz = r_o[last], c_o[last], h_o[last]
        better = c > L[u]
        L[u[better]] = c[better]
        Zh[u[better]] = hz[better]
        np.subtract.at(indeg, r, 1)
        ready = np.unique(r)
        frontier = ready[indeg[ready] == 0]
    return T, L, Zh, trunc.astype(bool), order


def kirpich_h(length_m: float, slope: float) -> float:
    """TxDOT Hydraulic Design Manual eq. 4-15, SI: t (min) = 0.0195 L^0.770 S^-0.385."""
    return 0.0195 * length_m ** 0.770 * slope ** -0.385 / 60


def scs_lag_tc_h(length_m: float, cn: float, y_pct: float) -> float:
    """NEH 630 eq. 15-4b: Tc (h) = l^0.8 (S + 1)^0.7 / (1140 Y^0.5), l ft, S = 1000/CN - 10 (in), Y average land slope %."""
    s = 1000 / cn - 10
    return (length_m / FT) ** 0.8 * (s + 1) ** 0.7 / (1140 * y_pct ** 0.5)


def label_catchments(rcv: np.ndarray, batches: list[np.ndarray], outlets: list[int]) -> np.ndarray:
    """Each cell -> index of the outlet it drains to (-1 none). The topological batches in reverse: a cell's receiver
    is always in a later forward batch, so it is labelled first. An outlet keeps its own label (nested outlets split)."""
    lab = np.full(rcv.size, -1, np.int64)
    is_out = np.zeros(rcv.size, bool)
    for i, o in enumerate(outlets):
        lab[o] = i
        is_out[o] = True
    for f in reversed(batches):
        f = f[(rcv[f] >= 0) & ~is_out[f]]
        lab[f] = lab[rcv[f]]
    return lab


def compute(fdir, z, acc_km2, wc, perm, valid, land_slope, res=RES, **over):
    """Link times and the upstream pass. `over` replaces module CHOICES for a sensitivity run (keys: SLOPE_MIN,
    SLOPE_REACH_LINKS, N_CHANNEL, R_MAIN_M, R_SMALL_M, CHANNEL_START_KM2, V_MAX)."""
    g = globals()
    saved = {k: g[k] for k in over}
    g.update(over)
    try:
        h, w = fdir.shape
        rcv = receivers(fdir, valid)
        length = link_length(fdir, res).ravel()
        slope = reach_slope(rcv, z.ravel().astype("float64"), length, SLOPE_REACH_LINKS)
        has = rcv >= 0
        v, regime = velocity(slope, land_slope.ravel(), acc_km2.ravel(), shallow_k_ms(wc.ravel()), perm.ravel())
        t = np.where(has, length / v, 0.0)
        border = np.zeros((h, w), bool)
        border[[0, -1], :] = border[:, [0, -1]] = True
        T, L, Zh, trunc, batches = upstream_pass(rcv, t, length, z, valid, border)
    finally:
        g.update(saved)
    return {"rcv": rcv, "t": t, "regime": regime, "T": T, "L": L, "Zh": Zh, "trunc": trunc, "batches": batches,
            "slope": slope}


def pick_outlets(area: str, grid, acc_km2, aoi, trunc, perm, rcv, osm_path: Path, n_max: int = 5) -> list[dict]:
    """Second-method outlets: per NAMED OSM river|stream, the cell within 60 m of it, inside the AOI, with the largest
    upstream area in SUB_KM2, whose catchment does not touch the grid border; nested ones dropped (keep the larger)."""
    from pyproj import Transformer
    from rasterio.features import rasterize
    from scipy import ndimage
    from shapely import LineString, ops
    to = Transformer.from_crs(4326, grid["crs"], always_xy=True).transform
    ways = json.loads(osm_path.read_text())["elements"]
    by_name: dict[str, list] = {}
    for wy in ways:
        nm = (wy.get("tags") or {}).get("name")
        if nm and len(wy.get("geometry", [])) > 1:
            by_name.setdefault(nm, []).append(ops.transform(to, LineString([(p["lon"], p["lat"]) for p in wy["geometry"]])))
    ok = aoi & ~trunc.reshape(aoi.shape) & ~perm & (acc_km2 >= SUB_KM2[0]) & (acc_km2 <= SUB_KM2[1])
    cands = []
    for nm, lines in sorted(by_name.items()):
        m = rasterize([(ln, 1) for ln in lines], out_shape=aoi.shape, transform=grid["transform"], all_touched=True).astype(bool)
        m = ndimage.binary_dilation(m, iterations=2) & ok
        if not m.any():
            continue
        i = int(np.flatnonzero(m.ravel())[np.argmax(acc_km2.ravel()[m.ravel()])])
        cands.append({"name": nm, "cell": i, "acc_km2": float(acc_km2.ravel()[i])})
    cands.sort(key=lambda c: -c["acc_km2"])
    chosen: list[dict] = []
    for c in cands:
        # nested? walk downstream from c and from each chosen outlet
        def downstream(i):
            seen = set()
            while i >= 0 and i not in seen:
                seen.add(i)
                i = int(rcv[i])
            return seen
        dc = downstream(c["cell"])
        if any(o["cell"] in dc or c["cell"] in downstream(o["cell"]) for o in chosen):
            continue
        chosen.append(c)
        if len(chosen) == n_max:
            break
    return chosen


def main(area: str, write_out: bool) -> int:
    prov = provenance()
    if write_out and (prov.get("dirty") or not prov.get("git_commit")):
        sys.exit(f"REFUSED: a dirty or untraceable run ({prov}) does not write arrival_h.tif; commit first or use --no-write")
    cfg = config.load(area)
    m = model_dir(area)
    grid = grid_of(m / "flowdir.tif")
    fdir = read(m / "flowdir.tif")
    z = read(m / "dem_cond.tif")
    acc = read(m / "acc.tif")
    slope_deg = read(m / "slope.tif")
    cn = read(m / "cn.tif")
    perm = read(m / "perm_water.tif") == 1
    wc, _ = to_utm(raw_dir(area) / "worldcover_2021.tif", cfg["utm_epsg"], Resampling.mode, like=grid)
    wc = np.nan_to_num(wc, nan=0).astype(np.int16)
    terr = json.loads((m / "terrain.json").read_text())
    assert terr["channel_km2"] == MAIN_CHANNEL_KM2, f"M-03 channel threshold {terr['channel_km2']} != {MAIN_CHANNEL_KM2}"
    cell_km2 = (RES / 1000) ** 2
    acc_km2 = acc * cell_km2
    valid = (fdir != -32768) & np.isfinite(z)
    from pyproj import Transformer
    from rasterio.features import rasterize
    from shapely import box, ops  # noqa: F401
    to = Transformer.from_crs(4326, grid["crs"], always_xy=True).transform
    aoi = rasterize([(ops.transform(to, box(*cfg["bbox"]).segmentize(0.001)), 1)], out_shape=fdir.shape,
                    transform=grid["transform"]).astype(bool)

    land = np.tan(np.radians(slope_deg))                 # m/m
    R = compute(fdir, z, acc_km2, wc, perm, valid, land)
    T, rcv, t = R["T"], R["rcv"], R["t"]
    arrival = (T / 3600).reshape(fdir.shape).astype("float32")
    arrival[~valid | perm] = np.nan
    reached = np.zeros(rcv.size, bool)
    reached[np.concatenate(R["batches"])] = True
    has = rcv >= 0
    viol = int((T[rcv[has]] + 1e-6 < T[has] + t[has]).sum())
    a_aoi = arrival[aoi & np.isfinite(arrival)]
    reg = R["regime"].reshape(fdir.shape)
    rep = {
        "provenance": prov, "area": area, "utm_epsg": cfg["utm_epsg"], "res_m": RES, "shape": list(fdir.shape),
        "method": "velocity method (NEH 630 ch.15 eq. 15-7) along D8; arrival_h = longest upstream travel time (Tc to the cell)",
        "choices": {"SLOPE_MIN": SLOPE_MIN, "SLOPE_REACH_LINKS": SLOPE_REACH_LINKS, "CHANNEL_START_KM2": CHANNEL_START_KM2, "MAIN_CHANNEL_KM2": MAIN_CHANNEL_KM2,
                    "R_SMALL_M": R_SMALL_M, "R_MAIN_M": R_MAIN_M, "N_CHANNEL": N_CHANNEL, "V_MAX": V_MAX,
                    "WC_FLOW": {str(k): v for k, v in WC_FLOW.items()}, "K_FT_S_table_15_3": K_FT_S},
        "sanity": {
            "valid_cells": int(valid.sum()), "unreached_valid_cells": int((valid.ravel() & ~reached).sum()),
            "negative": int((arrival[np.isfinite(arrival)] < 0).sum()), "inf": int(np.isinf(arrival).sum()),
            "downstream_not_later": viol,
            "ridge_cells_zero": bool(np.all(T[valid.ravel() & (np.bincount(rcv[has], minlength=rcv.size) == 0)] == 0)),
        },
        "aoi": {"cells": int(aoi.sum()), "arrival_h": {q: round(float(np.percentile(a_aoi, p)), 2) for q, p in
                                                         (("p10", 10), ("p50", 50), ("p90", 90), ("p99", 99), ("max", 100))},
                "truncated_share": round(float(R["trunc"].reshape(fdir.shape)[aoi].mean()), 4),
                "regime_share": {nm: round(float((reg[aoi] == k).mean()), 4) for k, nm in
                                 ((0, "shallow"), (1, "small_channel"), (2, "main_channel_or_water"))}},
    }
    # where the water matters: arrival over each scenario's flooded cells in the AOI (M-04 depth rasters, NaN = dry)
    wet = {}
    for key in ("50_normal", "150_normal", "250_elnino"):
        dp = m / "scenarios" / f"{key}_depth.tif"
        if dp.exists():
            d = read(dp)
            a = arrival[aoi & np.isfinite(d) & (d > 0) & np.isfinite(arrival)]
            wet[key] = {"cells": int(a.size), **{q: round(float(np.percentile(a, p)), 2) for q, p in
                                                  (("p10", 10), ("p50", 50), ("p90", 90), ("max", 100))}}
    rep["aoi"]["arrival_h_on_flooded_cells"] = wet
    am = np.where(aoi, np.nan_to_num(arrival, nan=-1), -1)
    rmax, cmax = np.unravel_index(int(np.argmax(am)), am.shape)
    xm, ym = grid["transform"] * (cmax + 0.5, rmax + 0.5)
    rep["aoi"]["max_at_lonlat"] = [round(v, 5) for v in Transformer.from_crs(grid["crs"], 4326, always_xy=True).transform(xm, ym)]
    rep["aoi"]["max_at_upstream_km2"] = round(float(acc_km2[rmax, cmax]), 1)
    # second method
    outs = pick_outlets(area, grid, acc_km2, aoi, R["trunc"], perm, rcv, m / "osm_waterways.json")
    lab = label_catchments(rcv, R["batches"], [o["cell"] for o in outs])
    tan_pct = np.tan(np.radians(slope_deg)).ravel() * 100
    zf, cnf = z.ravel(), cn.ravel()
    rows = []
    for i, o in enumerate(outs):
        c = o["cell"]
        mk = lab == i
        L_m = float(R["L"][c])
        S = float((R["Zh"][c] - zf[c]) / L_m)
        Y = float(np.nanmean(tan_pct[mk]))
        cn_raw = float(np.nanmean(cnf[mk]))
        cn_used = float(np.clip(cn_raw, *CN_RANGE))
        vel = float(T[c] / 3600)
        kir = kirpich_h(L_m, S)
        scs = scs_lag_tc_h(L_m, cn_used, Y)
        rr, cc = divmod(c, fdir.shape[1])
        x, y = grid["transform"] * (cc + 0.5, rr + 0.5)
        lon, lat = Transformer.from_crs(grid["crs"], 4326, always_xy=True).transform(x, y)
        rows.append({"name": o["name"], "outlet_lonlat": [round(lon, 5), round(lat, 5)], "area_km2": round(float(mk.sum()) * cell_km2, 2),
                     "acc_km2": round(o["acc_km2"], 2), "longest_path_km": round(L_m / 1000, 2), "path_slope": round(S, 5),
                     "land_slope_pct": round(Y, 2), "cn_mean": round(cn_raw, 1), "cn_used": round(cn_used, 1),
                     "tc_velocity_h": round(vel, 2), "tc_kirpich_h": round(kir, 2), "tc_scs_lag_h": round(scs, 2),
                     "ratio_velocity_to_kirpich": round(vel / kir, 2), "ratio_velocity_to_scs_lag": round(vel / scs, 2)})
    rep["second_method"] = {"kirpich": "TxDOT Hydraulic Design Manual eq. 4-15 (SI K = 0.0195), L = longest flow path, S = its drop / length",
                            "scs_lag": "NEH 630 eq. 15-4b, l = longest flow path, Y = mean land slope (slope.tif), CN = mean cn.tif (AMC II), clamped 50-95",
                            "sub_km2": SUB_KM2, "rows": rows}
    # sensitivity: AOI median and each outlet's Tc under one changed CHOICE at a time
    sens = []
    for k, vals in (("SLOPE_REACH_LINKS", (1, 30)), ("SLOPE_MIN", (0.0005, 0.005)), ("N_CHANNEL", (0.03, 0.06)), ("R_MAIN_M", (0.5, 2.0)),
                    ("CHANNEL_START_KM2", (1.0, 0.1)), ("V_MAX", (1.5, 6.0))):
        for val in vals:
            Rs = compute(fdir, z, acc_km2, wc, perm, valid, land, **{k: val})
            a = (Rs["T"] / 3600).reshape(fdir.shape)
            sens.append({"choice": k, "value": val, "aoi_p50_h": round(float(np.median(a[aoi & valid & ~perm])), 2),
                         "aoi_p90_h": round(float(np.percentile(a[aoi & valid & ~perm], 90)), 2),
                         "outlet_tc_h": [round(float(Rs["T"][o["cell"]] / 3600), 2) for o in outs]})
            print("sensitivity", sens[-1], flush=True)
    rep["sensitivity"] = sens
    print(json.dumps({k: rep[k] for k in ("sanity", "aoi")}, indent=1))
    print(json.dumps(rows, indent=1))
    if write_out:
        tags = {"calibrated": "false", "units": "hours", "producer": "pipeline/10_arrival.py", "git_commit": prov["git_commit"],
                "dirty": prov["dirty"], "meaning": "longest D8 travel time from any upstream cell (time of concentration); NaN = no data or permanent water",
                "screening": "not calibrated; no rainfall timing"}
        write(m / "arrival_h.tif", arrival, grid, tags=tags)
        (m / "arrival.json").write_text(json.dumps(rep, indent=2))
        png(m / "arrival.png", arrival, aoi, cfg["name"], outs, fdir.shape)
        handoff_md(area, cfg, grid, rep, m / "arrival_h.tif")
    return 0


def handoff_md(area: str, cfg: dict, grid: dict, rep: dict, tif: Path, fast_tif: Path | None = None) -> Path:
    """rms-audit/handoffs/arrival-<area>.md: what exposure (E-20) needs to read arrival_h.tif."""
    import hashlib
    sha = hashlib.sha256(tif.read_bytes()).hexdigest()
    fast = rep.get("fast")
    if fast and fast_tif is not None:
        fsha = hashlib.sha256(fast_tif.read_bytes()).hexdigest()
        fw = "\n".join(f"| {k} | {v['cells']:,} | {v['p10']} | {v['p50']} | {v['p90']} | {v['max']} |"
                        for k, v in fast["aoi_arrival_h_fast_on_flooded_cells"].items())
        fast_txt = f"""
## The RANGE and the headline (RULING M-20, product safety)

Overstating warning time is the dangerous error, and the velocity method above is 1.1 to 2.4 times SLOWER than
Kirpich / SCS lag on the named sub-catchments. Arrival is therefore a RANGE per cell:

- **`arrival_h_fast.tif`, the FAST bound = the app HEADLINE** ("water could arrive in as little as X h"):
  arrival_h / F, F = **{fast['divisor']}** = the largest velocity / second-method ratio over every sub-catchment of
  {', '.join(fast['areas'])} ({fast['from']['ratio'].replace('ratio_velocity_to_', 'vs ')}, {fast['from']['river']},
  {fast['from']['area']}). {fast_tif.stat().st_size:,} B, sha256 `{fsha}`. Same grid, units and NaN as arrival_h.tif.
- **`arrival_h.tif`, the velocity-method value** = the slow end of the range.

Fast bound on flooded cells (AOI):

| scenario | cells | p10 h | p50 h | p90 h | max h |
|---|---|---|---|---|---|
{fw}
"""
    else:
        fast_txt = ""
    c, a, s2 = rep["choices"], rep["aoi"], rep["sanity"]
    wet = "\n".join(f"| {k} | {v['cells']:,} | {v['p10']} | {v['p50']} | {v['p90']} | {v['max']} |"
                     for k, v in a["arrival_h_on_flooded_cells"].items())
    sub = "\n".join(f"| {r['name']} | {r['outlet_lonlat'][0]}, {r['outlet_lonlat'][1]} | {r['area_km2']} | {r['longest_path_km']} | "
                     f"{r['tc_velocity_h']} | {r['tc_kirpich_h']} | {r['tc_scs_lag_h']} | {r['ratio_velocity_to_kirpich']} | "
                     f"{r['ratio_velocity_to_scs_lag']} |" for r in rep["second_method"]["rows"])
    txt = f"""# Hand-off: flood arrival time, {cfg['name']} (model -> exposure, E-20)

Written by pipeline/10_arrival.py at commit {rep['provenance']['git_commit']} (dirty: {rep['provenance']['dirty']}).

**SCREENING ESTIMATE, NOT CALIBRATED.** No observed hydrograph was used. There is no rainfall timing (no storm duration,
intensity or infiltration delay) and no flood-wave routing or storage. It answers one question: if it rains everywhere
upstream at t = 0, how many hours until water from the most remote upstream point reaches this cell?

- **File:** `$RMS_DATA/processed/{area}/model/arrival_h.tif` ({tif.stat().st_size:,} B, sha256 `{sha}`)
- **Grid:** the M-03 grid, {grid['crs']}, 30 m, {rep['shape'][0]}×{rep['shape'][1]}; the same grid as hand.tif and the depth rasters.
- **Values:** float32 **hours**. NaN = no DEM, or permanent water (JRC >= 80 %). 0 = a ridge cell (nothing upstream).
- **Method:** NRCS NEH 630 ch. 15 (May 2010) velocity method, eq. 15-7, along the M-03 D8 flow directions.
  arrival_h = the LONGEST travel time from any upstream cell (the time of concentration to the cell).
  - Hillslope / shallow concentrated flow (upstream area < {c['CHANNEL_START_KM2']} km²): V = k·s^0.5, k from table 15-3 by
    WorldCover 2021 class, s = land slope (slope.tif).
  - Channels: Manning (eq. 15-10), n = {c['N_CHANNEL']}. R = {c['R_SMALL_M']} m from {c['CHANNEL_START_KM2']} km² and
    {c['R_MAIN_M']} m from {c['MAIN_CHANNEL_KM2']} km² and on permanent water. s = drop over {c['SLOPE_REACH_LINKS']} D8 links
    on dem_cond.
  - s floored at {c['SLOPE_MIN']}; every velocity capped at {c['V_MAX']} m/s.
  - These are CHOICES; arrival.json gives the sensitivity to each.
- **Sanity:** {s2['valid_cells']:,} valid cells, unreached {s2['unreached_valid_cells']}, negative {s2['negative']}, inf {s2['inf']},
  downstream earlier than upstream {s2['downstream_not_later']}, ridge cells 0: {s2['ridge_cells_zero']}.
  AOI cells whose catchment touches the grid edge: {a['truncated_share']:.2%}.
- **AOI arrival (h):** {a['arrival_h']}. Maximum at {a['max_at_lonlat']} (upstream area {a['max_at_upstream_km2']} km²).

Arrival on the flooded cells of three scenarios (AOI; depth > 0 in scenarios/<key>_depth.tif):

| scenario | cells | p10 h | p50 h | p90 h | max h |
|---|---|---|---|---|---|
{wet}

Second method on 5 sub-catchments of 5-49 km² (the lag method's range). Outlet = the cell within 60 m of a named OSM river
with the largest upstream area in that range. Where the named river itself drains more than 49 km², the outlet is a TRIBUTARY
beside it, so the name locates the sub-catchment and does not mean the river's own catchment:
- Kirpich: TxDOT Hydraulic Design Manual eq. 4-15, SI.
- SCS watershed lag method: NEH 630 eq. 15-4b, with mean cn.tif clamped to 50-95.

| OSM river named within 60 m of the outlet (the outlet can be a tributary beside it) | outlet lon, lat | km² | longest path km | velocity Tc h | Kirpich h | SCS lag Tc h | vel/Kirpich | vel/SCS |
|---|---|---|---|---|---|---|---|---|
{sub}

{fast_txt}
**Known limits:**
- No sheet-flow segment.
- One n and two radii for every channel.
- D8 on a 30 m DEM.
- Filled depressions take their reach's slope.
- The time is to the cell, not the time the depth there is reached.
"""
    out = REPO_ROOT.parent / "rms-audit" / "handoffs" / f"arrival-{area}.md"
    out.write_text(txt)
    return out


def png(path, arrival, aoi, name, outs, shape):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rows, cols = np.where(aoi)
    win = (slice(rows.min(), rows.max() + 1), slice(cols.min(), cols.max() + 1))
    fig, ax = plt.subplots(figsize=(10, 7))
    im = ax.imshow(arrival[win], cmap="viridis", vmin=0, vmax=float(np.nanpercentile(arrival[aoi], 99)), interpolation="nearest")
    for o in outs:
        r, c = divmod(o["cell"], shape[1])
        ax.plot(c - cols.min(), r - rows.min(), "r^", ms=7)
        ax.annotate(o["name"], (c - cols.min(), r - rows.min()), color="r", fontsize=7)
    fig.colorbar(im, ax=ax, shrink=0.8, label="hours")
    ax.set_title(f"{name}: flood arrival time from the upstream high ground (h), screening estimate, not calibrated", fontsize=9)
    ax.set_axis_off()
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def fast_divisor(reports: list[dict]) -> tuple[float, dict]:
    """RULING M-20 (operator, product safety): F = the LARGEST ratio velocity Tc / second-method Tc (Kirpich or SCS lag)
    over every sub-catchment of every area. arrival_h_fast = arrival_h / F. Never below 1 (never slower than arrival_h)."""
    best, at = 1.0, {}
    for r in reports:
        for row in r["second_method"]["rows"]:
            for k in ("ratio_velocity_to_kirpich", "ratio_velocity_to_scs_lag"):
                if row[k] > best:
                    best, at = row[k], {"area": r["area"], "river": row["name"], "ratio": k}
    return best, at


def write_fast(areas: list[str]) -> int:
    """After every area's main run: arrival_h_fast.tif per area (= arrival_h / F, F from ALL areas), the rule recorded in
    arrival.json, and the hand-off notes re-written with both files."""
    prov = provenance()
    if prov.get("dirty") or not prov.get("git_commit"):
        sys.exit(f"REFUSED: a dirty or untraceable run ({prov}) does not write arrival_h_fast.tif")
    reps = {a: json.loads((model_dir(a) / "arrival.json").read_text()) for a in areas}
    F, at = fast_divisor(list(reps.values()))
    for a, rep in reps.items():
        import rasterio
        m = model_dir(a)
        with rasterio.open(m / "arrival_h.tif") as d:
            arr = d.read(1)
            src_tags = d.tags()
        assert src_tags["git_commit"] == prov["git_commit"], f"{a}: arrival_h.tif is from {src_tags['git_commit']}, not {prov['git_commit']}"
        fast = (arr / F).astype("float32")
        tags = {**src_tags, "producer": "pipeline/10_arrival.py fast", "git_commit": prov["git_commit"], "dirty": prov["dirty"],
                "meaning": f"FAST bound: arrival_h / {F} (largest velocity/second-method ratio, {at}); NaN as arrival_h"}
        write(m / "arrival_h_fast.tif", fast, grid_of(m / "arrival_h.tif"), tags=tags)
        rep["fast"] = {"divisor": F, "from": at, "areas": areas,
                       "rule": "arrival_h_fast = arrival_h / F; the app headline is the FAST bound ('water could arrive in as little as X h')",
                       "aoi_arrival_h_fast_on_flooded_cells": {k: {q: (round(v[q] / F, 2) if q != "cells" else v[q]) for q in v}
                                                               for k, v in rep["aoi"]["arrival_h_on_flooded_cells"].items()}}
        (m / "arrival.json").write_text(json.dumps(rep, indent=2))
        handoff_md(a, config.load(a), grid_of(m / "arrival_h.tif"), rep, m / "arrival_h.tif", m / "arrival_h_fast.tif")
        print(a, "F", F, at)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("area", choices=[*config.areas(), "fast"])
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    raise SystemExit(write_fast(config.areas()) if a.area == "fast" else main(a.area, not a.no_write))
