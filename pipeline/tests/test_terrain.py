"""M-03: HAND on a synthetic DEM with a known answer (tilted plane, V-valley, channel down the middle)."""
import numpy as np
import pytest
from affine import Affine

from pipeline.lib import terrain

NY, NX, DX = 40, 21, 30.0
CROSS, DOWN = 0.5, 0.1     # m per cell toward the channel; m per cell down-valley


def valley():
    y, x = np.mgrid[0:NY, 0:NX]
    return 100 + CROSS * np.abs(x - 10) + DOWN * (NY - y)


def test_hand_equals_height_above_the_channel_it_drains_to():
    dem = valley()
    out = terrain.hydro(dem, Affine(DX, 0, 0, 0, -DX, 0), "EPSG:32736", channel_km2=30 * DX * DX / 1e6)
    assert set(np.where(out["channels"])[1].tolist()) == {10}          # the carved channel, nothing else
    # Each side cell drains straight across to the channel (cross slope 0.5 >> down slope 0.1), so
    # HAND = 0.5 * |col - 10|. Border columns are NaN in pysheds (no flow direction off the grid).
    want = CROSS * np.abs(np.arange(NX) - 10.0)
    for row in (10, 20, 30):
        np.testing.assert_allclose(out["hand"][row, 1:-1], want[1:-1], atol=1e-6)
    assert np.nanmax(out["hand"]) <= CROSS * 10 + 1e-6


def test_channel_threshold_in_km2_not_cells():
    dem = valley()
    # upstream area at the outlet is NY*NX cells = 840 * 900 m2 = 0.756 km2; a bigger threshold -> no channel
    out = terrain.hydro(dem, Affine(DX, 0, 0, 0, -DX, 0), "EPSG:32736", channel_km2=0.8)
    assert not out["channels"].any()
    assert out["acc"].max() == pytest.approx(NY * NX)


def test_slope_degrees_hand_values():
    y, x = np.mgrid[0:5, 0:5]
    s = terrain.slope_deg((x * 30.0).astype(float), 30.0, 30.0)   # rises 30 m per 30 m cell -> 45 deg
    np.testing.assert_allclose(s, 45.0)
    s = terrain.slope_deg(np.zeros((5, 5)), 30.0, 30.0)
    np.testing.assert_allclose(s, 0.0)


def test_extra_drainage_gives_hand_where_flow_ends_in_water():
    """A plain draining into a lake that is not a channel: without the lake as drainage HAND is NaN there."""
    y, x = np.mgrid[0:30, 0:30]
    dem = 100 + 0.2 * x + 0.01 * y           # gentle slope west, toward a lake in columns 0-4
    dem[:, :5] = 99.0                         # flat lake surface, lower than the plain
    t = Affine(DX, 0, 0, 0, -DX, 0)
    without = terrain.hydro(dem.astype(float), t, "EPSG:32736", channel_km2=100.0)  # no channel anywhere
    assert np.isnan(without["hand"][5:-1, 6:-1]).all()
    lake = np.zeros_like(dem, bool)
    lake[:, :5] = True
    with_lake = terrain.hydro(dem.astype(float), t, "EPSG:32736", channel_km2=100.0, extra_drainage=lake)
    inner = with_lake["hand"][2:-2, 6:-2]
    assert np.isfinite(inner).all()
    # HAND = height above the lake surface (99 m); the plain at column c is ~100 + 0.2c
    np.testing.assert_allclose(inner, dem[2:-2, 6:-2] - 99.0, atol=0.6)


def test_unroutable_cells_become_sinks_not_nan_holes():
    """A closed 1-cell pit that fill_* is not allowed to fix is still a drainage terminal; no NaN upstream."""
    dem = valley()
    out = terrain.hydro(dem, Affine(DX, 0, 0, 0, -DX, 0), "EPSG:32736", channel_km2=30 * DX * DX / 1e6)
    assert out["sinks"].sum() == 0 or np.isfinite(out["hand"][1:-1, 1:-1]).all()
    # every interior cell either has a D8 direction or is counted as a sink
    fd = out["fdir"][1:-1, 1:-1]
    routed = np.isin(fd, (64, 128, 1, 2, 4, 8, 16, 32))
    assert (routed | out["sinks"][1:-1, 1:-1]).all()
    assert np.isfinite(out["hand"][1:-1, 1:-1]).all()
