"""M-01: config loading, UTM derivation, AOI area. Real configs and hand-checkable values."""
import json

import pytest
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info

from pipeline.lib import config, paths


@pytest.mark.parametrize("lon,lat,epsg", [
    (35.075, -0.225, 32736),   # Nyando centre: zone floor(215.075/6)+1 = 36, south
    (36.85, -1.275, 32737),    # Nairobi centre: zone floor(216.85/6)+1 = 37, south
    (35.0, 0.5, 32636),        # north of the equator
    (36.0, -1.0, 32737),       # exactly on a zone edge belongs to the zone to the east
    (-0.1, 51.5, 32630),       # London, zone 30N
])
def test_utm_epsg_hand_values(lon, lat, epsg):
    assert config.utm_epsg(lon, lat) == epsg


@pytest.mark.parametrize("area", ["nyando", "nairobi"])
def test_utm_matches_pyproj_database(area):
    """Second method: pyproj's own UTM lookup for the AOI must contain our derived EPSG."""
    cfg = config.load(area)
    w, s, e, n = cfg["bbox"]
    infos = query_utm_crs_info(datum_name="WGS 84",
                               area_of_interest=AreaOfInterest(w, s, e, n))
    codes = {int(i.code) for i in infos}
    assert cfg["utm_epsg"] in codes, (cfg["utm_epsg"], codes)


def test_both_areas_load_with_derived_fields():
    assert config.areas() == ["nairobi", "nyando"]
    ny, nb = config.load("nyando"), config.load("nairobi")
    assert ny["utm_epsg"] == 32736 and nb["utm_epsg"] == 32737
    # 0.50 x 0.45 deg at the equator ~ (0.50*111.32)*(0.45*110.6) ~ 2770 km2 (west edge 34.80); 0.14 x 0.11 deg ~ 190 km2
    assert 2700 < ny["area_km2"] < 2850
    assert 180 < nb["area_km2"] < 200


@pytest.mark.parametrize("area", ["nyando", "nairobi"])
def test_area_two_methods_agree(area):
    cfg = config.load(area)
    utm = config.bbox_area_km2_utm(cfg["bbox"], cfg["utm_epsg"])
    assert abs(utm - cfg["area_km2"]) / cfg["area_km2"] < 0.005  # UTM scale factor 0.9996 -> ~0.1 %


@pytest.mark.parametrize("area", ["nyando", "nairobi"])
def test_bbox_matches_app_areas_json(area):
    """The model must cover exactly the box the app frames (web/public/data/areas.json, read-only)."""
    app = {a["id"]: a for a in json.loads((paths.REPO_ROOT / "web/public/data/areas.json").read_text())}
    cfg = config.load(area)
    assert app[area]["bbox"] == pytest.approx(cfg["bbox"])
    assert app[area]["user_types"] == cfg["user_types"]


def test_typed_utm_is_refused(tmp_path):
    (tmp_path / "x.yaml").write_text(
        "id: x\nname: X\ntype: rural\nbbox: [35, -1, 35.1, -0.9]\ndem: d\n"
        "backtest_event: {start: a, end: b}\nbefore_period: {start: a, end: b}\n"
        "user_types: [farmer]\nutm_epsg: 32736\n")
    with pytest.raises(ValueError, match="derived"):
        config.load("x", tmp_path)


def test_bbox_straddling_zones_is_refused(tmp_path):
    (tmp_path / "x.yaml").write_text(
        "id: x\nname: X\ntype: rural\nbbox: [35.9, -1, 36.1, -0.9]\ndem: d\n"
        "backtest_event: {start: a, end: b}\nbefore_period: {start: a, end: b}\n"
        "user_types: [farmer]\n")
    with pytest.raises(ValueError, match="straddles"):
        config.load("x", tmp_path)


def test_data_root_env_and_default(monkeypatch, tmp_path):
    monkeypatch.setenv("RMS_DATA", str(tmp_path))
    assert paths.data_root() == tmp_path.resolve()
    assert paths.model_dir("nyando") == tmp_path.resolve() / "processed" / "nyando" / "model"
    monkeypatch.setenv("RMS_DATA", "")
    assert paths.data_root() == (paths.REPO_ROOT.parent / "data").resolve()


# --- closes F1.5: the load() guards each get a test ------------------------------------------
def _write(tmp_path, name, **over):
    base = {"id": name, "name": "X", "type": "rural", "bbox": "[35, -1, 35.1, -0.9]", "dem": "d",
            "backtest_event": "{start: a, end: b}", "before_period": "{start: a, end: b}",
            "user_types": "[farmer]"}
    base.update(over)
    (tmp_path / f"{name}.yaml").write_text("".join(f"{k}: {v}\n" for k, v in base.items()))


def test_id_must_match_file_name(tmp_path):
    _write(tmp_path, "x", id="y")
    with pytest.raises(ValueError, match="file name"):
        config.load("x", tmp_path)


@pytest.mark.parametrize("bbox", ["[35.1, -1, 35, -0.9]", "[35, -0.9, 35.1, -1]"])
def test_bbox_order_west_south_east_north(tmp_path, bbox):
    _write(tmp_path, "x", bbox=bbox)
    with pytest.raises(ValueError, match="west, south, east, north"):
        config.load("x", tmp_path)


def test_equator_belongs_to_the_north():
    assert config.utm_epsg(35.0, 0.0) == 32636   # lat 0.0 is northern-hemisphere UTM (326zz)
    assert config.utm_epsg(35.0, -1e-9) == 32736


# --- F1.3: the Nyando River mouth (Wikidata Q58792399 P625, qualifier P518=Q1233637 "river mouth") ---
NYANDO_MOUTH = (34.84887, -0.27878)   # https://www.wikidata.org/wiki/Q58792399 (retrieved 2026-11-06)


def _inside(bbox, lon, lat):
    w, s, e, n = bbox
    return w <= lon <= e and s <= lat <= n


def test_nyando_export_box_contains_the_river_mouth():
    assert _inside(config.load("nyando")["export_bbox"], *NYANDO_MOUTH)


def test_nyando_aoi_contains_the_river_mouth():
    # bbox moved 34.85 -> 34.80 (operator ruling; exposure areas.json on data e472d23); was a strict xfail before
    assert _inside(config.load("nyando")["bbox"], *NYANDO_MOUTH)
