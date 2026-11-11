"""M-04 runoff and flood stage: curve numbers, SCS-CN runoff, HAND flood mask, depth and risk classes.

Sources (verified from the primary PDFs, page numbers given):
- USDA SCS (1986) Urban Hydrology for Small Watersheds, TR-55, 2nd ed., 210-VI-TR-55, June 1986,
  Table 2-2a (p.2-5), 2-2b (p.2-6), 2-2c (p.2-7). Copy used: https://ponce.sdsu.edu/tr55.pdf
- USDA NRCS (2009) NEH Part 630 Hydrology, Ch.7 Hydrologic Soil Groups, 210-VI-NEH, Jan 2009, §630.0701
  p.7-2/7-3. https://directives.nrcs.usda.gov/sites/default/files2/1712930597/11905.pdf
SCS-CN: S = 25400/CN - 254 (mm); Ia = 0.2 S; Q = (P - Ia)^2 / (P - Ia + S) for P > Ia, else 0.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

HSG = ("A", "B", "C", "D")

# ESA WorldCover v200 class -> (TR-55 cover type it stands for, CN for HSG A, B, C, D).
# Choices (screening-level, stated on the methods slide): rural Kenyan cover in "fair"/"poor" condition.
CN_TABLE = {
    10: ("tree cover -> woods, fair (2-2c)", (36, 60, 73, 79)),
    20: ("shrubland -> brush, fair (2-2c)", (35, 56, 70, 77)),
    30: ("grassland -> pasture/grassland/range, fair (2-2c)", (49, 69, 79, 84)),
    40: ("cropland -> row crops, straight row, poor (2-2b)", (72, 81, 88, 91)),
    50: ("built-up -> commercial and business, 85 % impervious (2-2a)", (89, 92, 94, 95)),
    60: ("bare/sparse -> fallow, bare soil (2-2b)", (77, 86, 91, 94)),
    80: ("permanent water -> 98 (impervious/water surface, 2-2a)", (98, 98, 98, 98)),
    90: ("herbaceous wetland -> 98 (saturated; assumption, not a TR-55 row)", (98, 98, 98, 98)),
    95: ("mangroves -> woods, fair (2-2c; assumption)", (36, 60, 73, 79)),
}


def hsg_from_texture(clay_pct, sand_pct) -> np.ndarray:
    """Hydrologic soil group index 0..3 (A..D) from topsoil texture, NEH 630 Ch.7 §630.0701 ("typically"):
    A <10 % clay and >90 % sand; B 10-20 % clay, 50-90 % sand; C 20-40 % clay, <50 % sand; D >40 % clay, <50 % sand.
    The four bands leave gaps (e.g. 15 % clay with 40 % sand); clay governs (it controls infiltration), sand only
    separates A from B. No depth-to-water-table or restrictive-layer rules (no data): a screening simplification.
    NaN texture -> -1."""
    clay = np.asarray(clay_pct, dtype="float64")
    sand = np.asarray(sand_pct, dtype="float64")
    g = np.select([clay > 40, clay > 20, clay >= 10, sand > 90], [3, 2, 1, 0], default=1)
    return np.where(np.isfinite(clay) & np.isfinite(sand), g, -1).astype("int8")


def fill_nearest(a) -> tuple[np.ndarray, np.ndarray]:
    """Fill NaN cells with the value of the nearest finite cell (Euclidean, in pixels). Returns (filled, was_nan).
    Used for SoilGrids texture under cities, where SoilGrids has no prediction (M-07: 55 % of the Nairobi AOI)."""
    from scipy import ndimage
    a = np.asarray(a, dtype="float64")
    bad = ~np.isfinite(a)
    if not bad.any() or bad.all():
        return a.copy(), bad
    idx = ndimage.distance_transform_edt(bad, return_distances=False, return_indices=True)
    return a[tuple(idx)], bad


def curve_number(landcover, hsg) -> np.ndarray:
    """CN per cell from WorldCover class and HSG index (0..3). NaN where either is unknown."""
    lc = np.asarray(landcover)
    g = np.asarray(hsg)
    cn = np.full(lc.shape, np.nan)
    for cls, (_, row) in CN_TABLE.items():
        for i, v in enumerate(row):
            cn[(lc == cls) & (g == i)] = v
    return cn


def scs_runoff(p_mm, cn) -> np.ndarray:
    """Runoff depth Q (mm) for rainfall P (mm) and curve number CN, TR-55 eq. 2-1..2-4 with Ia = 0.2 S."""
    p = np.asarray(p_mm, dtype="float64")
    cn = np.asarray(cn, dtype="float64")
    s = 25400.0 / cn - 254.0
    ia = 0.2 * s
    with np.errstate(invalid="ignore", divide="ignore"):
        q = np.where(p > ia, (p - ia) ** 2 / (p - ia + s), 0.0)
    return np.where(np.isfinite(cn), q, np.nan)


def stage(v_up, k: float, alpha: float = 0.4) -> np.ndarray:
    """Flood stage h (m above the drainage cell) = k * V_up^alpha, V_up = upstream runoff VOLUME in 1000 m3
    (= sum over the upstream area of Q mm x cell km2), a discharge proxy for a storm of fixed duration.
    F4.2: the plan's h = k * Q^alpha with Q a mean runoff DEPTH gave every channel the same stage (~3.05 m for a
    10 km2 stream and the 3,422 km2 main stem alike). Depth grows downstream with discharge as d = c Q^f, f = 0.4
    on average (Leopold & Maddock 1953, USGS Prof. Paper 252, p.16, at mean annual discharge;
    https://pubs.usgs.gov/pp/0252/report.pdf). k is calibrated in M-05."""
    v = np.asarray(v_up, dtype="float64")
    return k * np.power(np.maximum(v, 0.0), alpha)


def flood_depth(hand, h_at_drain, slope, connect_to, exclude, max_slope=15.0) -> np.ndarray:
    """Depth (m) = h - HAND where HAND < h, slope < max_slope, not `exclude` (permanent water), and the cell's
    8-connected wet patch touches a `connect_to` cell (channel or permanent water). NaN = dry.
    `h_at_drain` is the stage of the drainage cell each cell drains to (so each reach floods to its own level)."""
    with np.errstate(invalid="ignore"):
        wet = (hand < h_at_drain) & (slope < max_slope) & np.isfinite(hand) & ~exclude
    lab, n = ndimage.label(wet | connect_to, structure=np.ones((3, 3), bool))
    seeds = np.unique(lab[connect_to & (lab > 0)])
    keep = wet & np.isin(lab, seeds)
    return np.where(keep, h_at_drain - hand, np.nan)


RISK_EDGES_M = (0.3, 1.0)   # docs/DATA_CONTRACT.md: < 0.3 low, 0.3-1 medium, > 1 high


def risk_class(depth) -> np.ndarray:
    """0 dry, 1 low (< 0.3 m), 2 medium (0.3-1 m), 3 high (> 1 m)."""
    d = np.asarray(depth, dtype="float64")
    r = np.select([d > RISK_EDGES_M[1], d >= RISK_EDGES_M[0], d >= 0], [3, 2, 1], default=0)
    return np.where(np.isfinite(d), r, 0).astype("uint8")


def season_ratio(event_season_px: np.ndarray, clim_season_px: np.ndarray) -> float:
    """El Nino anomaly ratio over an area: mean over pixels of the event-season total / mean over pixels of the
    climatological mean season total (plan §4.5). Pixels NaN in either are dropped."""
    ok = np.isfinite(event_season_px) & np.isfinite(clim_season_px)
    return float(event_season_px[ok].mean() / clim_season_px[ok].mean())


def scenario_depth(p_mm: float, cn, fdir, transform, crs, hand, hand_index, slope, connect_to, exclude,
                   k: float, alpha: float, cell_km2: float):
    """One scenario on the M-03 grid: Q per cell -> upstream runoff volume V_up (1000 m3) -> stage of each DRAINAGE
    cell -> each cell takes the stage of the drainage cell it drains to (hand_index) -> flood_depth.
    Returns (depth m NaN = dry, h at each cell, Q mm)."""
    from pipeline.lib import terrain
    q = scs_runoff(p_mm, cn)
    v_up = terrain.upstream_sum(fdir, transform, crs, q * cell_km2)
    h_drain = stage(v_up, k, alpha)
    ok = hand_index >= 0
    h = np.full(hand.shape, np.nan)
    h[ok] = h_drain.ravel()[hand_index[ok]]
    return flood_depth(hand, h, slope, connect_to, exclude), h, q


def water_mask(perm, landcover) -> np.ndarray:
    """Cells that never "flood": JRC occurrence >= 80 % (perm) OR ESA WorldCover 2021 permanent water (class 80).
    JRC alone missed 5.22 km2 of Lake Victoria margin (JRC 69 %, DEM flattened at 1133.00 m) — M-06."""
    return np.asarray(perm, bool) | (np.asarray(landcover) == 80)


def season_rank(totals: dict, event_year: int, first: int, last: int) -> tuple[int, int]:
    """Rank (1 = wettest) of event_year among the seasons first..last by area-mean total. Refuses a record with a
    missing year: F5.3 — a rank over only the files on disk said "5th of 31" when the full 1991-2023 record gives
    6th of 33 (2021-2022 were not downloaded)."""
    missing = [y for y in range(first, last + 1) if y not in totals]
    if missing:
        raise ValueError(f"season record {first}-{last} is missing {missing}; a rank needs every season")
    years = sorted((y for y in totals if first <= y <= last), key=lambda y: totals[y], reverse=True)
    return years.index(event_year) + 1, len(years)
