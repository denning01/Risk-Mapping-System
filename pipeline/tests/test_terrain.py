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


def test_hand_index_points_at_the_channel_cell_in_the_same_row():
    dem = valley()
    out = terrain.hydro(dem, Affine(DX, 0, 0, 0, -DX, 0), "EPSG:32736", channel_km2=30 * DX * DX / 1e6)
    r, c = np.unravel_index(out["hand_index"][20, 3], dem.shape)
    assert c == 10 and r == 20                       # cross slope dominates: straight across to the channel
    assert out["hand"][20, 3] == pytest.approx(dem[20, 3] - out["cond"][r, c], abs=1e-6)


def test_upstream_mean_of_a_constant_is_the_constant_and_mixes_by_area():
    dem = valley()
    t = Affine(DX, 0, 0, 0, -DX, 0)
    out = terrain.hydro(dem, t, "EPSG:32736", channel_km2=30 * DX * DX / 1e6)
    m = terrain.upstream_mean(out["fdir"], t, "EPSG:32736", np.full(dem.shape, 7.0))
    np.testing.assert_allclose(m[1:-1, 1:-1], 7.0)
    half = np.where(np.arange(NX)[None, :] < 10, 0.0, 10.0) * np.ones((NY, 1))   # west 0, east (incl. channel) 10
    m = terrain.upstream_mean(out["fdir"], t, "EPSG:32736", half)
    outlet = m[NY - 2, 10]   # near the bottom of the channel: ~half the upstream cells are each side
    assert 4.0 < outlet < 6.5


def _bowl_with_hole():
    """A bowl draining to its centre, with the centre cell missing (NaN): the 8 cells around the hole have no
    D8 direction pysheds can resolve. Real-world analogue: the Kano-plain flats near the lake (M-03)."""
    y, x = np.mgrid[0:21, 0:21]
    dem = (100 + 0.5 * np.hypot(x - 10, y - 10)).astype(float)
    dem[10, 10] = np.nan
    return dem


def test_sink_rule_is_what_gives_hand_around_an_unroutable_cell(monkeypatch):
    """F3.7: fails without the sink rule. The ring around the hole is unroutable; with sinks as drainage its HAND is 0
    and finite, without them it is NaN."""
    dem = _bowl_with_hole()
    t = Affine(DX, 0, 0, 0, -DX, 0)
    out = terrain.hydro(dem, t, "EPSG:32736", channel_km2=100.0)
    ring = out["sinks"].copy()
    ring[[0, -1], :] = ring[:, [0, -1]] = False      # interior only (pysheds also leaves some edge cells unrouted)
    assert ring.sum() == 8 and not ring[10, 10]
    assert np.isfinite(out["hand"][ring]).all() and (out["hand"][ring] == 0).all()
    real_isin = np.isin
    monkeypatch.setattr(terrain.np, "isin", lambda a, b, **k: np.ones_like(np.asarray(a), bool)
                        if tuple(b) == (64, 128, 1, 2, 4, 8, 16, 32) else real_isin(a, b, **k))
    no_sinks = terrain.hydro(dem, t, "EPSG:32736", channel_km2=100.0)
    assert not no_sinks["sinks"].any()
    assert np.isnan(no_sinks["hand"][ring]).all()


def test_cond_never_carries_the_minus_9999_sentinel():
    """F3.5: NaN in the DEM must come out as NaN in cond, not -9999."""
    dem = _bowl_with_hole()
    dem[3:6, 15:18] = np.nan                           # a larger hole, flat-resolved by pysheds (nudged values)
    out = terrain.hydro(dem, Affine(DX, 0, 0, 0, -DX, 0), "EPSG:32736", channel_km2=100.0)
    assert np.nanmin(out["cond"]) > 0                  # no -9999 nor -9998.99... anywhere
    np.testing.assert_array_equal(np.isnan(out["cond"]), ~np.isfinite(dem))


def test_flowdir_on_disk_keeps_pysheds_codes_and_uses_a_free_nodata():
    """F3.6: -1/-2/0 are pysheds codes; the file's nodata must be a value pysheds never emits."""
    dem = _bowl_with_hole()
    out = terrain.hydro(dem, Affine(DX, 0, 0, 0, -DX, 0), "EPSG:32736", channel_km2=100.0)
    disk = terrain.fdir_for_disk(out["fdir"], dem)
    assert disk.dtype == np.int16 and disk[10, 10] == terrain.FDIR_NODATA
    assert terrain.FDIR_NODATA not in (64, 128, 1, 2, 4, 8, 16, 32, 0, -1, -2)
    keep = np.isfinite(dem)
    np.testing.assert_array_equal(disk[keep], out["fdir"][keep].astype(np.int16))


def test_upstream_mean_excludes_nan_cells_from_the_count():
    """F3.17: NaN inputs (gaps) must drop out of numerator AND denominator. A field that is 7 where defined and
    NaN on the whole west half must still average 7 everywhere downstream — counting NaN as 0 would give ~3.5."""
    dem = valley()
    t = Affine(DX, 0, 0, 0, -DX, 0)
    out = terrain.hydro(dem, t, "EPSG:32736", channel_km2=30 * DX * DX / 1e6)
    vals = np.full(dem.shape, 7.0)
    vals[:, :10] = np.nan
    m = terrain.upstream_mean(out["fdir"], t, "EPSG:32736", vals)
    np.testing.assert_allclose(m[1:-1, 10], 7.0)            # channel: mixes NaN-west and 7-east upstream areas
    assert np.isnan(m[5, 3])                                 # a west cell whose whole upstream area is NaN
