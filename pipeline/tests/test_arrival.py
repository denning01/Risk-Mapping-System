"""M-20 arrival time: the velocity method on small synthetic D8 grids, with expected times computed here by hand from
NEH 630 ch. 15 table 15-3 / eq. 15-10, never by calling the code under test for its own expected value."""
import importlib
import math

import numpy as np
import pytest

ar = importlib.import_module("pipeline.10_arrival")
FT = 0.3048
E, SE, S_, N = 1, 2, 4, 64   # pysheds D8 codes: east, south-east, south, north


def run(fdir, z, acc_km2=None, wc=None, perm=None, land=None, **over):
    fdir = np.asarray(fdir, np.int16)
    z = np.asarray(z, float)
    shape = fdir.shape
    acc_km2 = np.zeros(shape) if acc_km2 is None else np.asarray(acc_km2, float)
    wc = np.full(shape, 40, np.int16) if wc is None else np.asarray(wc, np.int16)   # cropland unless stated
    perm = np.zeros(shape, bool) if perm is None else np.asarray(perm, bool)
    land = np.zeros(shape) if land is None else np.asarray(land, float)
    valid = np.ones(shape, bool)
    return ar.compute(fdir, z, acc_km2, wc, perm, valid, land, **over)


def test_hillslope_line_is_the_sum_of_table_15_3_link_times_on_the_land_slope():
    # 1 x 4, flowing east; cropland = "cultivated straight row crops" 8.762 ft/s; land slope 4 %, 9 %, 1 %
    fdir = [[E, E, E, 0]]
    land = [[0.04, 0.09, 0.01, 0.0]]
    R = run(fdir, [[30, 20, 10, 0]], land=land)
    k = 8.762 * FT
    want = sum(30 / (k * math.sqrt(s)) for s in (0.04, 0.09, 0.01))
    assert R["T"][3] == pytest.approx(want, rel=1e-12)
    assert R["T"][0] == 0                                              # a ridge cell: nothing upstream
    assert list(R["T"]) == sorted(R["T"])                              # later downstream


def test_land_cover_sets_k_built_up_is_pavement_forest_is_heavy_litter():
    fdir = [[E, 0]]
    for cls, k_ft in ((50, 20.328), (10, 2.516), (30, 6.962), (20, 5.032), (60, 9.965)):
        R = run(fdir, [[1, 0]], wc=[[cls, cls]], land=[[0.04, 0]])
        assert R["t"][0] == pytest.approx(30 / (k_ft * FT * 0.2), rel=1e-12), cls


def test_a_junction_takes_the_slower_branch_not_the_sum_or_the_faster():
    #   (0,0)->(0,1)->(0,2)->(1,3)   slow branch (forest, 1 %)
    #   (1,2)->(1,3)                  fast branch (paved, 16 %: 2.5 m/s, under the cap)
    fdir = np.zeros((2, 4), np.int16)
    fdir[0, 0] = fdir[0, 1] = E
    fdir[0, 2] = SE
    fdir[1, 2] = E
    wc = np.array([[10, 10, 10, 10], [50, 50, 50, 50]])
    land = np.array([[0.01, 0.01, 0.01, 0], [0, 0, 0.16, 0]])
    R = run(fdir, np.zeros((2, 4)), wc=wc, land=land)
    k_f, k_p = 2.516 * FT, 20.328 * FT
    slow = 30 / (k_f * 0.1) * 2 + 30 * math.sqrt(2) / (k_f * 0.1)       # two straight links, one diagonal
    assert R["T"][7] == pytest.approx(slow, rel=1e-12)
    assert R["L"][7] == pytest.approx(60 + 30 * math.sqrt(2))           # longest flow length, diagonal = 30 sqrt 2
    assert R["t"][6] == pytest.approx(30 / (k_p * 0.4), rel=1e-12)


def test_channels_use_manning_with_the_stated_radius_and_the_reach_slope():
    # a 1 x 12 channel at a constant 0.4 % on the conditioned DEM; 0.5 km2 = small channel, 20 km2 = main
    z = 0.004 * 30 * np.arange(12)[::-1]
    fdir = [[E] * 11 + [0]]
    for km2, r in ((0.5, ar.R_SMALL_M), (20.0, ar.R_MAIN_M)):
        R = run(fdir, [z], acc_km2=[[km2] * 12])
        v = r ** (2 / 3) * math.sqrt(0.004) / ar.N_CHANNEL
        assert R["t"][0] == pytest.approx(30 / v, rel=1e-9), km2
        assert set(R["regime"][:11]) == {1 if km2 < 10 else 2}


def test_a_filled_flat_takes_the_drop_of_its_reach_and_a_true_flat_hits_the_floor():
    # dem_cond: 5 flat links then a 2 m drop over one link; the reach slope of link 0 over 10 links (here to the end, 6
    # links, 180 m) is 2 / 180
    z = [[2, 2, 2, 2, 2, 2, 0]]
    fdir = [[E] * 6 + [0]]
    R = run(fdir, z, acc_km2=[[20] * 7])
    assert R["slope"][0] == pytest.approx(2 / 180)
    flat = run([[E, E, 0]], [[0, 0, 0]], acc_km2=[[20] * 3])
    v = ar.R_MAIN_M ** (2 / 3) * math.sqrt(ar.SLOPE_MIN) / ar.N_CHANNEL
    assert flat["t"][0] == pytest.approx(30 / v)


def test_velocity_is_capped():
    R = run([[E, 0]], [[0, 0]], wc=[[50, 50]], land=[[1.0, 0]])     # paved at 100 %: 6.2 m/s uncapped
    assert R["t"][0] == pytest.approx(30 / ar.V_MAX)


def test_permanent_water_is_routed_as_a_main_channel():
    R = run([[E, E, 0]], [[0.24, 0.12, 0]], perm=[[True, True, False]])
    assert R["regime"][0] == 2


def test_a_cell_draining_from_the_grid_border_is_flagged_truncated():
    # 3 x 3; the border cell (0,1) drains south into the centre; (1,1) drains south to (2,1)
    fdir = np.zeros((3, 3), np.int16)
    fdir[0, 1] = S_
    fdir[1, 1] = S_
    R = run(fdir, np.zeros((3, 3)))
    assert R["trunc"][4] and R["trunc"][7]
    fdir2 = np.zeros((5, 5), np.int16)
    fdir2[2, 2] = E                                                    # interior -> interior; its receiver (2,3) is not
    R2 = run(fdir2, np.zeros((5, 5)))                                  # on the border either
    assert not R2["trunc"][2 * 5 + 3]


def test_catchment_labels_split_nested_outlets():
    # a 1 x 6 line east; outlets at index 2 and 5: cells 0-2 -> outlet 0, cells 3-5 -> outlet 1
    R = run([[E] * 5 + [0]], [[5, 4, 3, 2, 1, 0]])
    lab = ar.label_catchments(R["rcv"], R["batches"], [2, 5])
    assert list(lab) == [0, 0, 0, 1, 1, 1]


def test_kirpich_si_matches_the_feet_form():
    # TxDOT eq. 4-15: K = 0.0195 (SI, L m) and K = 0.0078 (L ft), minutes
    for L, S in ((1000.0, 0.01), (18330.0, 0.0157)):
        ft_form = 0.0078 * (L / FT) ** 0.770 * S ** -0.385 / 60
        assert ar.kirpich_h(L, S) == pytest.approx(ft_form, rel=2e-3)


def test_scs_lag_reproduces_the_neh_mawney_brook_example():
    # NEH 630 15-12: l = 3,865 ft, CN 63, Y = 4.79 % -> Tc = 1.14 h
    assert ar.scs_lag_tc_h(3865 * FT, 63, 4.79) == pytest.approx(1.14, abs=0.01)


def test_main_refuses_to_write_from_a_dirty_tree(monkeypatch):
    monkeypatch.setattr(ar, "provenance", lambda: {"git_commit": "abc1234", "dirty": True})

    def no_data(*a, **k):   # if the guard is gone, fail here, before any raster is read or written
        raise AssertionError("main went past the dirty-tree guard")
    monkeypatch.setattr(ar.config, "load", no_data)
    with pytest.raises(SystemExit, match="REFUSED"):
        ar.main("nyando", write_out=True)
