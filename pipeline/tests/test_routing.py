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


# ---- F3.7: extract() on a hand-written .osm (pyosmium reads XML) ----
BBOX = [35.0, -0.21, 35.01, -0.20]


def _osm_fixture(path: Path):
    n = lambda i, lon, lat, tags="": f'<node id="{i}" version="1" lat="{lat}" lon="{lon}">{tags}</node>'
    t = lambda k, v: f'<tag k="{k}" v="{v}"/>'
    body = [
        n(1, 35.002, -0.205, t("amenity", "school") + t("name", "In School")),        # node shelter inside bbox
        n(2, 35.20, -0.205, t("amenity", "school") + t("name", "Out School")),        # node shelter outside bbox
        n(3, 35.0065, -0.2065, t("amenity", "school") + t("name", "Dup School")),     # node inside the school area below
        n(10, 35.006, -0.207), n(11, 35.007, -0.207), n(12, 35.007, -0.206), n(13, 35.006, -0.206),
        n(20, 35.005, -0.205), n(21, 35.10, -0.205),                                  # road: one node in buffer, one far out
        n(30, 35.30, -0.30), n(31, 35.31, -0.30),                                     # road entirely outside the buffer
        n(40, 35.20, -0.207), n(41, 35.201, -0.207), n(42, 35.201, -0.206), n(43, 35.20, -0.206),  # F3.14: area outside
        '<way id="100" version="1">' + "".join(f'<nd ref="{r}"/>' for r in (10, 11, 12, 13, 10))
        + t("amenity", "school") + t("name", "Area School") + "</way>",
        '<way id="101" version="1">' + "".join(f'<nd ref="{r}"/>' for r in (40, 41, 42, 43, 40))
        + t("amenity", "school") + t("name", "Far Area School") + "</way>",
        '<way id="200" version="1"><nd ref="20"/><nd ref="21"/>' + t("highway", "primary") + "</way>",
        '<way id="201" version="1"><nd ref="30"/><nd ref="31"/>' + t("highway", "primary") + "</way>",
    ]
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6">\n' + "\n".join(body) + "\n</osm>\n")


def test_extract_on_handwritten_osm(tmp_path):
    f = tmp_path / "t.osm"
    _osm_fixture(f)
    ex = rt.extract(f, {"nyando": BBOX})["nyando"]
    got = sorted(s["osm"] for s in ex["shelters"])
    assert got == ["n1", "n3", "w100"]                       # n2 and area w101 outside bbox; w100 assembled as an area
    keep, dropped = rt.dedupe_shelters(ex["shelters"])
    assert dropped == 1 and sorted(s["osm"] for s in keep) == ["n1", "w100"]   # n3 is inside same-type w100
    for nt in ("drive", "walk"):
        nodes, ways = ex[nt]
        assert [w[0] for w in ways] == [200]                 # partly-inside road kept whole, outside road dropped
        assert set(nodes) == {20, 21}


# ---- F3.8 ----
def test_drive_graph_drops_oneway_dead_end_walk_keeps_it(tmp_path):
    """C: a one-way spur (2 -> 4) cannot be left again, so it is outside the strongly connected drive graph."""
    nodes = {1: (35.00, 0.0), 2: (35.01, 0.0), 3: (35.02, 0.0), 4: (35.01, 0.005)}
    ways = [(10, [1, 2], {"highway": "primary"}), (11, [2, 3], {"highway": "primary"}),
            (12, [2, 4], {"highway": "tertiary", "oneway": "yes"})]
    xml = tmp_path / "o.osm"
    rt.write_osm_xml(xml, nodes, ways)
    bb = (34.99, -0.01, 35.03, 0.01)
    assert 4 not in rt.build_graph(xml, "drive", bb, urban=False).nodes
    assert 4 in rt.build_graph(xml, "walk", bb, urban=False).nodes


def test_xml_escaping_roundtrips_awkward_names(tmp_path):
    """F: quotes, ampersands and angle brackets in tag values survive write_osm_xml -> graph_from_xml."""
    name = 'Mama "Ngina" & <Sons> Rd'
    nodes = {1: (35.00, 0.0), 2: (35.01, 0.0), 3: (35.02, 0.0), 4: (35.01, 0.005)}
    ways = [(10, [1, 2], {"highway": "primary", "name": name}), (11, [2, 3], {"highway": "primary"}),
            (12, [2, 4], {"highway": "primary"})]
    xml = tmp_path / "e.osm"
    rt.write_osm_xml(xml, nodes, ways)
    G = rt.build_graph(xml, "walk", (34.99, -0.01, 35.03, 0.01), urban=False)
    assert name in {d.get("name") for _, _, d in G.edges(data=True)}


def test_prepare_refuses_md5_mismatch(tmp_path):
    """G: a PBF whose md5 does not match its .md5 sidecar is refused before anything is read."""
    pbf = tmp_path / "x.osm.pbf"
    pbf.write_bytes(b"not the real file")
    (tmp_path / "x.osm.pbf.md5").write_text("0" * 32 + "  x.osm.pbf\n")
    assert rt.main(["prepare", "--area", "nyando", "--pbf", str(pbf)]) == 1


# ---- F3.9 ----
def test_unparseable_maxspeed_labelled_as_such(tmp_path):
    nodes = {1: (35.00, 0.0), 2: (35.01, 0.0), 3: (35.02, 0.0), 4: (35.01, 0.005)}
    ways = [(10, [1, 2], {"highway": "trunk", "maxspeed": "80-110", "name": "Range Rd"}),
            (11, [2, 3], {"highway": "trunk", "maxspeed": "80", "name": "Tagged Rd"}),
            (12, [2, 4], {"highway": "trunk", "name": "Plain Rd"})]
    xml = tmp_path / "m.osm"
    rt.write_osm_xml(xml, nodes, ways)
    G = rt.build_graph(xml, "drive", (34.99, -0.01, 35.03, 0.01), urban=True)
    src = {d["name"]: (d["speed_src"], d["speed_kph"]) for _, _, d in G.edges(data=True)}
    assert src["Range Rd"] == ("maxspeed_unparsed", 50.0)    # osmnx fell back to the (urban-capped) class value
    assert src["Tagged Rd"] == ("maxspeed", 80.0)
    assert src["Plain Rd"] == ("class", 50.0)


# ---- F3.13: a merged two-class edge is timed by a defined rule, independent of list order ----
def test_merged_two_class_edge_uses_slowest_class(tmp_path):
    nodes = {1: (35.00, 0.0), 2: (35.01, 0.0), 3: (35.02, 0.0)}   # node 2 is not an intersection -> one merged edge
    ways = [(10, [1, 2], {"highway": "primary"}), (11, [2, 3], {"highway": "residential"})]
    xml = tmp_path / "mg.osm"
    rt.write_osm_xml(xml, nodes, ways)
    bb = (34.99, -0.01, 35.03, 0.01)
    G = rt.build_graph(xml, "drive", bb, urban=False)
    for _, _, d in G.edges(data=True):
        assert d["highway"] == "residential" and d["highway_merged"] == "primary;residential"
        assert d["speed_kph"] == rt.HWY_KPH["residential"]
    # the list order osmnx hands over must not matter (it comes from a set)
    import osmnx as ox
    for order in (["primary", "residential"], ["residential", "primary"]):
        H = ox.graph_from_xml(xml, bidirectional=False, simplify=True, retain_all=True)
        for _, _, d in H.edges(data=True):
            assert isinstance(d["highway"], list)
            d["highway"] = list(order)
        H = rt.add_travel_times(H, "drive", urban=False)
        assert {d["speed_kph"] for _, _, d in H.edges(data=True)} == {rt.HWY_KPH["residential"]}
    assert rt.slowest_class(["motorway", "made_up_class"]) == "made_up_class"   # unknown -> FALLBACK_KPH (25) < 80


# ---- E-03: named places for origin checks ----
def test_place_kind():
    assert rt.place_kind({"place": "suburb", "name": "Kibera"}) == "place=suburb"
    assert rt.place_kind({"place": "suburb"}) is None                      # unnamed place is useless for a check
    assert rt.place_kind({"amenity": "marketplace"}) == "amenity=marketplace"
    assert rt.place_kind({"boundary": "administrative", "admin_level": "5", "name": "X"}) == "admin_level=5"
    assert rt.place_kind({"landuse": "farmland"}) == "landuse=farmland"
    assert rt.place_kind({"landuse": "residential", "name": "Y"}) is None
    assert rt.place_kind({"amenity": "school", "name": "Z"}) is None


def test_extract_places_on_handwritten_osm(tmp_path):
    n = lambda i, lon, lat, tags="": f'<node id="{i}" version="1" lat="{lat}" lon="{lon}">{tags}</node>'
    t = lambda k, v: f'<tag k="{k}" v="{v}"/>'
    sq = lambda wid, refs, tags: (f'<way id="{wid}" version="1">' + "".join(f'<nd ref="{r}"/>' for r in refs)
                                  + tags + "</way>")
    body = [n(1, 35.005, -0.205, t("place", "village") + t("name", "In Village")),
            n(2, 35.50, -0.205, t("place", "village") + t("name", "Far Village")),          # outside bbox+buffer
            n(3, 35.025, -0.205, t("place", "hamlet") + t("name", "Buffer Hamlet")),        # in the 0.02 deg buffer
            n(10, 35.006, -0.207), n(11, 35.007, -0.207), n(12, 35.007, -0.206), n(13, 35.006, -0.206),
            n(20, 35.60, -0.207), n(21, 35.601, -0.207), n(22, 35.601, -0.206), n(23, 35.60, -0.206),
            sq(100, (10, 11, 12, 13, 10), t("landuse", "farmland")),
            sq(101, (20, 21, 22, 23, 20), t("amenity", "marketplace") + t("name", "Far Market"))]
    f = tmp_path / "p.osm"
    f.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6">\n' + "\n".join(body) + "\n</osm>\n")
    got = {p["properties"]["osm"]: p for p in rt.extract_places(f, {"nyando": BBOX})["nyando"]}
    assert sorted(got) == ["n1", "n3", "w100"]
    farm = got["w100"]["properties"]
    assert farm["kind"] == "landuse=farmland" and farm["name"] is None
    assert farm["area_km2"] == pytest.approx(0.0124, rel=0.02)                 # 0.001 deg x 0.001 deg at the equator


def _places():
    P = lambda osm, kind, name, lon, lat: {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                                           "properties": {"osm": osm, "kind": kind, "name": name, "area_km2": None}}
    return [P("n1", "place=town", "Good Town", 35.005, -0.205), P("n2", "place=village", "Next Village", 35.006, -0.205),
            P("n3", "place=town", "Far Town", 35.20, -0.205), P("n4", "place=town", "Roadless Town", 35.009, -0.2099)]


def _gn():
    import numpy as np
    xy = (np.array([35.0051, 35.008]), np.array([-0.205, -0.205]))     # ~11 m from n1; n4 is ~550 m from the nearest
    return {"walk": xy, "drive": xy}


@pytest.mark.parametrize("spec,err", [
    ([("o1", "Good", "n1", "farmer")], None),
    ([("o1", "Good", "n1", "pilot")], "user_type 'pilot'"),
    ([("o1", "Far", "n3", "farmer")], "outside bbox"),
    ([("o1", "Ghost", "n9", "farmer")], "not in osm_places"),
    ([("o1", "Roadless", "n4", "farmer")], "from the walk graph"),
    ([("o1", "Good", "n1", "farmer")], "from the drive graph"),         # F4.5: near the walk graph, far from drive
    ([("o1", "Good", "n1", "farmer")], "no origin"),                  # run with two user_types: one uncovered
])
def test_build_origins_checks(monkeypatch, spec, err):
    monkeypatch.setitem(rt.ORIGINS, "nyando", spec)
    uts = ["farmer", "trader"] if err == "no origin" else ["farmer"]
    gn = _gn()
    if err == "from the drive graph":
        import numpy as np
        gn["drive"] = (np.array([35.009]), np.array([-0.201]))          # ~620 m from n1; walk nodes still ~11 m
    if err is None:
        rows, checks = rt.build_origins("nyando", _places(), uts, BBOX, gn)
        assert rows == [{"id": "o1", "name": "Good", "lon": 35.005, "lat": -0.205, "user_type": "farmer"}]
        assert checks[0]["nearest_other_osm_name"] == "Next Village" and checks[0]["nearest_other_m"] == 111
        assert checks[0]["snap_m"]["walk"] == 11
    else:
        with pytest.raises(ValueError, match=err):
            rt.build_origins("nyando", _places(), uts, BBOX, gn)


def test_committed_origins_cover_every_user_type():
    import json
    areas = {a["id"]: a for a in json.loads((Path(__file__).resolve().parents[2] / "web/public/data/areas.json").read_text())}
    for a, spec in rt.ORIGINS.items():
        assert {s[3] for s in spec} == set(areas[a]["user_types"]) and 3 <= len(spec) <= 6


# ---- F4.6: the COMMITTED origins.json files are exactly what ORIGINS + the OSM points give ----
OSM_POINTS = Path(__file__).resolve().parent / "data" / "origins_osm_points.json"


def test_committed_origins_json_matches_origins_and_osm_points():
    import json
    pts = json.loads(OSM_POINTS.read_text())
    root = Path(__file__).resolve().parents[2] / "web" / "public" / "data"
    for a, spec in rt.ORIGINS.items():
        committed = json.loads((root / a / "origins.json").read_text())
        assert [(o["id"], o["name"], o["user_type"]) for o in committed] == [(i, n, u) for i, n, _, u in spec]
        for o, (_, _, osm, _) in zip(committed, spec):
            lon, lat = pts[a][osm]["lonlat"]
            assert (o["lon"], o["lat"]) == (pytest.approx(lon, abs=1e-5), pytest.approx(lat, abs=1e-5)), (a, o["id"])


def test_osm_points_fixture_equals_the_places_cache_when_present():
    """The committed fixture cannot drift from the cache it was copied from (checked where $RMS_DATA exists)."""
    import json
    pts = json.loads(OSM_POINTS.read_text())
    checked = 0
    for a, spec in rt.ORIGINS.items():
        cache = rt.rms_data() / "processed" / a / "exposure" / "osm_places.geojson"
        if not cache.exists():
            continue
        F = {f["properties"]["osm"]: f for f in json.loads(cache.read_text())["features"]}
        for _, _, osm, _ in spec:
            assert F[osm]["geometry"]["coordinates"] == pts[a][osm]["lonlat"] and F[osm]["properties"]["name"] == pts[a][osm]["name"]
            checked += 1
    if not checked:
        pytest.skip("no osm_places cache under $RMS_DATA")
