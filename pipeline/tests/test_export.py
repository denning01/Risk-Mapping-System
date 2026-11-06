"""M-02: tile naming for the no-EE downloads, export box rules, and the raster checks."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from pipeline.lib import config, fetch

_spec = importlib.util.spec_from_file_location(
    "ee_export", Path(__file__).resolve().parents[1] / "01_ee_export.py")
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)


def names(urls):
    return sorted(u.rsplit("/", 1)[1] for u in urls)


def test_glo30_tiles_named_by_south_west_corner():
    # a 1x1 deg tile named S01 covers lat -1..0; N00 covers 0..1
    assert names(ex.glo30_urls([34.7, -0.65, 35.9, 0.15])) == sorted(
        f"Copernicus_DSM_COG_10_{a}_00_E{b}_00_DEM.tif" for a in ("S01", "N00") for b in ("034", "035"))
    assert names(ex.glo30_urls([36.78, -1.33, 36.92, -1.22])) == ["Copernicus_DSM_COG_10_S02_00_E036_00_DEM.tif"]


def test_worldcover_tiles_3deg_south_west_corner():
    assert names(ex.worldcover_urls([34.7, -0.65, 35.9, 0.15])) == [
        "ESA_WorldCover_10m_2021_v200_N00E033_Map.tif", "ESA_WorldCover_10m_2021_v200_S03E033_Map.tif"]
    assert names(ex.worldcover_urls([36.78, -1.33, 36.92, -1.22])) == ["ESA_WorldCover_10m_2021_v200_S03E036_Map.tif"]


def test_jrc_tiles_10deg_top_left_corner():
    assert names(ex.jrc_urls([34.7, -0.65, 35.9, 0.15])) == [
        "occurrence_30E_0Nv1_4_2021.tif", "occurrence_30E_10Nv1_4_2021.tif"]
    assert names(ex.jrc_urls([36.78, -1.33, 36.92, -1.22])) == ["occurrence_30E_0Nv1_4_2021.tif"]


def test_nyando_export_box_contains_aoi_and_ruled_west_edge():
    cfg = config.load("nyando")
    w, s, e, n = cfg["export_bbox"]
    assert w <= 34.80 and s <= -0.45 and e >= 35.30 and n >= 0.00   # operator ruling 2026-11-05


def test_export_box_must_contain_bbox(tmp_path):
    (tmp_path / "x.yaml").write_text(
        "id: x\nname: X\ntype: rural\nbbox: [35, -1, 35.1, -0.9]\ndem: d\n"
        "backtest_event: {start: a, end: b}\nbefore_period: {start: a, end: b}\n"
        "user_types: [farmer]\nexport_bbox: [35.05, -1, 35.1, -0.9]\n")
    with pytest.raises(ValueError, match="must contain"):
        config.load("x", tmp_path)


def _tif(path, arr, nodata, origin=(35.0, -0.5), res=0.01):
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                       dtype=arr.dtype, crs="EPSG:4326", transform=from_origin(*origin, res, res),
                       nodata=nodata) as ds:
        ds.write(arr, 1)


def test_stats_counts_nodata_and_coverage(tmp_path):
    a = np.arange(100, dtype="float32").reshape(10, 10)
    a[:2, :] = -9999                                       # 20 % nodata
    _tif(tmp_path / "a.tif", a, -9999)                     # covers 35.0..35.1, -0.6..-0.5
    s = fetch.stats(tmp_path / "a.tif", [35.0, -0.6, 35.1, -0.5])
    assert s["nodata_share"] == pytest.approx(0.2)
    assert (s["min"], s["max"]) == (20.0, 99.0)
    assert s["covers_bbox"] and not s["all_nodata"]
    assert not fetch.stats(tmp_path / "a.tif", [34.9, -0.6, 35.1, -0.5])["covers_bbox"]  # 10 px short


def test_stats_flags_all_nodata(tmp_path):
    _tif(tmp_path / "b.tif", np.full((5, 5), -9999, "float32"), -9999)
    assert fetch.stats(tmp_path / "b.tif", [35.0, -0.55, 35.05, -0.5])["all_nodata"]


def test_clip_mosaics_two_tiles(tmp_path):
    _tif(tmp_path / "w.tif", np.full((10, 10), 1, "int16"), -1, origin=(35.0, -0.5))
    _tif(tmp_path / "e.tif", np.full((10, 10), 2, "int16"), -1, origin=(35.1, -0.5))
    fetch.clip([str(tmp_path / "w.tif"), str(tmp_path / "e.tif")], [35.05, -0.6, 35.15, -0.5], tmp_path / "c.tif")
    with rasterio.open(tmp_path / "c.tif") as ds:
        a = ds.read(1)
    assert a.shape == (10, 10) and (a[:, :5] == 1).all() and (a[:, 5:] == 2).all()
