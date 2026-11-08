"""E-20: arrival bands in the flood GeoJSON (07), the arrival snapshot, and who it affects (11_arrival_exposure)."""
import importlib.util
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import shape

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))


def _load(name, file):
    s = importlib.util.spec_from_file_location(name, HERE / file)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


scen = _load("scen_a", "07_scenarios.py")
ax = _load("ax11", "11_arrival_exposure.py")

CRS = "EPSG:32736"
TF = from_origin(722600.0, 9977880.0, 30.0, 30.0)


def test_classify_arrival_band_edges():
    h = np.array([0.0, 0.5, 0.999, 1.0, 2.99, 3.0, 6.0, 6.01, np.nan])
    assert scen.classify_arrival_band(h).tolist() == [0, 0, 0, 1, 1, 2, 2, 3, -1]


def test_flood_features_split_by_arrival_band_with_the_feature_median():
    """One medium-depth block of 4 x 6 cells; arrival (fast bound) columns 0-1: 0.0 and 0.4 h, 2-3: 2.0 h, 4: 4.5 h,
    5: 7.0 h. Features: (medium band 0.5-1.0) x 4 arrival bands; arrival_h = the median hours of each feature's cells
    (<1 h: median of 0.0 and 0.4 x4 each = 0.2), no two features overlap, cells conserved."""
    d = np.full((8, 8), np.nan, dtype="float32")
    d[1:5, 1:7] = 0.6
    arr = np.full((8, 8), np.nan)
    arr[1:5, 1] = 0.0; arr[1:5, 2] = 0.4; arr[1:5, 3:5] = 2.0; arr[1:5, 5] = 4.5; arr[1:5, 6] = 7.0
    feats, st = scen.flood_features(d, TF, CRS, arr, simplify_m=0, arrival_bands=True)
    got = sorted((f["properties"]["risk"], f["properties"]["depth_m"], f["properties"]["arrival_h"]) for f in feats)
    assert got == [("medium", 0.6, 0.2), ("medium", 0.6, 2.0), ("medium", 0.6, 4.5), ("medium", 0.6, 7.0)]
    area = {f["properties"]["arrival_h"]: scen.reproject(shape(f["geometry"]), "EPSG:4326", CRS).area for f in feats}
    assert area[0.2] == pytest.approx(8 * 900, abs=300) and area[2.0] == pytest.approx(8 * 900, abs=300)
    for a, b in itertools.combinations([shape(f["geometry"]) for f in feats], 2):
        assert a.intersection(b).area == 0
    assert st["flooded_cells"] == 24


def test_arrival_display_h_rounds_to_a_tenth_with_a_floor_of_a_tenth():
    """RULING E-20 Q2: never 0 h, never minute-precision: 0.0 / 0.01 / 0.04 / 0.149 -> 0.1; 0.16 -> 0.2; 2.46 -> 2.5."""
    assert [scen.arrival_display_h(x) for x in (0.0, 0.01, 0.04, 0.149, 0.16, 2.46, 7.0)] == [0.1, 0.1, 0.1, 0.1, 0.2, 2.5, 7.0]


def test_flood_features_low_median_is_floored_to_a_tenth():
    d = np.full((6, 6), np.nan, dtype="float32"); d[1:3, 1:3] = 0.6
    arr = np.full((6, 6), 0.02)
    feats, _ = scen.flood_features(d, TF, CRS, arr, simplify_m=0, arrival_bands=True)
    assert [f["properties"]["arrival_h"] for f in feats] == [0.1]


def test_without_arrival_bands_the_old_bin_rule_is_unchanged():
    d = np.full((6, 6), np.nan, dtype="float32"); d[1:3, 1:3] = 0.2
    arr = np.full((6, 6), 2.6)
    feats, _ = scen.flood_features(d, TF, CRS, arr, arrival_bin_h=1.0, simplify_m=0)
    assert [f["properties"]["arrival_h"] for f in feats] == [3.0]


def _write(path, a, tf=TF):
    with rasterio.open(path, "w", driver="GTiff", height=a.shape[0], width=a.shape[1], count=1, dtype="float32",
                       crs=CRS, transform=tf) as ds:
        ds.write(a.astype("float32"), 1)


def _handoff(slow, fast, commit="abc1234"):
    sh = scen._sha256
    return (f"Written by pipeline/10_arrival.py at commit {commit} (dirty: False).\n"
            f"- **File:** `$RMS_DATA/processed/x/model/arrival_h.tif` ({slow.stat().st_size:,} B, sha256 `{sh(slow)}`)\n"
            f"- **`arrival_h_fast.tif`, the FAST bound = the app HEADLINE**:\n  arrival_h / F. "
            f"{fast.stat().st_size:,} B, sha256 `{sh(fast)}`. Same grid.\n")


def test_snapshot_arrival_copies_verifies_full_sha_and_grid(tmp_path):
    model, snap = tmp_path / "model", tmp_path / "snap"
    model.mkdir(); snap.mkdir()
    a = np.arange(16, dtype="float32").reshape(4, 4)
    _write(model / "arrival_h.tif", a); _write(model / "arrival_h_fast.tif", a / 2.44)
    _write(snap / f"{scen.scenario_keys()[0]}_depth.tif", np.zeros((4, 4)))
    ho = tmp_path / "h.md"; ho.write_text(_handoff(model / "arrival_h.tif", model / "arrival_h_fast.tif"))
    d = scen.snapshot_arrival(model, ho, snap)
    assert d == snap / "arrival" / "abc1234"
    fast, slow = scen.read_arrival_snapshot(d, (TF, CRS, (4, 4)))
    assert np.allclose(slow, a) and np.allclose(fast, a / 2.44, atol=1e-5)
    # a model file that changed after the hand-off: refused, nothing kept
    _write(model / "arrival_h_fast.tif", a / 2.0)
    ho2 = tmp_path / "h2.md"; ho2.write_text(ho.read_text().replace("abc1234", "def5678"))
    with pytest.raises(ValueError, match="hand-off says"):
        scen.snapshot_arrival(model, ho2, snap)
    assert not (snap / "arrival" / "def5678").exists()
    # a different grid: refused
    _write(model / "arrival_h_fast.tif", a / 2.44, tf=from_origin(0, 0, 30, 30))
    ho3 = tmp_path / "h3.md"; ho3.write_text(_handoff(model / "arrival_h.tif", model / "arrival_h_fast.tif", "fff0000"))
    with pytest.raises(ValueError, match="grid differs"):
        scen.snapshot_arrival(model, ho3, snap)
    # a tampered snapshot file is refused on read
    (d / "arrival_h.tif").write_bytes((d / "arrival_h.tif").read_bytes()[:-1] + b"\x01")
    with pytest.raises(ValueError, match="sha256 differs"):
        scen.read_arrival_snapshot(d, (TF, CRS, (4, 4)))


def test_parse_arrival_handoff_needs_both_files_and_the_commit():
    with pytest.raises(ValueError, match="arrival_h_fast.tif"):
        scen.parse_arrival_handoff("at commit abc1234\n- `$RMS_DATA/processed/x/model/arrival_h.tif` (1 B, sha256 `"
                                   + "0" * 64 + "`)")


def test_band_table_people_sum_to_targets_and_buildings_and_area_by_band():
    """Cells: band 0 x3 wet, band 1 x1 wet, band 3 x1 dry, one NaN wet cell (unknown). Buildings: two in band 0 (0.4
    people each), one in band 1 (1.3), one dry (ignored), one on the NaN cell (0.5). Medium target 3 (sum 2.6 -> 3)."""
    cell_band = np.array([0, 0, 0, 1, 3, -1]); wet = np.array([1, 1, 1, 1, 0, 1], bool)
    b_band = np.array([0, 0, 1, 3, -1]); b_wet = np.array([1, 1, 1, 0, 1], bool)
    ppl = np.array([[0.4] * 3, [0.4] * 3, [1.3] * 3, [9.0] * 3, [0.5] * 3])
    t = ax.band_table(cell_band, wet, 900.0, b_band, b_wet, ppl, {"low": 2, "medium": 3, "high": 3})
    assert [t[n]["buildings"] for n in ("<1", "1-3", "3-6", ">6", "unknown")] == [2, 1, 0, 0, 1]
    assert t["<1"]["flooded_km2"] == 0.0027 and t["unknown"]["flooded_km2"] == 0.0009
    for s, tot in (("low", 2), ("medium", 3), ("high", 3)):
        assert sum(t[n][f"people_{s}"] for n in t) == tot
    assert t["1-3"]["people_medium"] == 1 and t["<1"]["people_medium"] == 1     # 0.8 -> 1, 1.3 -> 1, 0.5 -> 1 (3)
    t2 = ax.band_table(cell_band[:5], wet[:5], 900.0, b_band[:4], b_wet[:4], ppl[:4], {"low": 2, "medium": 2, "high": 2})
    assert "unknown" not in t2


def test_arrival_h_is_the_median_not_the_mean():
    """F-A3: one '<1' feature whose cells are 0.1 h (x2 columns) and 0.9 h (x1): median 0.1, mean 0.37 -> 0.4."""
    d = np.full((6, 6), np.nan, dtype="float32"); d[1:5, 1:4] = 0.6
    arr = np.full((6, 6), 0.1); arr[:, 3] = 0.9
    feats, _ = scen.flood_features(d, TF, CRS, arr, simplify_m=0, arrival_bands=True)
    assert [f["properties"]["arrival_h"] for f in feats] == [0.1]


def test_within_a_depth_band_the_earlier_arrival_wins_contested_faces():
    """F-A14: two same-depth features (<1 h left, >6 h right) with a jagged border, simplified at 60 m so their drawn
    outlines overlap. The earlier arrival is assigned last and keeps every face it contains: its drawn area equals its
    area drawn alone (within 0.01 %); with the order reversed it loses ~0.9 % to the later one."""
    tf = from_origin(722600.0, 9977880.0, 30.0, 30.0)
    rng = np.random.default_rng(3)
    d = np.full((40, 40), np.nan, dtype="float32"); d[2:38, 2:38] = 0.6
    arr = np.full((40, 40), 7.0)
    for i in range(40):
        arr[i, :20 + int(rng.integers(-4, 5))] = 0.3
    area = lambda fs: {f["properties"]["arrival_h"]: scen.reproject(shape(f["geometry"]), "EPSG:4326", CRS).area for f in fs}
    both = area(scen.flood_features(d, tf, CRS, arr, simplify_m=60, arrival_bands=True)[0])
    alone = area(scen.flood_features(np.where(arr < 1, d, np.nan), tf, CRS, arr, simplify_m=60, arrival_bands=True)[0])
    assert set(both) == {0.3, 7.0}
    assert both[0.3] == pytest.approx(alone[0.3], rel=1e-4)
