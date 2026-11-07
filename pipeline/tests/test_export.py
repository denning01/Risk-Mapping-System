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


# --- F2.1 / F2.2: a clip must lie on its source's native pixel grid --------------------------------------
def _pc_tile(path, origin_lon, origin_lat, res, n=40):
    """A tile like GLO-30: pixel-centre registered on whole degrees, i.e. its EDGE is half a pixel off the degree."""
    arr = (np.arange(n * n, dtype="float32").reshape(n, n))
    with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1, dtype="float32", crs="EPSG:4326",
                       transform=from_origin(origin_lon - res / 2, origin_lat + res / 2, res, res)) as ds:
        ds.write(arr, 1)
    return arr


def test_clip_stays_on_the_native_grid_of_a_pixel_centre_registered_tile(tmp_path):
    res = 0.01
    arr = _pc_tile(tmp_path / "t.tif", 35.0, 0.0, res)
    bbox = [35.10, -0.20, 35.20, -0.10]                 # whole-degree-ish box: lands on pixel CENTRES of this tile
    fetch.clip([str(tmp_path / "t.tif")], bbox, tmp_path / "c.tif")
    with rasterio.open(tmp_path / "t.tif") as src, rasterio.open(tmp_path / "c.tif") as c:
        dx, dy = fetch.grid_phase_px(c.transform, src.transform)
        assert dx == pytest.approx(round(dx), abs=1e-6) and dy == pytest.approx(round(dy), abs=1e-6)
        b = c.bounds
        assert b.left <= bbox[0] and b.bottom <= bbox[1] and b.right >= bbox[2] and b.top >= bbox[3]
        clipped = c.read(1)
        r0, c0 = int(round(dy)), int(round(dx))
        np.testing.assert_array_equal(clipped, arr[r0:r0 + clipped.shape[0], c0:c0 + clipped.shape[1]])


def test_snap_bounds_grows_outward_to_pixel_edges():
    t = from_origin(34.9995, 0.0005, 0.001, 0.001)      # edges at x.xxx5
    w, s, e, n = fetch.snap_bounds([35.0, -0.1, 35.1, 0.0], t)
    assert (w, e) == (pytest.approx(34.9995), pytest.approx(35.1005))
    assert (s, n) == (pytest.approx(-0.1005), pytest.approx(0.0005))
    # already on edges: unchanged
    assert fetch.snap_bounds([34.9995, -0.0995, 35.0995, 0.0005], t) == pytest.approx((34.9995, -0.0995, 35.0995, 0.0005))


def test_fabdem_tiles_are_read_from_the_right_10_degree_zip():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("ex", Path(__file__).resolve().parents[1] / "01_ee_export.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    base = "/vsizip//vsicurl/https://data.bris.ac.uk/datasets/s5hqmjcdj8yo2ibzi9b4ew3sn/"
    urls = ex.fabdem_urls([36.50, -1.50, 37.10, -0.95])
    assert urls == [base + "S10E030-N00E040_FABDEM_V1-2.zip/S02E036_FABDEM_V1-2.tif",   # SW-corner names, as on the server
                    base + "S10E030-N00E040_FABDEM_V1-2.zip/S02E037_FABDEM_V1-2.tif",
                    base + "S10E030-N00E040_FABDEM_V1-2.zip/S01E036_FABDEM_V1-2.tif",
                    base + "S10E030-N00E040_FABDEM_V1-2.zip/S01E037_FABDEM_V1-2.tif"]
    # a box north of the equator uses the N00..N10 zip
    assert ex.fabdem_urls([36.1, 0.2, 36.2, 0.3]) == [base + "N00E030-N10E040_FABDEM_V1-2.zip/N00E036_FABDEM_V1-2.tif"]


def test_dem_file_follows_the_configured_dem():
    from pipeline.lib import config
    assert config.load("nairobi")["dem_file"] == "dem_fabdem.tif"
    assert config.load("nyando")["dem_file"] == "dem_glo30.tif"


def test_chirps_daily_days_cover_each_backtest_window():
    """M-07: daily CHIRPS follows the config's backtest window (Nairobi Apr-May 2024), not a hard-coded 2023 OND."""
    from pipeline.lib import config
    ny = ex.daily_days(config.load("nyando"))
    assert len(ny) == 92 and ny[0] == "2023-10-01" and ny[-1] == "2023-12-31"
    nb = ex.daily_days(config.load("nairobi"))
    assert nb[0] == "2024-04-05" and nb[-1] == "2024-05-10" and len(nb) == 36 and len(set(nb)) == 36


def test_forecast_maps_the_wettest_day_to_the_nearest_slider_value():
    """M-11 mapping rule: nearest of 50..250 mm/24 h; under 25 mm maps to no scenario."""
    spec = importlib.util.spec_from_file_location("fc", Path(__file__).resolve().parents[1] / "08_forecast.py")
    fc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fc)
    assert fc.map_rain(24.9) is None and fc.map_rain(25.0) == 50 and fc.map_rain(74.0) == 50
    assert fc.map_rain(76.0) == 100 and fc.map_rain(180.0) == 200 and fc.map_rain(400.0) == 250
    assert fc.OUTLOOK["enso_established"] is True
    assert fc.OUTLOOK["above_normal_pct_band"] == {"nyando": [70, 80], "nairobi": [80, 90]}


def test_forecast_climatology_drops_null_days_and_reports_the_real_period():
    """M-11: the API's GloFAS record is null before 1997, so a '1991-2020' label would be false."""
    spec = importlib.util.spec_from_file_location("fc2", Path(__file__).resolve().parents[1] / "08_forecast.py")
    fc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fc)
    c = fc.clim(["1991-01-01", "1991-01-02", "1997-01-01", "1997-01-02", "1997-01-03", "1997-01-04"],
                [None, None, 1.0, 2.0, 3.0, 4.0], peak=3.5)
    assert c["period"] == "1997-01-01..1997-01-04" and c["days"] == 4 and c["missing_days_in_request"] == 2
    assert c["p50_m3s"] == 2.5 and c["max_m3s"] == 4.0 and c["peak_percentile"] == 75.0   # 3 of 4 finite days below 3.5


def test_forecast_reports_the_point_max_on_the_wettest_day_separately_from_the_16_day_point_max():
    """F9.2: Nyando's 34.5 mm single-point max was on 11-12, not on the wettest AOI-mean day 11-13 (27.8 mm there)."""
    spec = importlib.util.spec_from_file_location("fc3", Path(__file__).resolve().parents[1] / "08_forecast.py")
    fc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fc)
    pr = np.array([[34.5, 27.8], [0.0, 20.0], [0.0, 10.4]])           # 3 points x 2 days
    r = fc.rain_summary(pr, ["d1", "d2"])
    assert r["wettest_day"] == "d2" and r["wettest_day_mm"] == 19.4 and r["wettest_day_point_max_mm"] == 27.8
    assert r["max_single_point_day"] == "d1" and r["max_single_point_day_mm"] == 34.5
    assert "**rain_summary(pr, days)" in (Path(__file__).resolve().parents[1] / "08_forecast.py").read_text()
