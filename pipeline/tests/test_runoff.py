"""M-04: SCS-CN runoff, CN/HSG lookup, flood mask and risk classes against hand-calculated values."""
from pathlib import Path

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


def test_stage_is_k_times_volume_to_alpha():
    assert runoff.stage(1e4, 0.02, 0.4) == pytest.approx(0.02 * 10 ** 1.6)
    assert runoff.stage(0.0, 0.02, 0.4) == 0.0
    # same runoff depth, 100x the area -> 100^0.4 = 6.31x the stage (F4.2: depth grows downstream with discharge)
    assert runoff.stage(50.0 * 1000, 0.02) / runoff.stage(50.0 * 10, 0.02) == pytest.approx(100 ** 0.4)


def test_stage_grows_downstream_along_a_channel_with_uniform_runoff():
    """F4.2: on a valley with uniform CN, the drainage-cell stage must rise monotonically downstream; with a mean
    runoff DEPTH (the plan's form) it is constant along the whole channel."""
    from affine import Affine
    from pipeline.lib import terrain
    from pipeline.tests.test_terrain import DX, valley
    dem = valley()
    t = Affine(DX, 0, 0, 0, -DX, 0)
    out = terrain.hydro(dem, t, "EPSG:32736", channel_km2=30 * DX * DX / 1e6)
    cn = np.full(dem.shape, 80.0)
    _, h, q = runoff.scenario_depth(100.0, cn, out["fdir"], t, "EPSG:32736", out["hand"], out["hand_index"],
                                    np.zeros(dem.shape), out["channels"], np.zeros(dem.shape, bool), 0.05, 0.4,
                                    DX * DX / 1e6)
    rows = [r for r in range(1, dem.shape[0] - 1) if out["channels"][r, 10]]
    hc = h[rows, 10]                                   # row index grows downstream (dem falls with y)
    assert len(rows) > 10 and (np.diff(hc) > 0).all()
    assert hc[-1] / hc[0] > 2.0
    q_mean = terrain.upstream_mean(out["fdir"], t, "EPSG:32736", q)
    assert np.ptp(q_mean[rows, 10]) < 1e-9              # the old form: no downstream growth at all


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


TR55_ROWS = {   # TR-55 (1986) Table 2-2a/b/c, typed from the PDF (pages 2-5..2-7); auditor re-read them in R4
    10: (36, 60, 73, 79), 20: (35, 56, 70, 77), 30: (49, 69, 79, 84), 40: (72, 81, 88, 91),
    50: (89, 92, 94, 95), 60: (77, 86, 91, 94), 80: (98, 98, 98, 98), 90: (98, 98, 98, 98), 95: (36, 60, 73, 79)}


def test_cn_table_pins_every_value():
    assert {c: v for c, (_, v) in runoff.CN_TABLE.items()} == TR55_ROWS
    for cls, row in TR55_ROWS.items():
        np.testing.assert_array_equal(runoff.curve_number(np.full(4, cls), np.arange(4)), row)


def test_hsg_band_edges_follow_neh630():
    # A <10 % clay AND >90 % sand; B 10-20 % clay; C 20-40 %; D >40 % (edges belong to the lower-numbered band's
    # text: "20-40 %" includes 40 -> C; "10-20 %" includes 20 -> B; "<10 %" excludes 10)
    clay = np.array([9.99, 9.99, 10.0, 20.0, 20.01, 40.0, 40.01])
    sand = np.array([90.01, 90.0, 95.0, 30.0, 30.0, 10.0, 10.0])
    np.testing.assert_array_equal(runoff.hsg_from_texture(clay, sand), [0, 1, 1, 1, 2, 2, 3])


def test_flood_mask_is_strict_at_the_stage_and_at_15_degrees():
    hand = np.array([[0.0, 1.0, 0.5]])
    slope = np.array([[0.0, 0.0, 15.0]])
    ch = np.array([[True, False, False]])
    d = runoff.flood_depth(hand, np.full(hand.shape, 1.0), slope, ch, np.zeros(hand.shape, bool))
    assert d[0, 0] == 1.0 and np.isnan(d[0, 1]) and np.isnan(d[0, 2])     # HAND == h dry; slope == 15 dry


def test_water_mask_adds_worldcover_water_to_jrc():
    perm = np.array([True, False, False, False])
    lc = np.array([30, 80, 90, 10])                      # WorldCover 80 = permanent water; 90 wetland is NOT water
    np.testing.assert_array_equal(runoff.water_mask(perm, lc), [True, True, False, False])


def test_season_rank_refuses_a_record_with_missing_years():
    totals = {y: float(y % 7) for y in range(1991, 2024)}
    totals[2023] = 5.5                                     # only years with value 6 are wetter
    rank, n = runoff.season_rank(totals, 2023, 1991, 2023)
    assert n == 33 and rank == 1 + sum(v > 5.5 for y, v in totals.items() if y != 2023)
    del totals[2021], totals[2022]
    with pytest.raises(ValueError, match=r"missing \[2021, 2022\]"):
        runoff.season_rank(totals, 2023, 1991, 2023)


def _fake_chirps(root, years):
    import rasterio
    from rasterio.transform import from_origin
    d = root / "raw" / "nyando" / "chirps" / "monthly"
    d.mkdir(parents=True)
    for y in years:
        for m in (10, 11, 12):
            with rasterio.open(d / f"{y}-{m:02d}.tif", "w", driver="GTiff", height=2, width=2, count=1, dtype="float32",
                               crs="EPSG:4326", transform=from_origin(34.9, -0.1, 0.05, 0.05), nodata=-9999) as ds:
                ds.write(np.full((1, 2, 2), 100.0 + (y == 2023) * 50 + y % 5, "float32"))


def test_chirps_ratio_in_03_refuses_a_record_missing_its_first_years(tmp_path, monkeypatch):
    """F5.8: the rank range starts at the WMO normal's first year (1991), not at the first file found."""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("rf", Path(__file__).resolve().parents[1] / "03_runoff_flood.py")
    rf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rf)
    monkeypatch.setenv("RMS_DATA", str(tmp_path))
    box = [34.9, -0.2, 35.0, -0.1]
    _fake_chirps(tmp_path, range(1991, 2024))
    full = rf.chirps_ratio("nyando", box)
    assert full["of_years"] == 33 and full["rank_wettest"] == 1
    for m in (10, 11, 12):
        (tmp_path / "raw" / "nyando" / "chirps" / "monthly" / f"1991-{m:02d}.tif").unlink()
    with pytest.raises(ValueError, match=r"missing \[1991\]"):
        rf.chirps_ratio("nyando", box)


def test_fill_nearest_takes_the_closest_finite_cell():
    a = np.array([[10.0, np.nan, np.nan, 40.0]])
    f, bad = runoff.fill_nearest(a)
    np.testing.assert_array_equal(f, [[10.0, 10.0, 40.0, 40.0]])
    np.testing.assert_array_equal(bad, [[False, True, True, False]])
    g, _ = runoff.fill_nearest(np.array([1.0, 2.0]))
    np.testing.assert_array_equal(g, [1.0, 2.0])


def test_soil_gap_fill_is_on_for_nairobi_only():
    """Nyando's posted rasters were built without the fill; switching it on there changes them (no-rewrite rule)."""
    from pipeline.lib import config
    assert config.load("nairobi").get("soil_gap_fill") == "nearest"
    assert config.load("nyando").get("soil_gap_fill") is None


def test_03_soil_gate_fills_only_where_the_config_says_and_main_uses_it():
    """F8.2: test the gate where it acts (03), not only the config keys."""
    import importlib.util
    from pathlib import Path
    from pipeline.lib import config
    spec = importlib.util.spec_from_file_location("rf_soil", Path(__file__).resolve().parents[1] / "03_runoff_flood.py")
    rf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rf)
    clay = np.array([[20.0, np.nan], [30.0, 40.0]])
    sand = np.array([[50.0, np.nan], [40.0, 30.0]])
    c, s, gap = rf.soil_inputs(config.load("nyando"), clay.copy(), sand.copy())
    assert gap is None and np.isnan(c[0, 1]) and np.isnan(s[0, 1])               # Nyando: untouched
    np.testing.assert_array_equal(np.isnan(c), np.isnan(clay))
    c, s, gap = rf.soil_inputs(config.load("nairobi"), clay.copy(), sand.copy())
    assert gap is not None and gap[0, 1] and gap.sum() == 1 and np.isfinite(c).all() and np.isfinite(s).all()
    assert "soil_inputs(cfg, clay, sand)" in (Path(__file__).resolve().parents[1] / "03_runoff_flood.py").read_text()


NY = Path("/Users/mac/IGAD/data/processed/nyando/model/runoff_flood.json")


@pytest.mark.skipif(not NY.exists(), reason="no local Nyando model")
def test_real_nyando_run_had_no_soil_fill_and_keeps_its_cn_gaps():
    """F8.2 data side: the posted Nyando run recorded no fill and 1.82 % of its AOI without CN."""
    import json
    r = json.loads(NY.read_text())
    assert r.get("soil_gap_fill") is None and r["aoi_cn"]["nan_share"] == pytest.approx(0.0182, abs=1e-4)
