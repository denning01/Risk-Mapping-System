"""Terrain core (M-03): conditioned DEM, D8 flow, accumulation, channels, HAND, slope — all in UTM metres."""
from __future__ import annotations

import numpy as np

# pysheds 0.5 calls np.in1d, removed in numpy 2.4 (this venv has numpy 2.5). np.in1d(a, b) was
# np.isin(np.ravel(a), b). Shim it here rather than change the venv every worktree shares.
if not hasattr(np, "in1d"):
    np.in1d = lambda ar1, ar2, assume_unique=False, invert=False: np.isin(  # noqa: E731
        np.ravel(ar1), ar2, assume_unique=assume_unique, invert=invert)

from affine import Affine  # noqa: E402
from pysheds.grid import Grid  # noqa: E402
from pysheds.sview import Raster, ViewFinder  # noqa: E402

NODATA = -9999.0


def slope_deg(dem: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Slope in degrees from central differences (numpy.gradient), cell sizes in metres."""
    gy, gx = np.gradient(dem.astype("float64"), dy, dx)
    return np.degrees(np.arctan(np.hypot(gx, gy)))


def hydro(dem: np.ndarray, transform: Affine, crs: str, channel_km2: float,
          extra_drainage: np.ndarray | None = None) -> dict:
    """Fill pits/depressions, resolve flats, D8 flow, accumulation (cells), channels where the upstream
    area >= channel_km2, HAND (m) to the nearest drainage cell each cell drains to.
    extra_drainage (bool, same shape): cells that are drainage regardless of accumulation — permanent
    water. Without it, the lake-shore flats of the Kano plains drain into the lake, never meet a
    channel cell, and get HAND = NaN (found in M-03 on Nyando)."""
    vf = ViewFinder(affine=transform, shape=dem.shape, crs=crs, nodata=NODATA)
    r = Raster(np.where(np.isfinite(dem), dem, NODATA).astype("float64"), viewfinder=vf)
    g = Grid.from_raster(r)
    cond = g.resolve_flats(g.fill_depressions(g.fill_pits(r)))
    fdir = g.flowdir(cond)
    acc = g.accumulation(fdir)
    cell_km2 = abs(transform.a * transform.e) / 1e6
    channels = np.asarray(acc) * cell_km2 >= channel_km2
    # Interior cells pysheds could not route (flowdir -2 unresolved flat, -1 pit, 0 nodata) end every
    # flow path through them; treat them as terminals (water ponds there) or all upstream HAND is NaN.
    fd = np.asarray(fdir)
    sinks = ~np.isin(fd, (64, 128, 1, 2, 4, 8, 16, 32)) & np.isfinite(dem) & (dem != NODATA)
    drainage = channels | sinks
    if extra_drainage is not None:
        drainage |= extra_drainage
    dmask = Raster(drainage, viewfinder=fdir.viewfinder)
    hand = g.compute_hand(fdir, cond, dmask)
    # flat index of the drainage cell each cell's HAND is measured against (-1 where none)
    hidx = np.asarray(g.compute_hand(fdir, cond, dmask, return_index=True, nodata_out=-1)).astype("int64")
    cond_out = np.asarray(cond, dtype="float64").copy()
    # F3.5: never let the -9999 sentinel reach a reader. Mask by the INPUT DEM's validity: resolve_flats nudges
    # nodata cells by tiny increments, so an exact `== NODATA` test missed 6,694 of 8,317 cells on Nyando.
    cond_out[~np.isfinite(dem) | (dem == NODATA) | (cond_out <= NODATA + 1)] = np.nan
    return {"cond": cond_out, "fdir": np.asarray(fdir), "acc": np.asarray(acc),
            "channels": channels, "drainage": drainage, "sinks": sinks, "hand_index": hidx, "hand": np.asarray(hand, dtype="float64"), "cell_km2": cell_km2}


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
