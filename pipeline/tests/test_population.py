"""Tests for pipeline/05_population.py on tiny synthetic rasters."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest
from rasterio.transform import from_origin

spec = importlib.util.spec_from_file_location("pop", Path(__file__).resolve().parents[1] / "05_population.py")
pop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pop)

RES = 1 / 1200  # WorldPop's 3 arc-second pixel


def _wp(tmp, arr, x0=35.0, y0=-0.2, nodata=-99999.0):
    import rasterio
    p = tmp / "wp.tif"
    with rasterio.open(p, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(x0, y0, RES, RES), nodata=nodata) as d:
        d.write(arr.astype("float32"), 1)
    return p


def _area_6933(x0, y0):
    """Independent check: the same pixel's area in EPSG:6933 (WGS84 cylindrical equal-area)."""
    from pyproj import Transformer
    from shapely.geometry import box
    from shapely.ops import transform
    t = Transformer.from_crs(4326, 6933, always_xy=True)
    return transform(lambda x, y: t.transform(x, y), box(x0, y0 - RES, x0 + RES, y0).segmentize(RES / 20)).area


@pytest.mark.parametrize("lat", [0.0, -1.3, 60.0])
def test_pixel_area_matches_equal_area_projection(lat):
    a = pop.pixel_area_m2(from_origin(35.0, lat, RES, RES), 1)[0, 0]
    assert a == pytest.approx(_area_6933(35.0, lat), rel=1e-4)
    assert 8400 < pop.pixel_area_m2(from_origin(35.0, 0.0, RES, RES), 1)[0, 0] < 8600   # ~92.6 m x ~92.1 m


def test_sum_in_polygon_uses_pixel_centres_and_drops_nodata(tmp_path):
    from shapely.geometry import box
    arr = np.ones((10, 10)); arr[0, 0] = -99999.0; arr[5, 5] = 7.0
    p = _wp(tmp_path, arr)
    # polygon covering the left 5 columns and top 6 rows exactly, plus a sliver that touches no pixel centre
    g = box(35.0, -0.2 - 6 * RES, 35.0 + 5.4 * RES, -0.2)
    assert pop.sum_in_polygon(p, g) == pytest.approx(6 * 5 - 1)      # 30 pixels, nodata one counts 0
    g2 = box(35.0 + 5 * RES, -0.2 - 6 * RES, 35.0 + 6 * RES, -0.2 - 5 * RES)
    assert pop.sum_in_polygon(p, g2) == pytest.approx(7.0)


def test_scale_factors_hit_projection_exactly():
    f = pop.scale_factors({"low": 70, "medium": 100, "high": 120}, 50.0)
    assert {s: 50.0 * v for s, v in f.items()} == {"low": 70, "medium": 100, "high": 120}
    with pytest.raises(ValueError):
        pop.scale_factors({"low": 1, "medium": 1, "high": 1}, 0.0)


def _grid(n_src=300, dst=(1000, 1000)):
    from pyproj import Transformer
    src_tf = from_origin(35.0, -0.2, RES, RES)
    x0, y0 = Transformer.from_crs(4326, 32736, always_xy=True).transform(35.0, -0.2)
    return src_tf, from_origin(round(x0), round(y0), 30, 30)


def test_people_on_grid_preserves_total_of_a_large_field():
    """A uniform 300x300-pixel field (~27.6 km) fully inside the dst grid: total kept within 0.3 %."""
    src_tf, dst_tf = _grid()
    people = np.full((300, 300), 4.0)
    out = pop.people_on_grid(people, src_tf, (1000, 1000), dst_tf, "EPSG:32736")
    assert out.sum() == pytest.approx(people.sum(), rel=0.003)
    # density is uniform, so every covered interior cell holds 4 people x (900 m2 / pixel area)
    exp = 4.0 * 900 / pop.pixel_area_m2(src_tf, 1)[0, 0]
    assert out[100:800, 100:800] == pytest.approx(np.full((700, 700), exp), rel=1e-4)   # pixel area varies ~2e-5 by row


def test_people_on_grid_puts_people_in_the_right_place():
    src_tf, dst_tf = _grid()
    people = np.zeros((60, 60)); people[20:40, 10:30] = 5.0           # 2000 people in a ~1.84 km block
    out = pop.people_on_grid(people, src_tf, (200, 200), dst_tf, "EPSG:32736")
    assert out.sum() == pytest.approx(2000, rel=0.025)               # a single small block: edge rounding ~1 cell/side
    rows, cols = np.nonzero(out)
    # pixel rows 20-40, cols 10-30 (~92 m each) -> UTM rows ~61-123, cols ~31-92 (+/- a cell)
    assert 59 <= rows.min() <= 63 and 121 <= rows.max() <= 125
    assert 29 <= cols.min() <= 33 and 90 <= cols.max() <= 94


def test_exposed_people_only_wet_cells():
    g = np.array([[10.0, 20.0], [30.0, 40.0]])
    wet = np.array([[True, False], [False, True]])
    assert pop.exposed_people(g, wet, {"low": 0.5, "medium": 1.0, "high": 2.0}) == {"low": 25, "medium": 50, "high": 100}


def test_county_feature_requires_exactly_one():
    feats = [{"properties": {"name": "Kisumu"}}, {"properties": {"name": "Nairobi"}}]
    assert pop.county_feature("nyando", feats)["properties"]["name"] == "Kisumu"
    with pytest.raises(SystemExit):
        pop.county_feature("nyando", feats + [{"properties": {"name": "Kisumu"}}])


def test_read_buildings_filters_bbox_and_attaches_thresholds(tmp_path):
    import gzip
    rows = ["-0.2001,35.0001,50.0,0.80,X", "-0.2002,35.0002,60.0,0.70,X", "-0.9,35.0003,70.0,0.99,X"]  # 3rd outside
    f = tmp_path / "t.csv.gz"
    with gzip.open(f, "wt") as g:
        g.write("\n".join(rows) + "\n")
    b = pop.read_buildings([(f, "183")], [35.0, -0.21, 35.01, -0.20])
    assert list(b["area_m2"]) == [50.0, 60.0] and list(b["lat"]) == [-0.2001, -0.2002]
    assert set(b["thr85"]) == {0.716} and set(b["thr90"]) == {0.778}


def test_buildings_in_wet_counts_centroids_by_row_and_col():
    """Asymmetric probes, no mirror pair: points at (row 0, col 2) and (row 3, col 1). Transposing row/col would look
    up (2, 0) and (1, 3) instead."""
    from pyproj import Transformer
    tf = from_origin(722600.0, 9977880.0, 30, 30)
    to = Transformer.from_crs(32736, 4326, always_xy=True).transform
    pts = [to(722600 + 2.5 * 30, 9977880 - 0.5 * 30),    # row 0, col 2
           to(722600 + 1.5 * 30, 9977880 - 3.5 * 30),    # row 3, col 1
           to(722600 + 2.5 * 30, 9977880 - 0.5 * 30),    # row 0, col 2 but low confidence
           to(722600 - 100.0, 9977880 + 100.0)]          # outside the raster
    b = {"lon": np.array([p[0] for p in pts]), "lat": np.array([p[1] for p in pts]),
         "conf": np.array([0.9, 0.9, 0.5, 0.9]), "thr85": np.full(4, 0.716)}
    def wet_at(*cells):
        w = np.zeros((5, 5), bool)
        for rc in cells:
            w[rc] = True
        return w
    assert pop.buildings_in_wet(b, wet_at((0, 2)), tf, "EPSG:32736") == 1
    assert pop.buildings_in_wet(b, wet_at((3, 1)), tf, "EPSG:32736") == 1
    assert pop.buildings_in_wet(b, wet_at((2, 0), (1, 3)), tf, "EPSG:32736") == 0   # the transposed cells
    assert pop.buildings_in_wet(b, wet_at((0, 2), (3, 1)), tf, "EPSG:32736") == 2


def test_project_reproduces_population_json_for_both_units():
    import json
    root = Path(__file__).resolve().parents[2] / "web" / "public" / "data"
    for area, county in (("nyando", "Kisumu"), ("nairobi", "Nairobi")):
        pj = json.loads((root / area / "population.json").read_text())
        u = pj["units"][0]
        assert (u["p2009"], u["p2019"]) == pop.KNBS[county]
        for year in ("2026", "2036"):
            assert pop.project(*pop.KNBS[county], pj["assumptions"], int(year)) == u["projections"][year]


def test_exposed_both_ways_A_uses_unit_factor_B_per_county():
    man = {"factors_A": {"low": 1.0, "medium": 2.0, "high": 3.0},
           "counties": [{"id": 1, "factors": {"low": 1.0, "medium": 2.0, "high": 3.0}},
                        {"id": 2, "factors": {"low": 0.5, "medium": 1.0, "high": 1.5}},
                        {"id": 3, "name": "Kiambu", "aoi_share": 0.0}]}   # as prepare writes it: NO factors key
    people = np.array([[10.0, 20.0, 40.0, 80.0, 5.0]])
    county = np.array([[1, 2, 0, 2, 3]], dtype="uint8")
    wet = np.array([[True, True, True, False, True]])
    sums = pop.exposed_by_county(people, county, wet)
    assert sums == {0: 40.0, 1: 10.0, 2: 20.0, 3: 5.0}
    both = pop.exposed_both_ways(sums, man)
    assert both["A"] == {"low": 75, "medium": 150, "high": 225}
    # ids 0 and 3 (no county / no KNBS figures) fall back to A's factor
    assert both["B"] == {"low": 10 + 10 + 45, "medium": 20 + 20 + 90, "high": 30 + 30 + 135}
    assert both["fallback_people_2020"] == 45.0


def test_exposed_building_weighted_spreads_county_people_by_footprint_area():
    """2x2 grid, county 1 (left col) and 2 (right col). County 1 has 1000 WorldPop people in the AOI, county 2 has 500.
    County 1: buildings of 30 m2 (wet) and 90 m2 (dry) -> 25 % of its area wet. County 2: one dry building."""
    from pyproj import Transformer
    tf = from_origin(722600.0, 9977880.0, 30, 30)
    to = Transformer.from_crs(32736, 4326, always_xy=True).transform
    pts = [to(722600 + 15, 9977880 - 15), to(722600 + 15, 9977880 - 45), to(722600 + 45, 9977880 - 45),
           to(722600 + 15, 9977880 - 15)]                                          # last: low confidence, ignored
    b = {"lon": np.array([p[0] for p in pts]), "lat": np.array([p[1] for p in pts]),
         "area_m2": np.array([30.0, 90.0, 50.0, 10_000.0]), "conf": np.array([0.9, 0.9, 0.9, 0.1]),
         "thr85": np.full(4, 0.716)}
    county = np.array([[1, 2], [1, 2]], dtype="uint8")
    wet = np.array([[True, True], [False, False]])
    mask = np.ones((2, 2), bool)
    man = {"factors_A": {"low": 1.0, "medium": 2.0, "high": 3.0},
           "counties": [{"id": 1, "worldpop_aoi_2020": 1000.0, "factors": {"low": 1.0, "medium": 2.0, "high": 3.0}},
                        {"id": 2, "worldpop_aoi_2020": 500.0, "factors": {"low": 0.5, "medium": 1.0, "high": 1.5}}]}
    out = pop.exposed_building_weighted(b, wet, county, mask, tf, "EPSG:32736", man)
    assert out["B"] == {"low": 250, "medium": 500, "high": 750}          # 1000 x f x 0.25; county 2 has 0 wet area
    assert out["A"] == {"low": 250, "medium": 500, "high": 750}
    wet2 = np.array([[False, False], [False, True]])                       # county 2's only building now wet
    out2 = pop.exposed_building_weighted(b, wet2, county, mask, tf, "EPSG:32736", man)
    assert out2["B"]["medium"] == 500 and out2["A"]["medium"] == 1000      # 500 x 1.0 (B) vs 500 x 2.0 (A)
