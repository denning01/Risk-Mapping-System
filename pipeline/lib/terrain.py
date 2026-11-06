"""Terrain core (M-03): conditioned DEM, D8 flow, accumulation, channels, HAND, slope — all in UTM metres."""
from __future__ import annotations

import numpy as np

# pysheds 0.5 calls np.in1d, removed in numpy 2.4 (this venv has numpy 2.5). np.in1d(a, b) was
# np.isin(np.ravel(a), b). Shim it here rather than change the venv every worktree shares.
if not hasattr(np, "in1d"):
    np.in1d = lambda ar1, ar2, assume_unique=False, invert=False: np.isin(  # noqa: E731
        np.ravel(ar1), ar2, assume_unique=assume_unique, invert=invert)

from affine import Affine  # noqa: E402
from skimage.morphology import reconstruction  # noqa: E402
from pysheds.grid import Grid  # noqa: E402
from pysheds.sview import Raster, ViewFinder  # noqa: E402

NODATA = -9999.0


def slope_deg(dem: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Slope in degrees from central differences (numpy.gradient), cell sizes in metres."""
    gy, gx = np.gradient(dem.astype("float64"), dy, dx)
    return np.degrees(np.arctan(np.hypot(gx, gy)))


D8 = (64, 128, 1, 2, 4, 8, 16, 32)
_STEP = {64: (-1, 0), 128: (-1, 1), 1: (0, 1), 2: (1, 1), 4: (1, 0), 8: (1, -1), 16: (0, -1), 32: (-1, -1)}


def _terminals(fd: np.ndarray) -> np.ndarray:
    """Flat index of the cell where each cell's D8 path stops: an unroutable cell, or the last cell before the
    grid edge. Pointer jumping (log2 of the longest path iterations)."""
    h, w = fd.shape
    idx = np.arange(h * w).reshape(h, w)
    nxt = idx.copy()
    for code, (dr, dc) in _STEP.items():
        rr, cc = np.nonzero(fd == code)
        r2, c2 = rr + dr, cc + dc
        inside = (r2 >= 0) & (r2 < h) & (c2 >= 0) & (c2 < w)
        nxt[rr[inside], cc[inside]] = idx[r2[inside], c2[inside]]
    nxt = nxt.ravel()
    while True:
        jumped = nxt[nxt]
        if np.array_equal(jumped, nxt):
            return nxt.reshape(h, w)
        nxt = jumped


def route_leftover_flats(fdir: np.ndarray, cond: np.ndarray, outlet: np.ndarray | None = None) -> tuple[np.ndarray, int]:
    """Breach what pysheds leaves stranded. resolve_flats can leave interior cells with no D8 direction (a filled
    flat lifted by tiny increments around its old low point). On Nyando one sat ON the main stem near Muhoroni
    (35.107 E, -0.126) and cut 1,592 km2 of catchment off from Ahero (found while closing F2.1).
    Each stranded cell spills to its LOWEST neighbour whose path already reaches a real outlet (grid edge,
    `outlet` cells such as permanent water, or the edge of the DEM's nodata), even if that neighbour is
    marginally higher. Targets never drain through the stranded cell, so no cycle can form. Repeats until no
    change. Returns (fdir, cells routed)."""
    fd = fdir.copy()
    h, w = fd.shape
    finite = np.isfinite(cond)
    good_end = np.zeros((h, w), bool)
    good_end[[0, -1], :] = good_end[:, [0, -1]] = True
    if outlet is not None:
        good_end |= outlet
    nod = ~finite
    near_nod = np.zeros_like(nod)
    for dr, dc in _STEP.values():          # 8-neighbour: water can leave diagonally into the nodata hole too
        near_nod |= np.roll(np.roll(nod, dr, 0), dc, 1)
    good_end |= finite & near_nod
    from collections import deque
    n_fixed = 0
    while True:
        term = _terminals(fd)
        good = good_end.ravel()[term] & finite
        unrouted = ~np.isin(fd, D8) & finite & ~good
        unrouted[[0, -1], :] = unrouted[:, [0, -1]] = False
        if not unrouted.any():
            return fd, n_fixed
        # Phase 1, breadth-first from every good cell into unrouted cells that are no lower than it: a flat drains
        # cell by cell toward its outlet (nearest-to-outlet first), never uphill.
        q = deque()
        for r, c in np.argwhere(unrouted):
            for dr, dc in _STEP.values():
                if good[r + dr, c + dc] and cond[r + dr, c + dc] <= cond[r, c]:
                    q.append((r, c))
                    break
        changed = 0
        while q:
            r, c = q.popleft()
            if not unrouted[r, c]:
                continue
            best, best_z = None, None
            for code, (dr, dc) in _STEP.items():
                rr, cc = r + dr, c + dc
                if good[rr, cc] and cond[rr, cc] <= cond[r, c] and (best is None or cond[rr, cc] < best_z):
                    best, best_z = code, cond[rr, cc]
            if best is None:
                continue
            fd[r, c] = best
            good[r, c], unrouted[r, c] = True, False
            changed += 1
            for dr, dc in _STEP.values():
                rr, cc = r + dr, c + dc
                if unrouted[rr, cc] and cond[rr, cc] >= cond[r, c]:
                    q.append((rr, cc))
        n_fixed += changed
        if changed:
            continue                       # recompute terminals: cells draining into fixed ones are now good
        # Phase 2 (stalled): a true pit spills over its lowest neighbour that reaches an outlet, even if higher.
        for r, c in np.argwhere(unrouted):
            best, best_z = None, None
            for code, (dr, dc) in _STEP.items():
                rr, cc = r + dr, c + dc
                if good[rr, cc] and (best is None or cond[rr, cc] < best_z):
                    best, best_z = code, cond[rr, cc]
            if best is not None:
                fd[r, c] = best
                changed += 1
        n_fixed += changed
        if not changed:
            return fd, n_fixed


def fill_depressions(dem: np.ndarray, outlet: np.ndarray | None = None) -> np.ndarray:
    """Fill every depression to its spill level by morphological reconstruction by erosion (Soille 2004, as in
    skimage). Water may leave at the grid edge, at nodata cells and at `outlet` cells (permanent water).
    Replaces pysheds fill_pits/fill_depressions, which on Nyando left a depression's low cell unfilled
    (1194.6822 m under a filled flat at +0.0012 m) — a pit ON the main stem near Muhoroni."""
    ok = np.isfinite(dem) & (dem != NODATA)
    z = np.where(ok, dem, np.nanmin(np.where(ok, dem, np.nan)) - 1.0)
    keep = ~ok
    keep[[0, -1], :] = True
    keep[:, [0, -1]] = True
    if outlet is not None:
        keep |= outlet
    seed = np.where(keep, z, z.max())
    filled = reconstruction(seed, z, method="erosion")
    return np.where(ok, filled, np.nan)


def hydro(dem: np.ndarray, transform: Affine, crs: str, channel_km2: float,
          extra_drainage: np.ndarray | None = None) -> dict:
    """Fill pits/depressions, resolve flats, D8 flow, accumulation (cells), channels where the upstream
    area >= channel_km2, HAND (m) to the nearest drainage cell each cell drains to.
    extra_drainage (bool, same shape): cells that are drainage regardless of accumulation — permanent
    water. Without it, the lake-shore flats of the Kano plains drain into the lake, never meet a
    channel cell, and get HAND = NaN (found in M-03 on Nyando)."""
    vf = ViewFinder(affine=transform, shape=dem.shape, crs=crs, nodata=NODATA)
    filled = fill_depressions(dem.astype("float64"), extra_drainage)
    r = Raster(np.where(np.isfinite(filled), filled, NODATA).astype("float64"), viewfinder=vf)
    g = Grid.from_raster(r)
    # No pysheds resolve_flats: on Nyando it lifted a filled flat 0.12 m ABOVE its own outlet cell and recreated the
    # pit on the main stem. Flats are routed by route_leftover_flats() on the correctly filled surface instead.
    cond = r
    fdir = g.flowdir(cond)
    cond_a = np.asarray(cond, dtype="float64")
    fd_fixed, flats_routed = route_leftover_flats(np.asarray(fdir), np.where(cond_a <= NODATA + 1, np.nan, cond_a),
                                                  outlet=extra_drainage)
    fdir = Raster(fd_fixed.astype(np.asarray(fdir).dtype), viewfinder=fdir.viewfinder)
    acc = g.accumulation(fdir)
    cell_km2 = abs(transform.a * transform.e) / 1e6
    channels = np.asarray(acc) * cell_km2 >= channel_km2
    # Interior cells pysheds could not route (flowdir -2 unresolved flat, -1 pit, 0 nodata) end every
    # flow path through them; treat them as terminals (water ponds there) or all upstream HAND is NaN.
    fd = np.asarray(fdir)
    sinks = ~np.isin(fd, D8) & np.isfinite(dem) & (dem != NODATA)
    drainage = channels | sinks
    if extra_drainage is not None:
        drainage |= extra_drainage
    dmask = Raster(drainage, viewfinder=fdir.viewfinder)
    hand_filled = np.asarray(g.compute_hand(fdir, cond, dmask), dtype="float64")
    # flat index of the drainage cell each cell's HAND is measured against (-1 where none)
    hidx = np.asarray(g.compute_hand(fdir, cond, dmask, return_index=True, nodata_out=-1)).astype("int64")
    # F2.10: HAND from the RAW surface. pysheds measures on the filled DEM, which overstates HAND inside a filled
    # depression by its fill depth (up to 20.9 m on the Kano plain), making closed depressions look SAFER than they
    # are. hand = raw dem of the cell - filled elevation of its drainage cell, floored at 0 (a cell below its drain
    # level sits in a depression that ponds first).
    cond_a2 = np.asarray(cond, dtype="float64")
    ok = (hidx >= 0) & np.isfinite(dem) & (dem != NODATA) & np.isfinite(hand_filled)
    hand = np.full(dem.shape, np.nan)
    hand[ok] = np.maximum(dem[ok] - cond_a2.ravel()[hidx[ok]], 0.0)
    cond_out = np.asarray(cond, dtype="float64").copy()
    # F3.5: never let the -9999 sentinel reach a reader. Mask by the INPUT DEM's validity: resolve_flats nudges
    # nodata cells by tiny increments, so an exact `== NODATA` test missed 6,694 of 8,317 cells on Nyando.
    cond_out[~np.isfinite(dem) | (dem == NODATA) | (cond_out <= NODATA + 1)] = np.nan
    return {"cond": cond_out, "fdir": np.asarray(fdir), "acc": np.asarray(acc),
            "channels": channels, "drainage": drainage, "sinks": sinks, "flats_routed": flats_routed, "hand_index": hidx, "hand": hand,
            "hand_filled": hand_filled, "cell_km2": cell_km2}


FDIR_NODATA = -32768   # F3.6: pysheds emits -1 (pit), -2 (flat), 0 (nodata) as real codes; never use them as the tag


def fdir_for_disk(fdir: np.ndarray, dem: np.ndarray) -> np.ndarray:
    """int16 flow directions for GeoTIFF: D8 codes and pysheds' -2/-1/0 kept, cells without DEM -> FDIR_NODATA."""
    out = np.asarray(fdir).astype("int16")
    out[~np.isfinite(dem) | (dem == NODATA)] = FDIR_NODATA
    return out


def upstream_mean(fdir: np.ndarray, transform: Affine, crs: str, values: np.ndarray) -> np.ndarray:
    """Mean of `values` over each cell's upstream area (itself included), via D8 accumulation:
    accumulation(weights=values) / accumulation(). NaN values count as 0 and are excluded from the count."""
    vf = ViewFinder(affine=transform, shape=fdir.shape, crs=crs, nodata=0)
    fd = Raster(fdir.astype("int64"), viewfinder=vf)
    g = Grid.from_raster(fd)
    ok = np.isfinite(values)
    num = np.asarray(g.accumulation(fd, weights=Raster(np.where(ok, values, 0.0).astype("float64"), viewfinder=vf)))
    den = np.asarray(g.accumulation(fd, weights=Raster(ok.astype("float64"), viewfinder=vf)))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)
