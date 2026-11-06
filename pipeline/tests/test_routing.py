"""Tests for pipeline/06_routing.py on tiny synthetic OSM data."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("rt", Path(__file__).resolve().parents[1] / "06_routing.py")
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)


def test_filter_parser_roundtrips_osmnx_filters():
    for nt in ("drive", "walk"):
        assert len(rt.network_rules(nt)) >= 5


@pytest.mark.parametrize("tags,drive,walk", [
    ({"highway": "primary"}, True, True),
    ({"highway": "footway"}, False, True),
    ({"highway": "motorway"}, True, False),          # walk filter excludes "motor" (unanchored search)
    ({"highway": "track"}, False, True),             # osmnx drive excludes tracks; walk keeps them
    ({"highway": "residential", "access": "private"}, False, False),
    ({"highway": "service", "service": "driveway"}, False, True),
    ({"highway": "residential", "foot": "no"}, True, False),
    ({"building": "yes"}, False, False),             # no highway key
    ({"highway": "residential", "area": "yes"}, False, False),
])
def test_way_filters(tags, drive, walk):
    assert rt.way_passes(tags, rt.network_rules("drive")) is drive
    assert rt.way_passes(tags, rt.network_rules("walk")) is walk


def test_parser_rejects_unknown_syntax():
    with pytest.raises(ValueError):
        rt.parse_overpass_filter('["highway"](if: t["x"] > 1)')


def test_shelter_type_mapping():
    assert rt.shelter_type({"amenity": "school"}) == "school"
    assert rt.shelter_type({"amenity": "place_of_worship", "religion": "muslim"}) == "church"
    assert rt.shelter_type({"healthcare": "clinic"}) == "hospital"
    assert rt.shelter_type({"amenity": "community_centre"}) == "community_hall"
    assert rt.shelter_type({"amenity": "police"}) == "police"
    assert rt.shelter_type({"amenity": "bar"}) is None


def test_dedupe_drops_node_inside_same_type_area():
    from shapely.geometry import box
    a = {"osm": "w1", "type": "school", "lon": 35.0005, "lat": -0.2005, "geom": box(35.0, -0.201, 35.001, -0.2)}
    n_same = {"osm": "n1", "type": "school", "lon": 35.0002, "lat": -0.2002}
    n_other = {"osm": "n2", "type": "church", "lon": 35.0002, "lat": -0.2002}
    n_out = {"osm": "n3", "type": "school", "lon": 35.01, "lat": -0.2002}
    keep, dropped = rt.dedupe_shelters([a, n_same, n_other, n_out])
    assert dropped == 1 and [s["osm"] for s in keep] == ["w1", "n2", "n3"]


def _net(tmp: Path):
    """Nodes in a line on the equator, ~1112 m apart (0.01 deg): primary then residential with maxspeed 20."""
    nodes = {1: (35.00, 0.0), 2: (35.01, 0.0), 3: (35.02, 0.0), 4: (35.01, 0.005)}
    ways = [(10, [1, 2], {"highway": "primary", "name": "A Road"}),
            (11, [2, 3], {"highway": "residential", "maxspeed": "20", "name": "B Lane"}),
            (12, [2, 4], {"highway": "tertiary", "name": "C Spur", "maxspeed": "120 mph"})]  # 193 km/h: a tag error  # spur makes node 2 an intersection (no merge)
    xml = tmp / "t.osm"
    rt.write_osm_xml(xml, nodes, ways)
    return xml


def _edge(G, name):
    return next(d for _, _, d in G.edges(data=True) if d.get("name") == name)


def test_drive_graph_travel_times_rural_and_urban(tmp_path):
    xml = _net(tmp_path)
    bb = (34.99, -0.01, 35.03, 0.01)
    G = rt.build_graph(xml, "drive", bb, urban=False)
    a, b = _edge(G, "A Road"), _edge(G, "B Lane")
    assert a["length"] == pytest.approx(1113, rel=0.01)
    assert a["speed_kph"] == rt.HWY_KPH["primary"] and a["speed_src"] == "class"
    assert a["travel_time"] == pytest.approx(a["length"] / (60 / 3.6), rel=0.01)
    assert b["speed_kph"] == 20 and b["speed_src"] == "maxspeed"        # a tag beats the class value
    c = _edge(G, "C Spur")
    assert c["speed_kph"] == rt.HWY_KPH["tertiary"] and c["speed_src"] == "tag_invalid"   # > 110 km/h -> class value
    assert all(d["speed_kph"] <= rt.MAX_TAGGED_KPH for _, _, d in G.edges(data=True))
    Gu = rt.build_graph(xml, "drive", bb, urban=True)
    assert _edge(Gu, "A Road")["speed_kph"] == 50                         # Cap 403 s.42(3) urban cap
    assert _edge(Gu, "B Lane")["speed_kph"] == 20


def test_walk_graph_constant_speed_bidirectional(tmp_path):
    G = rt.build_graph(_net(tmp_path), "walk", (34.99, -0.01, 35.03, 0.01), urban=False)
    assert G.number_of_edges() == 6                                       # 3 ways, both directions
    for _, _, d in G.edges(data=True):
        assert d["speed_kph"] == 3.6
        assert d["travel_time"] == pytest.approx(d["length"] / 1.0, rel=0.01)  # 1.0 m/s
