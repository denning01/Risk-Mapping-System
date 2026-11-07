"""Tests for pipeline/07_scenarios.py on tiny synthetic rasters with hand-computed answers."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import shape

spec = importlib.util.spec_from_file_location("scen", Path(__file__).resolve().parents[1] / "07_scenarios.py")
scen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scen)

CRS = "EPSG:32736"
RES = 30.0
TF = from_origin(722600.0, 9977880.0, RES, RES)  # ~35.0E, ~0.20S (Nyando), UTM 36S


def grid():
    """10x10 NaN grid; low block 2x2 (4 cells), medium block 2x3 (6), high block 1x2 (2) — not touching."""
    d = np.full((10, 10), np.nan, dtype="float32")
    d[0:2, 0:2] = 0.1           # low
    d[4:6, 4:7] = 0.5           # medium
    d[8, 8:10] = 2.0            # high
    return d


def test_classify_thresholds():
    d = np.array([np.nan, -1, 0.0, 0.01, 0.2999, 0.3, 1.0, 1.0001, 5], dtype="float32")
    assert scen.classify_risk(d).tolist() == [0, 0, 0, 1, 1, 2, 2, 3, 3]


def test_utm_epsg():
    assert scen.utm_epsg(36.85, -1.275) == 32737   # Nairobi
    assert scen.utm_epsg(35.075, -0.225) == 32736  # Nyando
    assert scen.utm_epsg(35.0, 0.1) == 32636


def test_three_classes_known_area():
    feats, st = scen.flood_features(grid(), TF, CRS, simplify_m=0)
    assert [f["properties"]["risk"] for f in feats] == ["low", "medium", "high"]
    assert st["cells_by_risk"] == {"low": 4, "medium": 6, "high": 2}
    assert st["flooded_area_m2"] == pytest.approx(12 * 900)
    assert st["polygon_area_m2"] == pytest.approx(12 * 900)       # second method: polygon area in UTM
    assert [f["properties"]["depth_m"] for f in feats] == [0.1, 0.5, 2.0]
    assert all(f["properties"]["arrival_h"] is None for f in feats)
    # each output polygon, projected back to UTM, has its class's area (to coordinate rounding)
    for f, n in zip(feats, (4, 6, 2)):
        assert scen.reproject(shape(f["geometry"]), "EPSG:4326", CRS).area == pytest.approx(n * 900, rel=0.02)
    # WGS84 lon/lat, near 35.0E 0.18S
    lon, lat = feats[0]["geometry"]["coordinates"][0][0]
    assert 34.9 < lon < 35.2 and -0.3 < lat < -0.1


def test_arrival_bins_split_a_class():
    d = grid()
    arr = np.full(d.shape, np.nan, dtype="float32")
    arr[4:6, 4] = 2.2   # medium block: one column bins to 2 h
    arr[4:6, 5:7] = 5.9  # the other two columns bin to 6 h
    feats, _ = scen.flood_features(d, TF, CRS, arrival=arr, arrival_bin_h=1.0, simplify_m=0)
    props = [(f["properties"]["risk"], f["properties"]["arrival_h"]) for f in feats]
    assert props == [("low", None), ("medium", 2.0), ("medium", 6.0), ("high", None)]


def test_dry_raster_gives_no_features():
    feats, st = scen.flood_features(np.full((5, 5), np.nan, dtype="float32"), TF, CRS)
    assert feats == [] and st["flooded_cells"] == 0


def test_rejects_geographic_crs():
    with pytest.raises(ValueError):
        scen.flood_features(grid(), from_origin(35, 0, 0.0003, 0.0003), "EPSG:4326")


def test_shelter_safety():
    to_wgs = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
    wet = to_wgs(722600 + 4.5 * RES, 9977880 - 4.5 * RES)    # inside the medium block
    dry = to_wgs(722600 + 9.5 * RES, 9977880 - 0.5 * RES)    # a dry corner cell
    far = to_wgs(800000, 9900000)                              # outside the raster
    sh = [{"id": i, "lon": p[0], "lat": p[1], "safe": None} for i, p in (("w", wet), ("d", dry), ("f", far))]
    out = {s["id"]: s for s in scen.shelters_safety(sh, grid(), TF, CRS)}
    assert (out["w"]["safe"], out["d"]["safe"], out["f"]["safe"]) == (False, True, False)  # outside = not safe
    assert out["f"]["_outside"] and not out["w"]["_outside"]


def test_shelter_safety_row_col_not_transposed():
    """F1.4: wet at (row 0, col 9), dry at its transpose (row 9, col 0) — a row/col swap flips both."""
    d = grid()
    d[0, 9] = 0.5
    assert np.isnan(d[9, 0])
    to_wgs = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
    wet = to_wgs(722600 + 9.5 * RES, 9977880 - 0.5 * RES)    # x = col 9, y = row 0
    dry = to_wgs(722600 + 0.5 * RES, 9977880 - 9.5 * RES)    # x = col 0, y = row 9
    sh = [{"id": i, "lon": p[0], "lat": p[1], "safe": None} for i, p in (("w", wet), ("d", dry))]
    out = {s["id"]: s["safe"] for s in scen.shelters_safety(sh, d, TF, CRS)}
    assert out == {"w": False, "d": True}


def test_raster_covers_bbox():
    to_wgs = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
    w, n = to_wgs(722600 + 1 * RES, 9977880 - 1 * RES)
    e, s_ = to_wgs(722600 + 9 * RES, 9977880 - 9 * RES)
    assert scen.raster_covers_bbox(TF, (10, 10), CRS, [w, s_, e, n])[0]
    ok, why = scen.raster_covers_bbox(TF, (10, 10), CRS, [w - 0.001, s_, e, n])   # ~111 m west of the grid
    assert not ok and "west_m" in why


@pytest.mark.parametrize("edge,dw,ds,de,dn", [
    ("west_m", -0.001, 0, 0, 0), ("east_m", 0, 0, 0.001, 0),
    ("south_m", 0, -0.001, 0, 0), ("north_m", 0, 0, 0, 0.001),
])
def test_raster_covers_bbox_each_edge(edge, dw, ds, de, dn):
    """F1.10: a bbox ~111 m past ANY one edge of the grid is refused, and that edge is named."""
    to_wgs = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
    w, n = to_wgs(722600 + 1 * RES, 9977880 - 1 * RES)
    e, s_ = to_wgs(722600 + 9 * RES, 9977880 - 9 * RES)
    ok, why = scen.raster_covers_bbox(TF, (10, 10), CRS, [w + dw, s_ + ds, e + de, n + dn])
    assert not ok and edge in why and sum(k in why for k in ("west_m", "east_m", "south_m", "north_m")) == 1


def test_raster_covers_bbox_refuses_south_up_and_rotated():
    """F1.10: a south-up grid (e > 0) or a rotated one is refused, not mis-measured."""
    from rasterio.transform import Affine  # F1.12: same class (affine.Affine), via a declared dependency
    to_wgs = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
    w, n = to_wgs(722600 + 1 * RES, 9977880 - 1 * RES)
    e, s_ = to_wgs(722600 + 9 * RES, 9977880 - 9 * RES)
    south_up = Affine(RES, 0, 722600.0, 0, RES, 9977880.0 - 10 * RES)   # same footprint, rows run north
    rotated = Affine(RES, 1.0, 722600.0, 1.0, -RES, 9977880.0)
    for tf in (south_up, rotated):
        ok, why = scen.raster_covers_bbox(tf, (10, 10), CRS, [w, s_, e, n])
        assert not ok and "north-up" in why


def _write_inputs(tmp: Path, mock: bool, carried_source: str = "mock", bbox=None, old_year: int = 2026):
    data, depth = tmp / "data", tmp / "depth"
    sd = data / "nyando" / "scenarios"
    sd.mkdir(parents=True)
    depth.mkdir()
    to_wgs0 = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
    if bbox is None:  # inside the 10x10 grid
        w, n = to_wgs0(722600 + 1 * RES, 9977880 - 1 * RES)
        e, s_ = to_wgs0(722600 + 9 * RES, 9977880 - 9 * RES)
        bbox = [w, s_, e, n]
    (data / "areas.json").write_text(json.dumps([{"id": "nyando", "bbox": bbox}]))
    prof = dict(driver="GTiff", width=10, height=10, count=1, dtype="float32", crs=CRS, transform=TF, nodata=np.nan)
    to_wgs = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
    wet = to_wgs(722600 + 4.5 * RES, 9977880 - 4.5 * RES)
    for k in scen.scenario_keys():
        with rasterio.open(depth / f"{k}_depth.tif", "w", **prof) as ds:
            ds.write(grid(), 1)
            if mock:
                ds.update_tags(MOCK="1")
        (sd / f"{k}.exposure.json").write_text(json.dumps({"year": old_year, "population": {"low": 1, "medium": 2, "high": 3},
                                                           "buildings": 4, "flooded_area_km2": 99, "roads_cut": [], "source": carried_source}))
        (sd / f"{k}.shelters.json").write_text(json.dumps([{"id": "s1", "name": "x", "type": "school", "lon": wet[0],
                                                            "lat": wet[1], "capacity": None, "safe": True}]))
        (sd / f"{k}.routes.json").write_text("[]")
    return data, depth


def test_write_end_to_end(tmp_path):
    data, depth = _write_inputs(tmp_path, mock=True)
    assert scen.main(["write", "--area", "nyando", "--depth-dir", str(depth), "--data-dir", str(data)]) == 0
    sd = data / "nyando" / "scenarios"
    for k in scen.scenario_keys():
        fc = json.loads((sd / f"{k}.geojson").read_text())
        assert len(fc["features"]) == 3
        exp = json.loads((sd / f"{k}.exposure.json").read_text())
        assert exp["flooded_area_km2"] == 0.01 and exp["source"] == "mock"   # 12 * 900 m2 = 0.0108 km2
        assert json.loads((sd / f"{k}.shelters.json").read_text())[0]["safe"] is False


def test_write_refuses_model_label_on_mock(tmp_path):
    data, depth = _write_inputs(tmp_path, mock=True)
    with pytest.raises(SystemExit):
        scen.main(["write", "--area", "nyando", "--depth-dir", str(depth), "--data-dir", str(data), "--source", "model"])


def test_write_refuses_model_label_on_mock_raster_even_if_carried_is_model(tmp_path):
    """F1.5: the raster's MOCK tag alone must block --source model."""
    data, depth = _write_inputs(tmp_path, mock=True, carried_source="model")
    with pytest.raises(SystemExit):
        scen.main(["write", "--area", "nyando", "--depth-dir", str(depth), "--data-dir", str(data), "--source", "model"])


def test_write_model_allowed_when_all_inputs_real(tmp_path):
    data, depth = _write_inputs(tmp_path, mock=False, carried_source="model")
    assert scen.main(["write", "--area", "nyando", "--depth-dir", str(depth), "--data-dir", str(data), "--source", "model"]) == 0


def test_write_fails_if_raster_does_not_cover_bbox(tmp_path):
    """F2.2: a raster narrower than areas.json's bbox fails before anything is written."""
    data, depth = _write_inputs(tmp_path, mock=True, bbox=[34.0, -0.3, 35.5, 0.0])
    before = (data / "nyando" / "scenarios" / "50_normal.exposure.json").read_text()
    assert scen.main(["write", "--area", "nyando", "--depth-dir", str(depth), "--data-dir", str(data)]) == 1
    assert not (data / "nyando" / "scenarios" / "50_normal.geojson").exists()
    assert (data / "nyando" / "scenarios" / "50_normal.exposure.json").read_text() == before


def test_standin_tags_mock_and_roundtrips(tmp_path):
    """F1.7: every stand-in raster carries MOCK=1, and the rasterised area matches the mock polygon."""
    data, out = tmp_path / "data", tmp_path / "out"
    sd = data / "nyando" / "scenarios"
    sd.mkdir(parents=True)
    bbox = [35.0, -0.21, 35.01, -0.2]
    (data / "areas.json").write_text(json.dumps([{"id": "nyando", "bbox": bbox}]))
    sq = [[[35.002, -0.208], [35.006, -0.208], [35.006, -0.204], [35.002, -0.204], [35.002, -0.208]]]
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": sq},
                                                      "properties": {"risk": "medium", "depth_m": 0.5, "arrival_h": 3}}]}
    for k in scen.scenario_keys():
        (sd / f"{k}.geojson").write_text(json.dumps(fc))
    assert scen.main(["standin", "--area", "nyando", "--data-dir", str(data), "--out-dir", str(out)]) == 0
    tifs = sorted(out.glob("*.tif"))
    assert len(tifs) == 20
    for t in tifs:
        with rasterio.open(t) as ds:
            assert ds.tags().get("MOCK") == "1", t.name
            assert ds.crs.to_epsg() == 32736
            assert scen.raster_covers_bbox(ds.transform, (ds.height, ds.width), ds.crs, bbox)[0]
    with rasterio.open(out / "50_normal_depth.tif") as ds:
        wet_m2 = np.isfinite(ds.read(1)).sum() * 900
    poly_m2 = scen.reproject(shape(fc["features"][0]["geometry"]), "EPSG:4326", "EPSG:32736").area
    assert wet_m2 == pytest.approx(poly_m2, rel=0.05)


def test_write_fails_on_missing_raster(tmp_path):
    data, depth = _write_inputs(tmp_path, mock=True)
    (depth / "250_elnino_depth.tif").unlink()
    assert scen.main(["write", "--area", "nyando", "--depth-dir", str(depth), "--data-dir", str(data)]) == 1


# ---- AOI restriction: a model raster may cover a larger export box than the area ----
def test_aoi_mask_selects_cell_centres_inside_bbox():
    to_wgs = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
    w, n = to_wgs(722600 + 2 * RES, 9977880 - 1 * RES)       # bbox edges on cell boundaries: cols 2..6, rows 1..7
    e, s_ = to_wgs(722600 + 7 * RES, 9977880 - 8 * RES)
    m = scen.aoi_mask((10, 10), TF, CRS, [w, s_, e, n])
    rows, cols = np.nonzero(m)
    assert m.sum() == 5 * 7 and (rows.min(), rows.max(), cols.min(), cols.max()) == (1, 7, 2, 6)


def test_write_draws_and_counts_only_inside_the_area(tmp_path):
    """The default test bbox spans cells 1..8, so the low block's (0,0),(0,1),(1,0) and the high cell (8,9) are
    outside: 12 wet cells -> 8 inside, and no polygon may reach the raster's own west/north edge."""
    data, depth = _write_inputs(tmp_path, mock=True)
    bbox = json.loads((data / "areas.json").read_text())[0]["bbox"]
    assert scen.main(["write", "--area", "nyando", "--depth-dir", str(depth), "--data-dir", str(data)]) == 0
    from shapely.geometry import box
    # a cell is kept when its CENTRE is inside, so its edge may stick out by half a cell (15 m), plus 1e-5 deg rounding;
    # an unmasked edge cell sticks out a whole cell (30 m ~ 2.7e-4 deg) and fails
    allowed = box(*bbox).buffer(0.5 * RES / 111_000 + 1.5e-5)
    for k in scen.scenario_keys():
        fc = json.loads((data / "nyando" / "scenarios" / f"{k}.geojson").read_text())
        for f in fc["features"]:
            assert allowed.contains(shape(f["geometry"])), (k, f["properties"])
    d = np.where(scen.aoi_mask((10, 10), TF, CRS, bbox), grid(), np.nan)
    assert scen.flood_features(d, TF, CRS)[1]["flooded_cells"] == 8


# ---- snapshot: a model hand-off is frozen and sha256-verified before use ----
def _handoff(tmp: Path, mutate=None, commit="abc1234"):
    import hashlib
    md = tmp / "model" / "scenarios"
    md.mkdir(parents=True)
    rows = []
    prof = dict(driver="GTiff", width=10, height=10, count=1, dtype="float32", crs=CRS, transform=TF, nodata=np.nan)
    for k in scen.scenario_keys():
        f = md / f"{k}_depth.tif"
        with rasterio.open(f, "w", **prof) as ds:
            ds.write(grid(), 1)
            ds.update_tags(git_commit=commit)
        b = f.read_bytes()
        rows.append(f"| `scenarios/{k}_depth.tif` | 0.01 | 3.0 | {len(b):,} | `{hashlib.sha256(b).hexdigest()[:16]}…` |")
    hand = md.parent / "hand.tif"
    with rasterio.open(hand, "w", **prof) as ds:
        ds.write(grid(), 1)
    hb = hand.read_bytes()
    rows.append(f"| `hand.tif` | – | 3.0 | {len(hb):,} | `{hashlib.sha256(hb).hexdigest()}` |")   # full 64-hex form
    h = tmp / "flood-nyando.md"
    h.write_text("# Hand-off\n\n| file | flooded km² | margin px | bytes | sha256 |\n|---|---|---|---|---|\n" + "\n".join(rows) + "\n")
    if mutate:
        mutate(md)
    return md.parent, h


def test_parse_handoff_reads_the_table():
    t = scen.parse_handoff("| `scenarios/50_normal_depth.tif` | 99.53 | 371.8 | 900,470 | `5b981f986ed4874c…` |\n"
                           "| `hand.tif` | – | 371.8 | 40,041,784 | `f1b767794edddbe2…` |")
    assert t["scenarios/50_normal_depth.tif"] == {"bytes": 900470, "sha_prefix": "5b981f986ed4874c", "km2": 99.53}
    assert t["hand.tif"]["km2"] is None


def test_snapshot_copies_and_names_by_commit(tmp_path):
    model, h = _handoff(tmp_path)
    d = scen.snapshot(model, h, tmp_path / "snap")
    assert d.name == "abc1234" and len(list(d.glob("*_depth.tif"))) == 10     # 5 rain x 2 enso
    assert (d / "hand.tif").exists() and "hand.tif" in json.loads((d / "snapshot.json").read_text())["sha256"]
    assert json.loads((d / "snapshot.json").read_text())["git_commit"] == "abc1234"


def test_snapshot_refuses_a_file_changed_after_the_handoff(tmp_path):
    def rewrite(md):
        with rasterio.open(md / "250_elnino_depth.tif", "r+") as ds:
            ds.write(np.where(np.isnan(grid()), 0.7, grid()).astype("float32"), 1)
    model, h = _handoff(tmp_path, mutate=rewrite)
    with pytest.raises(ValueError, match="250_elnino_depth.tif"):
        scen.snapshot(model, h, tmp_path / "snap")
    assert [p.name for p in (tmp_path / "snap").iterdir()] == []          # nothing left behind


def test_write_flags_km2_that_disagree_with_the_handoff(tmp_path, capsys):
    data, depth = _write_inputs(tmp_path, mock=True)
    km2 = {f"scenarios/{k}_depth.tif": 0.01 for k in scen.scenario_keys()}
    km2["scenarios/100_elnino_depth.tif"] = 5.0
    (depth / "snapshot.json").write_text(json.dumps({"handoff_km2": km2}))
    assert scen.main(["write", "--area", "nyando", "--depth-dir", str(depth), "--data-dir", str(data)]) == 0
    out = capsys.readouterr().out
    assert "100_elnino: flooded" in out and "5.0 km2" in out and "50_normal: flooded" not in out


# ---- E-04: write puts the RULED population number (W2 weight, option B factors) into exposure.json ----
def _pop_inputs(rms: Path, low_building: bool = False, county_factors: bool = True):
    from rasterio.transform import from_origin as fo
    ex = rms / "processed" / "nyando" / "exposure"
    ex.mkdir(parents=True)
    to_wgs = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
    w, n = to_wgs(722600 - 300, 9977880 + 300)
    prof = dict(driver="GTiff", width=4, height=4, count=1, crs="EPSG:4326", transform=fo(w, n, 0.003, 0.003))
    with rasterio.open(ex / "worldpop_2020_aoi.tif", "w", dtype="float32", **prof) as d:
        d.write(np.full((4, 4), 100.0, dtype="float32"), 1)
    with rasterio.open(ex / "county_id_aoi.tif", "w", dtype="uint8", **prof) as d:
        d.write(np.ones((4, 4), dtype="uint8"), 1)
    pts = [to_wgs(722600 + 4.5 * RES, 9977880 - 4.5 * RES),       # in the wet medium block, 30 m2
           to_wgs(722600 + 7.5 * RES, 9977880 - 2.5 * RES)]       # dry cell inside the AOI, 90 m2
    areas = [30.0, 90.0]
    if low_building:                                              # LOW cell (depth 0.1 m) inside the AOI, 60 m2
        pts.append(to_wgs(722600 + 1.5 * RES, 9977880 - 1.5 * RES))
        areas.append(60.0)
    n = len(pts)
    np.savez(ex / "open_buildings_aoi.npz", lon=np.array([p[0] for p in pts]), lat=np.array([p[1] for p in pts]),
             area_m2=np.array(areas), conf=np.full(n, 0.9), thr80=np.full(n, 0.7), thr85=np.full(n, 0.7),
             thr90=np.full(n, 0.7))
    county = {"id": 1, "worldpop_aoi_2020": 1000.0}
    if county_factors:
        county["factors"] = {"low": 1.0, "medium": 2.0, "high": 4.0}
    (ex / "population_manifest.json").write_text(json.dumps({
        "unit": "t", "year": 2026, "projection": {}, "modes": {"A": "a", "B": "b"},
        "factors_A": {"low": 3.0, "medium": 3.0, "high": 3.0},
        "counties": [county]}))


def test_write_population_uses_the_ruled_weight_and_mode(tmp_path, monkeypatch):
    data, depth = _write_inputs(tmp_path, mock=True)
    _pop_inputs(tmp_path / "rms")
    monkeypatch.setenv("RMS_DATA", str(tmp_path / "rms"))
    args = ["write", "--area", "nyando", "--depth-dir", str(depth), "--data-dir", str(data), "--population",
            "--population-mode", "B", "--population-weight", "buildings", "--buildings"]
    assert scen.main(args) == 0
    exp = json.loads((data / "nyando" / "scenarios" / "50_normal.exposure.json").read_text())
    # W2/B: 1000 people x factor_B x (30 / 120 wet footprint share) ; A would give 750 for medium
    assert exp["population"] == {"low": 250, "medium": 500, "high": 1000} and exp["buildings"] == 1
    assert exp["year"] == 2026 and exp["source"] == "mock"
    assert scen.main(args[:7] + ["--population", "--buildings"]) == 1       # no mode/weight -> refused


def test_snapshot_refuses_a_changed_hand_tif(tmp_path):
    def rewrite(md):
        with rasterio.open(md.parent / "hand.tif", "r+") as ds:
            ds.write(np.full((10, 10), 9.0, dtype="float32"), 1)
    model, h = _handoff(tmp_path, mutate=rewrite)
    with pytest.raises(ValueError, match="hand.tif"):
        scen.snapshot(model, h, tmp_path / "snap")


def _add_row(model, h, name, value):
    import hashlib
    f = model / name
    prof = dict(driver="GTiff", width=10, height=10, count=1, dtype="float32", crs=CRS, transform=TF, nodata=np.nan)
    with rasterio.open(f, "w", **prof) as ds:
        ds.write(np.full((10, 10), value, dtype="float32"), 1)
    b = f.read_bytes()
    h.write_text(h.read_text() + f"| `{name}` | – | 3.0 | {len(b):,} | `{hashlib.sha256(b).hexdigest()}` |\n")


def test_snapshot_accepts_a_document_only_repost_that_adds_a_row(tmp_path):
    model, h = _handoff(tmp_path)
    d = scen.snapshot(model, h, tmp_path / "snap")
    _add_row(model, h, "slope.tif", 2.0)                     # the 14:21 re-post: slope.tif row added, nothing else
    d2 = scen.snapshot(model, h, tmp_path / "snap")
    assert d2 == d and (d / "slope.tif").exists()
    snap = json.loads((d / "snapshot.json").read_text())
    assert "slope.tif" in snap["sha256"] and len(snap["sha256"]) == 12
    assert "slope.tif" in (d / "handoff.md").read_text()


def test_snapshot_refuses_a_repost_that_changes_an_existing_file(tmp_path):
    model, h = _handoff(tmp_path)
    scen.snapshot(model, h, tmp_path / "snap")
    import hashlib
    with rasterio.open(model / "hand.tif", "r+") as ds:          # hand.tif rewritten, table updated to match
        ds.write(np.full((10, 10), 7.0, dtype="float32"), 1)
    b = (model / "hand.tif").read_bytes()
    lines = [l if "`hand.tif`" not in l else f"| `hand.tif` | – | 3.0 | {len(b):,} | `{hashlib.sha256(b).hexdigest()}` |"
             for l in h.read_text().splitlines()]
    h.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="different contents"):
        scen.snapshot(model, h, tmp_path / "snap")


def test_written_area_is_measured_after_simplification():
    """A 10x10-cell block missing one corner cell: simplifying at 25 m cuts the notch's corner (30/sqrt(2) = 21 m off the
    chord), so the DRAWN area grows by half a cell. written_area_m2 must report the drawn polygon, not the
    pre-simplification one (the pre-simplification number hid a +0.12 % change on Nyando at 20 m)."""
    d = np.full((10, 10), 0.5, dtype="float32")
    d[0, 9] = np.nan
    _, st0 = scen.flood_features(d, TF, CRS, simplify_m=0)
    _, st = scen.flood_features(d, TF, CRS, simplify_m=25)
    assert st0["written_area_m2"] == pytest.approx(99 * 900) == st["polygon_area_m2"]
    assert st["written_area_m2"] == pytest.approx(99 * 900 + 450)


# ---- R5 audit F5.5 / F5.7 / F5.8 ----
_POP_ARGS = ["--population", "--population-mode", "B", "--population-weight", "buildings", "--buildings"]


def _run_pop(tmp_path, monkeypatch, **kw):
    old_year = kw.pop("old_year", 2026)
    data, depth = _write_inputs(tmp_path, mock=True, old_year=old_year)
    _pop_inputs(tmp_path / "rms", **kw)
    monkeypatch.setenv("RMS_DATA", str(tmp_path / "rms"))
    assert scen.main(["write", "--area", "nyando", "--depth-dir", str(depth), "--data-dir", str(data)] + _POP_ARGS) == 0
    return json.loads((data / "nyando" / "scenarios" / "50_normal.exposure.json").read_text())


def test_exposed_includes_low_class_water(tmp_path, monkeypatch):
    """F5.5: "exposed" = any depth > 0, LOW class (0.1 m) included. A building only in a 0.1 m cell is counted, and its
    footprint carries people: wet share (30 + 60) / 180 = 0.5 -> medium 1000 x 2 x 0.5 = 1000. Counting only depth
    > 0.3 m would give 1 building and 333 people."""
    exp = _run_pop(tmp_path, monkeypatch, low_building=True)
    assert exp["buildings"] == 2
    assert exp["population"] == {"low": 500, "medium": 1000, "high": 2000}


def test_written_year_comes_from_the_manifest_not_the_old_file(tmp_path, monkeypatch):
    """F5.7: the carried file says 2020; the manifest's projection year (2026) must be written."""
    exp = _run_pop(tmp_path, monkeypatch, old_year=2020)
    assert exp["year"] == 2026


def test_county_without_knbs_figures_uses_the_unit_factor_in_w2(tmp_path, monkeypatch):
    """F5.8: a county with no KNBS figures falls back to A's factor (3.0) in mode B: 1000 x 3 x 30/120 = 750."""
    exp = _run_pop(tmp_path, monkeypatch, county_factors=False)
    assert exp["population"] == {"low": 750, "medium": 750, "high": 750}


# ---- E-10: buildings layer (pending Person B's schema; never written under web/) ----
def test_buildings_points_geojson_classes_from_unrounded_depth_and_floor():
    fc = scen.buildings_points_geojson([35.123456, 35.2], [-0.1234567, -0.3], [0.2999, 0.004])
    p = [f["properties"] for f in fc["features"]]
    # 0.2999 rounds to 0.30 but is LOW (under 0.3 m); 0.004 m is wet, so it reads 0.01, never 0.00
    assert p == [{"depth_m": 0.3, "depth_class": "low"}, {"depth_m": 0.01, "depth_class": "low"}]
    assert fc["features"][0]["geometry"] == {"type": "Point", "coordinates": [35.12346, -0.12346]}
    cls = [f["properties"]["depth_class"] for f in scen.buildings_points_geojson([0] * 4, [0] * 4, [0.3, 1.0, 1.0001, 5])["features"]]
    assert cls == ["medium", "medium", "high", "high"]
    with pytest.raises(ValueError):
        scen.buildings_points_geojson([0], [0], [0.0])
    with pytest.raises(ValueError):
        scen.buildings_points_geojson([0], [0], [np.nan])


def _buildings_npz(rms: Path, cells_conf):
    to = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
    pts = [to(722600 + (c + 0.5) * RES, 9977880 - (r + 0.5) * RES) for (r, c), _ in cells_conf]
    d = rms / "processed" / "nyando" / "exposure"
    d.mkdir(parents=True)
    n = len(pts)
    np.savez(d / "open_buildings_aoi.npz", lon=np.array([p[0] for p in pts]), lat=np.array([p[1] for p in pts]),
             area_m2=np.full(n, 50.0), conf=np.array([c for _, c in cells_conf]), thr80=np.full(n, 0.67),
             thr85=np.full(n, 0.716), thr90=np.full(n, 0.77))


def test_write_buildings_layer_matches_the_counter_and_masks_the_aoi(tmp_path, monkeypatch):
    """grid(): medium 0.5 m at rows 4-5 x cols 4-6, high 2.0 m at row 8 x cols 8-9, low 0.1 m at rows 0-1 x cols 0-1.
    The AOI bbox spans cells 1..9, so the low cell (0, 0) is OUTSIDE the area: a building there is in neither the
    counter nor the layer. Expected layer: (4, 4) medium 0.5, (5, 6) medium 0.5, (8, 8) high 2.0."""
    rms = tmp_path / "rms"
    monkeypatch.setenv("RMS_DATA", str(rms))
    _buildings_npz(rms, [((4, 4), 0.9), ((5, 6), 0.9), ((8, 8), 0.9), ((4, 5), 0.5),   # 0.5 < thr85: not counted
                         ((0, 0), 0.9), ((2, 2), 0.9)])                                   # outside AOI / dry
    data, depth = _write_inputs(tmp_path, mock=True)
    out = rms / "processed" / "nyando" / "exposure" / "buildings_points" / "t"
    assert scen.main(["write", "--area", "nyando", "--depth-dir", str(depth), "--data-dir", str(data),
                      "--buildings", "--buildings-points-dir", str(out)]) == 0
    for k in scen.scenario_keys():
        exp = json.loads((data / "nyando" / "scenarios" / f"{k}.exposure.json").read_text())
        fc = json.loads((out / f"{k}.buildings.geojson").read_text())
        assert exp["buildings"] == len(fc["features"]) == 3
        assert sorted((f["properties"]["depth_class"], f["properties"]["depth_m"]) for f in fc["features"]) == \
            [("high", 2.0), ("medium", 0.5), ("medium", 0.5)]
    assert not list((data / "nyando" / "scenarios").glob("*.buildings.geojson"))   # nothing reaches the app's data


def test_write_buildings_layer_refused_inside_web_or_data_dir_and_without_buildings(tmp_path, monkeypatch):
    rms = tmp_path / "rms"
    monkeypatch.setenv("RMS_DATA", str(rms))
    _buildings_npz(rms, [((4, 4), 0.9)])
    data, depth = _write_inputs(tmp_path, mock=True)
    before = (data / "nyando" / "scenarios" / "50_normal.exposure.json").read_text()
    base = ["write", "--area", "nyando", "--depth-dir", str(depth), "--data-dir", str(data)]
    monkeypatch.setattr(scen, "REPO", tmp_path / "repo")   # a fake repo: a broken guard can never write the real web/
    web_dir = scen.REPO / "web" / "public" / "data" / "nyando" / "scenarios"
    assert scen.main(base + ["--buildings", "--buildings-points-dir", str(web_dir)]) == 1
    assert scen.main(base + ["--buildings", "--buildings-points-dir", str(data / "nyando" / "x")]) == 1
    assert scen.main(base + ["--buildings-points-dir", str(tmp_path / "ok")]) == 1          # needs --buildings
    assert not list(web_dir.glob("*.buildings.geojson")) and not (tmp_path / "ok").exists()
    assert (data / "nyando" / "scenarios" / "50_normal.exposure.json").read_text() == before  # nothing written
