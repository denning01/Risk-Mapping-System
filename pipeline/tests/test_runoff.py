"""M-04: SCS-CN runoff, CN/HSG lookup, flood mask and risk classes against hand-calculated values."""
import numpy as np
import pytest

from pipeline.lib import runoff


def test_scs_runoff_matches_hand_calculation():
    # CN 80: S = 25400/80 - 254 = 63.5 mm; Ia = 12.7 mm; P = 100: Q = 87.3^2 / (87.3 + 63.5) = 7621.29 / 150.8 = 50.539 mm
    assert runoff.scs_runoff(100.0, 80) == pytest.approx(50.5391, abs=1e-3)
    # CN 70: S = 108.857 mm; Ia = 21.771 mm; P = 150: Q = 128.229^2 / 237.086 = 69.353 mm
    assert runoff.scs_runoff(150.0, 70) == pytest.approx(69.353, abs=1e-2)
    # below initial abstraction -> 0 (CN 80, P 12 < Ia 12.7)
    assert runoff.scs_runoff(12.0, 80) == 0.0
    # TR-55 Table 2-1 "Runoff depth for selected CN's and rainfall amounts" (p.2-4), inches, printed to 0.01 in
    for p_in, cn, q_in in ((2.0, 90, 1.09), (4.0, 80, 2.04), (6.0, 70, 2.81), (1.0, 98, 0.79), (10.0, 40, 2.23),
                           (15.0, 85, 13.07)):
        assert runoff.scs_runoff(p_in * 25.4, cn) / 25.4 == pytest.approx(q_in, abs=0.0051), (p_in, cn)
    # monotone in P and CN, never above P
    p = np.linspace(0, 300, 61)
    for cn in (40, 70, 98):
        q = runoff.scs_runoff(p, cn)
        assert (np.diff(q) >= 0).all() and (q <= p + 1e-9).all()
    assert np.isnan(runoff.scs_runoff(100.0, np.nan))


def test_hsg_from_neh630_texture_bands():
    clay = np.array([5, 15, 30, 45, 5, 15, np.nan])
    sand = np.array([95, 70, 30, 20, 70, 40, 50])
    #               A   B   C   D   B(gap: sand<=90) B(gap: clay governs)  unknown
    np.testing.assert_array_equal(runoff.hsg_from_texture(clay, sand), [0, 1, 2, 3, 1, 1, -1])


def test_curve_number_lookup_from_tr55_rows():
    lc = np.array([10, 40, 50, 30, 80, 70])
    g = np.array([3, 2, 1, 0, 2, 2])
    # woods fair D 79; row crops SR poor C 88; commercial B 92; pasture fair A 49; water 98; snow (unmapped) NaN
    np.testing.assert_array_equal(runoff.curve_number(lc, g)[:5], [79, 88, 92, 49, 98])
    assert np.isnan(runoff.curve_number(lc, g)[5])
    assert np.isnan(runoff.curve_number(np.array([40]), np.array([-1]))[0])


def test_stage_is_k_times_q_to_alpha():
    assert runoff.stage(64.0, 0.25, 0.5) == pytest.approx(2.0)
    assert runoff.stage(0.0, 0.25, 0.5) == 0.0


def test_flood_depth_keeps_low_flat_cells_connected_to_a_channel():
    hand = np.array([[0.0, 0.5, 1.5, 0.2, 9.0],
                     [0.0, 0.5, 1.5, 9.0, 0.2],
                     [0.0, 0.5, 1.5, 9.0, 9.0]])
    channel = np.zeros(hand.shape, bool)
    channel[:, 0] = True
    slope = np.zeros(hand.shape)
    slope[2, 1] = 20.0                                    # too steep to pond
    perm = np.zeros(hand.shape, bool)
    d = runoff.flood_depth(hand, np.full(hand.shape, 1.0), slope, channel, perm)
    # col 0 (channel, HAND 0) depth 1.0; col 1 depth 0.5 except the steep cell; col 2 above stage;
    # (0,3) and (1,4) are low but isolated from the channel -> dry
    want = np.array([[1.0, 0.5, np.nan, np.nan, np.nan],
                     [1.0, 0.5, np.nan, np.nan, np.nan],
                     [1.0, np.nan, np.nan, np.nan, np.nan]])
    np.testing.assert_array_equal(np.isnan(d), np.isnan(want))
    np.testing.assert_allclose(d[~np.isnan(d)], want[~np.isnan(want)])
    # permanent water is never "flooded", but still connects its shore
    perm2 = np.zeros(hand.shape, bool)
    perm2[:, 0] = True
    d2 = runoff.flood_depth(hand, np.full(hand.shape, 1.0), slope, perm2, perm2)
    assert np.isnan(d2[:, 0]).all() and d2[0, 1] == pytest.approx(0.5)


def test_risk_classes_follow_the_contract_edges():
    d = np.array([np.nan, 0.0, 0.29, 0.3, 1.0, 1.01, 3.0])
    np.testing.assert_array_equal(runoff.risk_class(d), [0, 1, 1, 2, 2, 3, 3])


def test_season_ratio_is_ratio_of_area_means():
    ev = np.array([200.0, 400.0, np.nan])
    cl = np.array([100.0, 200.0, 150.0])
    assert runoff.season_ratio(ev, cl) == pytest.approx(2.0)
