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


def _write_inputs(tmp: Path, mock: bool, carried_source: str = "mock", bbox=None):
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
        (sd / f"{k}.exposure.json").write_text(json.dumps({"year": 2026, "population": {"low": 1, "medium": 2, "high": 3},
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
