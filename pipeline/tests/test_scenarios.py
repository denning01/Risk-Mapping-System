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
    assert (out["w"]["safe"], out["d"]["safe"], out["f"]["safe"]) == (False, True, True)
    assert out["f"]["_outside"] and not out["w"]["_outside"]


def _write_inputs(tmp: Path, mock: bool):
    data, depth = tmp / "data", tmp / "depth"
    sd = data / "nyando" / "scenarios"
    sd.mkdir(parents=True)
    depth.mkdir()
    prof = dict(driver="GTiff", width=10, height=10, count=1, dtype="float32", crs=CRS, transform=TF, nodata=np.nan)
    to_wgs = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
    wet = to_wgs(722600 + 4.5 * RES, 9977880 - 4.5 * RES)
    for k in scen.scenario_keys():
        with rasterio.open(depth / f"{k}_depth.tif", "w", **prof) as ds:
            ds.write(grid(), 1)
            if mock:
                ds.update_tags(MOCK="1")
        (sd / f"{k}.exposure.json").write_text(json.dumps({"year": 2026, "population": {"low": 1, "medium": 2, "high": 3},
                                                           "buildings": 4, "flooded_area_km2": 99, "roads_cut": [], "source": "mock"}))
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


def test_write_fails_on_missing_raster(tmp_path):
    data, depth = _write_inputs(tmp_path, mock=True)
    (depth / "250_elnino_depth.tif").unlink()
    assert scen.main(["write", "--area", "nyando", "--depth-dir", str(depth), "--data-dir", str(data)]) == 1
