"""Tests for pipeline/06_routing.py on tiny synthetic OSM data."""
import importlib.util
from pathlib import Path

import numpy as np
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


# ---- shelter contract types: human decision (worship + police YES), gated on Person B's schema change ----
@pytest.mark.parametrize("props,now,nxt", [
    ({"osm_tag": "amenity=place_of_worship", "religion": "christian", "name": "St Paul"}, "church", "place_of_worship"),
    ({"osm_tag": "amenity=place_of_worship", "religion": "muslim", "name": "Jamia Mosque"}, None, "place_of_worship"),
    ({"osm_tag": "amenity=place_of_worship", "religion": "hindu", "name": "Shree Temple"}, None, "place_of_worship"),
    ({"osm_tag": "amenity=place_of_worship", "religion": None, "name": "Kanisa la Mungu"}, "church", "place_of_worship"),
    ({"osm_tag": "amenity=place_of_worship", "religion": None, "name": "Masjid Noor"}, None, "place_of_worship"),
    ({"osm_tag": "amenity=place_of_worship", "religion": "christian", "name": None}, None, None),   # unnamed: held back
    ({"osm_tag": "amenity=place_of_worship", "religion": "christian", "name": "  "}, None, None),
    ({"osm_tag": "amenity=police", "name": "Ahero Police Station"}, None, "police"),
    ({"osm_tag": "amenity=school", "name": "X"}, "school", "school"),
    ({"osm_tag": "amenity=clinic", "name": "X"}, "hospital", "hospital"),
    ({"osm_tag": "healthcare=hospital", "name": "X"}, "hospital", "hospital"),
    ({"osm_tag": "amenity=community_centre", "name": "X"}, "community_hall", "community_hall"),
    ({"osm_tag": "amenity=bar", "name": "X"}, None, None),
])
def test_contract_type_before_and_after_the_schema_change(props, now, nxt):
    assert rt.contract_type(props, schema_next=False) == now
    assert rt.contract_type(props, schema_next=True) == nxt
    assert now is None or now in rt.CONTRACT_TYPES_NOW
    assert nxt is None or nxt in rt.CONTRACT_TYPES_NEXT


def test_default_emits_only_the_current_enum():
    assert rt.SCHEMA_HAS_WORSHIP_POLICE is False     # flipped only after Person B's schema is on data
    assert rt.contract_type({"osm_tag": "amenity=police"}) is None


# ---------------------------------------------------------------------------------------------
# E-05 flood-aware routing, on a synthetic lattice in UTM 37S (EPSG:32736), 300 m spacing
# ---------------------------------------------------------------------------------------------
_X0, _Y0, _SP = 722600.0, 9977880.0, 300.0


def _ll(x, y):
    from pyproj import Transformer
    return Transformer.from_crs(32736, 4326, always_xy=True).transform(x, y)


def _lattice(n=4, kph=3.6, names=None, drive=False):
    """n x n nodes, id r*10+c, at (X0 + c*SP, Y0 - r*SP); edges both ways between 4-neighbours."""
    import networkx as nx
    G = nx.MultiDiGraph(crs="EPSG:4326")
    for r in range(n):
        for c in range(n):
            lon, lat = _ll(_X0 + c * _SP, _Y0 - r * _SP)
            G.add_node(r * 10 + c, x=lon, y=lat)
    for r in range(n):
        for c in range(n):
            for dr, dc in ((0, 1), (1, 0)):
                if r + dr < n and c + dc < n:
                    a, b = r * 10 + c, (r + dr) * 10 + c + dc
                    nm = (names or {}).get(frozenset((a, b)))
                    for u, v in ((a, b), (b, a)):
                        G.add_edge(u, v, length=_SP, travel_time=_SP / (kph / 3.6), highway="residential",
                                   **({"name": nm} if nm else {}))
    return rt.RoutingGraph(G, "EPSG:32736")


_TF = None


def _wet(cells, shape=(40, 40)):
    """30 m grid with origin at (X0 - 15*30, Y0 + 15*30) so lattice nodes fall mid-grid. cells: list of (x, y) UTM."""
    from rasterio.transform import from_origin, rowcol
    tf = from_origin(_X0 - 450, _Y0 + 450, 30, 30)
    w = np.zeros(shape, bool)
    for x, y in cells:
        r, c = rowcol(tf, x, y)
        w[int(r), int(c)] = True
    return w, tf


def test_cut_catches_a_flooded_cell_near_one_end_not_only_the_midpoint():
    RG = _lattice(2)
    wet, tf = _wet([(_X0 + 20, _Y0)])               # 20 m along edge 0-1 (300 m): its midpoint (150 m) is dry
    cut = RG.cut(wet, tf)
    hit = {(RG.nodes[RG.u[e]], RG.nodes[RG.v[e]]) for e in np.nonzero(cut)[0]}
    assert hit == {(0, 1), (1, 0)}


def test_cut_is_empty_on_a_dry_raster_and_ignores_samples_outside_it():
    RG = _lattice(3)
    wet, tf = _wet([], shape=(5, 5))                # covers only a corner; the rest has no information
    assert not RG.cut(wet, tf).any()


def test_leg_detours_around_a_cut_edge_and_reports_unreachable():
    RG = _lattice(3)
    o, d = _ll(_X0, _Y0), _ll(_X0 + 2 * _SP, _Y0)  # node 0 -> node 2 along the top row
    free = rt.leg(RG, o, d, None)
    assert free["minutes"] == 10                    # 600 m at 1 m/s
    wet, tf = _wet([(_X0 + _SP + 150, _Y0)])        # edge 1-2 flooded
    det = rt.leg(RG, o, d, RG.cut(wet, tf))
    assert det["minutes"] == 20                     # 0-1-11-12-2: 1200 m
    wet2, tf = _wet([(_X0 + 150, _Y0), (_X0, _Y0 - 150)])   # both edges out of node 0 flooded
    cut2 = RG.cut(wet2, tf)
    # the origin's node is cut off: NO route. (A former version snapped to the nearest live node 300 m away and drew a
    # straight line through the water; caught by resampling the written lines against the raster.)
    assert RG.endpoint(*o, cut2, (wet2, tf))[0] == -1
    assert rt.leg(RG, o, d, cut2, (wet2, tf)) is None


def test_a_flooded_snap_leg_makes_the_endpoint_unreachable():
    RG = _lattice(3)
    o = _ll(_X0 - 200, _Y0)                          # 200 m west of node 0, off the network
    wet, tf = _wet([(_X0 - 100, _Y0)])              # water between the origin and node 0; no edge is wet
    cut = RG.cut(wet, tf)
    assert not cut.any()
    node, dist, why = RG.endpoint(*o, cut, (wet, tf))
    assert node == -1 and "flooded" in why
    assert RG.endpoint(*o, cut, None)[0] == RG.idx[0]   # without flood information the leg is not checked


def test_nearest_SAFE_shelter_skips_a_nearer_unsafe_one():
    W = _lattice(3)
    D = _lattice(3, kph=30, drive=True)
    near = dict(zip(("lon", "lat"), _ll(_X0 + _SP, _Y0)))
    far = dict(zip(("lon", "lat"), _ll(_X0 + 2 * _SP, _Y0 - 2 * _SP)))
    sh = [{"id": "x-near", "name": "Near school", "type": "school", "capacity": None, "safe": False, **near},
          {"id": "x-far", "name": "Far school", "type": "school", "capacity": None, "safe": True, **far}]
    o = {"id": "x-o1", "name": "O", "user_type": "trader", **dict(zip(("lon", "lat"), _ll(_X0, _Y0)))}
    no_cut = np.zeros(W.n_edges, bool)
    routes, extra, checks = rt.build_routes("t", {"type": "urban", "bbox": [-180, -90, 180, 90]}, [o], sh, W, D,
                                                 no_cut, np.zeros(D.n_edges, bool), {}, None)
    assert routes[0]["shelter_id"] == "x-far" and routes[0]["kind"] == "to_shelter" and routes[0]["baseline"] is None
    assert routes[0]["safe"]["minutes"] == 20 and extra == []
    sh[1]["safe"] = False
    routes, _, checks = rt.build_routes("t", {"type": "urban", "bbox": [-180, -90, 180, 90]}, [o], sh, W, D,
                                             no_cut, np.zeros(D.n_edges, bool), {}, None)
    assert routes == [] and "no safe shelter" in checks[0]["unreachable"]     # reported, not silently dropped


def test_commute_baseline_equals_safe_when_clear_and_names_avoided_roads_when_cut(monkeypatch):
    names = {frozenset((1, 2)): "Juja Road", frozenset((0, 1)): "Outer Ring Road"}
    W = _lattice(3)
    D = _lattice(3, kph=36, names=names, drive=True)
    monkeypatch.setitem(rt.COMMUTE, "x-o3", ("n1", "Kasarani"))
    o = {"id": "x-o3", "name": "W", "user_type": "commuter", **dict(zip(("lon", "lat"), _ll(_X0, _Y0)))}
    places = {"n1": _ll(_X0 + 2 * _SP, _Y0)}
    meta = {"type": "urban", "bbox": [-180, -90, 180, 90]}
    clear = rt.build_routes("t", meta, [o], [], W, D, np.zeros(W.n_edges, bool), np.zeros(D.n_edges, bool),
                                 places, None)[0][0]
    assert clear["kind"] == "commute" and clear["shelter_id"] is None
    assert clear["safe"] == clear["baseline"] and clear["avoided"] == []
    wet, tf = _wet([(_X0 + _SP + 150, _Y0)])                           # Juja Road segment flooded
    r = rt.build_routes("t", meta, [o], [], W, D, W.cut(wet, tf), D.cut(wet, tf), places, None)[0][0]
    assert r["avoided"] == ["Juja Road"] and r["safe"]["minutes"] > r["baseline"]["minutes"]
    assert r["safe"]["geometry"]["coordinates"] != r["baseline"]["geometry"]["coordinates"]


def test_relocation_picks_dry_high_ground_and_reports_none():
    from rasterio.transform import from_origin
    W = _lattice(3)
    D = _lattice(3, kph=30, drive=True)
    wet, tf = _wet([])
    hand = np.zeros_like(wet, float)
    from rasterio.transform import rowcol
    def put(x, y, v):
        r, c = rowcol(tf, x, y); hand[int(r) - 2:int(r) + 3, int(c) - 2:int(c) + 3] = v
    put(_X0 + 2 * _SP, _Y0 - 2 * _SP, 10.0)                 # node 22: high
    put(_X0 + _SP, _Y0, 30.0)                               # node 1: higher, but we flood it
    wet[tuple(int(v) for v in rowcol(tf, _X0 + _SP, _Y0))] = True
    o = {"id": "x-o1", "name": "S", "user_type": "settler", **dict(zip(("lon", "lat"), _ll(_X0, _Y0)))}
    meta = {"type": "rural", "bbox": [-180, -90, 180, 90]}
    reloc = {"wet": wet, "wet_tf": tf, "hand": hand, "hand_tf": tf}
    routes, extra, checks = rt.build_routes("t", meta, [o], [], W, D, W.cut(wet, tf), D.cut(wet, tf), {}, reloc)
    assert routes[0]["kind"] == "relocation" and extra[0]["type"] == "high_ground" and extra[0]["safe"]
    assert routes[0]["shelter_id"] == extra[0]["id"] == "x-hg-22"
    assert "HAND 10 m" in extra[0]["name"]
    reloc["hand"] = np.zeros_like(hand)
    routes, extra, checks = rt.build_routes("t", meta, [o], [], W, D, W.cut(wet, tf), D.cut(wet, tf), {}, reloc)
    assert routes == [] and extra == [] and "HAND" in checks[0]["unreachable"]


def test_robust_hand_removes_a_one_cell_spike_but_keeps_a_plateau():
    h = np.full((20, 20), 4.0)
    h[5, 5] = 13.0                                          # one roof
    h[10:20, 10:20] = 12.0                                  # a real 300 m x 300 m rise
    h[0, 19] = np.nan
    r = rt.robust_hand(h)
    assert r[5, 5] == 4.0 and r[15, 15] == 12.0
    assert r[0, 19] == 0.0           # NaN counts as 0 and, edge-replicated in the corner, drags p25 down: conservative


def test_roads_cut_orders_main_classes_first_and_keeps_only_named_in_bbox():
    names = {frozenset((0, 1)): "Small Lane", frozenset((10, 11)): "Small Lane", frozenset((1, 2)): "Big Highway"}
    D = _lattice(3, names=names)                  # Small Lane has twice the cut length: class must still win
    for e in range(D.n_edges):
        if D.name[e] == ["Big Highway"]:
            D.hwy[e] = "trunk"
    cut = np.ones(D.n_edges, bool)
    top, full = rt.roads_cut(D, cut, [-180, -90, 180, 90])
    assert top == ["Big Highway", "Small Lane"]
    assert rt.roads_cut(D, cut, [0, 0, 1, 1])[0] == []        # nothing in this bbox


def test_shelters_from_osm_uses_the_current_enum_and_labels_unnamed():
    feats = [{"geometry": {"coordinates": [35.0, -0.2]}, "properties": {"osm": "n1", "osm_tag": "amenity=school", "name": None}},
             {"geometry": {"coordinates": [35.0, -0.2]}, "properties": {"osm": "n2", "osm_tag": "amenity=place_of_worship",
                                                                       "name": "Masjid", "religion": "muslim"}},
             {"geometry": {"coordinates": [35.0, -0.2]}, "properties": {"osm": "n3", "osm_tag": "amenity=police", "name": "Police"}},
             {"geometry": {"coordinates": [36.0, -0.2]}, "properties": {"osm": "n4", "osm_tag": "amenity=school", "name": "Out"}}]
    out = rt.shelters_from_osm("x", feats, [34.9, -0.3, 35.1, -0.1])
    assert out == [{"id": "x-n1", "name": "School (unnamed in OpenStreetMap)", "type": "school", "lon": 35.0,
                    "lat": -0.2, "capacity": None, "safe": True}]


def test_a_bridge_way_is_not_cut_but_its_flooded_approach_on_the_same_edge_is(tmp_path):
    """Edge 0-1 (300 m) as one graph edge; only its first 100 m is an OSM bridge way. Wet under the bridge: not cut.
    Wet at 200 m (the approach, same graph edge): cut."""
    lon0, lat0 = _ll(_X0, _Y0)
    lon1, lat1 = _ll(_X0 + 100, _Y0)
    xml = tmp_path / "t.osm"
    rt.write_osm_xml(xml, {1: (lon0, lat0), 2: (lon1, lat1)}, [(9, [1, 2], {"highway": "primary", "bridge": "yes"})])
    bl = rt.bridge_lines(xml)
    assert len(bl) == 1 and np.allclose(bl[0], [(lon0, lat0), (lon1, lat1)], atol=1e-7)
    G = _lattice(2).G
    RG = rt.RoutingGraph(G, "EPSG:32736", rt.bridge_lines(xml))
    wet, tf = _wet([(_X0 + 50, _Y0)])
    assert not RG.cut(wet, tf).any()
    wet, tf = _wet([(_X0 + 200, _Y0)])
    assert RG.cut(wet, tf).sum() == 2                     # 0->1 and 1->0
    xml2 = tmp_path / "n.osm"
    rt.write_osm_xml(xml2, {1: (lon0, lat0), 2: (lon1, lat1)}, [(9, [1, 2], {"highway": "primary", "bridge": "no"})])
    assert rt.bridge_lines(xml2) == []


def test_relocation_candidates_exclude_a_wet_node_even_if_reachable():
    """Reachability normally drops wet nodes (their edges are cut); a bridge can keep one reachable. Pass every node as
    reachable and check the wet filter on its own."""
    W = _lattice(3)
    D = _lattice(3, kph=30, drive=True)
    wet, tf = _wet([])
    from rasterio.transform import rowcol
    hand = np.full(wet.shape, 10.0)
    r, c = rowcol(tf, _X0 + _SP, _Y0)
    wet[int(r), int(c)] = True
    hand[int(r) - 2:int(r) + 3, int(c) - 2:int(c) + 3] = 30.0          # the wet node is the highest: tempting
    dist = np.full(len(W.nodes), 60.0)
    cands = rt.relocation_candidates(W, wet, tf, hand, tf, [-180, -90, 180, 90], D, [], dist, 0.0)
    assert W.idx[1] not in {c["node"] for c in cands} and len(cands) == 8


def test_to_shelter_avoided_names_the_flooded_road_on_the_usual_path():
    W = _lattice(3, names={frozenset((1, 2)): "Juja Road"})
    D = _lattice(3, kph=30, drive=True)
    s = {"id": "x-s", "name": "School", "type": "school", "capacity": None, "safe": True,
         **dict(zip(("lon", "lat"), _ll(_X0 + 2 * _SP, _Y0)))}
    o = {"id": "x-o1", "name": "O", "user_type": "trader", **dict(zip(("lon", "lat"), _ll(_X0, _Y0)))}
    wet, tf = _wet([(_X0 + _SP + 150, _Y0)])                           # Juja Road flooded
    r = rt.build_routes("t", {"type": "urban", "bbox": [-180, -90, 180, 90]}, [o], [s], W, D, W.cut(wet, tf),
                        D.cut(wet, tf), {}, None, flood=(wet, tf))[0][0]
    assert r["avoided"] == ["Juja Road"] and r["safe"]["minutes"] == 20


def test_flood_masks_walk_any_depth_drive_from_0_3_m():
    d = np.array([[np.nan, 0.0, 0.01, 0.29, 0.3, 1.5]])
    walk, drive = rt.flood_masks(d)
    assert walk.tolist() == [[False, False, True, True, True, True]]
    assert drive.tolist() == [[False, False, False, False, True, True]]
    assert rt.DRIVE_CUT_M == 0.3          # NWS "12 inches of rushing water" (0.305 m), operator ruling part 2


def test_shallow_water_cuts_the_footpath_but_not_the_road():
    names = {frozenset((1, 2)): "Thika Road"}
    W = _lattice(3, names=names)
    D = _lattice(3, kph=36, names=names, drive=True)
    wet, tf = _wet([(_X0 + _SP + 150, _Y0)])
    depth = np.where(wet, 0.2, np.nan)                       # 0.2 m: a closed-depression puddle on the road
    ww, wd = rt.flood_masks(depth)
    assert W.cut(ww, tf).sum() == 2 and D.cut(wd, tf).sum() == 0
    depth = np.where(wet, 0.4, np.nan)
    assert D.cut(rt.flood_masks(depth)[1], tf).sum() == 2


def test_relocation_candidates_skip_built_cells():
    """Operator ruling part 3: on a surface DEM a roof reads as high ground; a node in a cell with a footprint is no site."""
    from rasterio.transform import rowcol
    W = _lattice(3)
    D = _lattice(3, kph=30, drive=True)
    wet, tf = _wet([])
    hand = np.full(wet.shape, 10.0)
    built = np.zeros(wet.shape, bool)
    r, c = rowcol(tf, _X0 + _SP, _Y0)
    built[int(r), int(c)] = True                                       # node 1's cell holds a building
    dist = np.full(len(W.nodes), 60.0)
    all_ = rt.relocation_candidates(W, wet, tf, hand, tf, [-180, -90, 180, 90], D, [], dist, 0.0)
    off = rt.relocation_candidates(W, wet, tf, hand, tf, [-180, -90, 180, 90], D, [], dist, 0.0, built)
    assert len(all_) == 9 and len(off) == 8 and W.idx[1] not in {c["node"] for c in off}


def test_robust_slope_pct_converts_degrees_and_takes_the_local_median():
    deg = np.full((20, 20), np.degrees(np.arctan(0.03)))      # 3 % everywhere
    deg[5, 5] = 40.0                                          # one noisy cell
    deg[10:20, 10:20] = np.degrees(np.arctan(0.2))            # a 20 % hillside
    p = rt.robust_slope_pct(deg)
    assert p[5, 5] == pytest.approx(3.0, abs=1e-3) and p[15, 15] == pytest.approx(20.0, abs=1e-3)
    assert rt.robust_slope_pct(np.full((5, 5), np.nan))[2, 2] > rt.SLOPE_MAX_PCT       # no data = not a site


def test_relocation_candidates_drop_steep_sites_and_prefer_gentle_ones():
    """UNHCR: ideally 2-4 %, not more than 10 %. Node 22 at 12 % is excluded; node 2 (3 %) beats node 20 (8 %) at equal
    HAND, walk time and access."""
    from rasterio.transform import rowcol
    W = _lattice(3)
    D = _lattice(3, kph=30, drive=True)
    wet, tf = _wet([])
    hand = np.full(wet.shape, 0.0)
    slope = np.full(wet.shape, 3.0)
    def at(node):
        r, c = rowcol(tf, _X0 + (node % 10) * _SP, _Y0 - (node // 10) * _SP); return int(r), int(c)
    for n, sl in ((2, 3.0), (20, 8.0), (22, 12.0)):
        hand[at(n)] = 10.0; slope[at(n)] = sl
    dist = np.full(len(W.nodes), 60.0)
    c = rt.relocation_candidates(W, wet, tf, hand, tf, [-180, -90, 180, 90], D, [], dist, 0.0, None, slope)
    assert [W.nodes[x["node"]] for x in c] == [2, 20]
    assert c[0]["slope_pct"] == 3.0 and c[0]["score"] > c[1]["score"]


# ---- R6 audit F6.3 / F6.4 / F6.6: the slide-facing minutes and the relocation ranking are pinned ----
def test_minutes_round_up_with_float_noise_guard():
    """F6.3 (X2): minutes are rounded UP: 570 s -> 10, 601 s -> 11, 540 s + 30 m snap at 1 m/s -> 10; but 600.0000001 s
    is 10 (float noise), not 11."""
    assert rt._minutes(570.0) == 10 and rt._minutes(601.0) == 11
    assert rt._minutes(540.0, 30.0) == 10
    assert rt._minutes(600.0000001) == 10 and rt._minutes(600.0) == 10


def test_dijkstra_uses_the_fastest_of_parallel_edges():
    """F6.3 (X4): two u->v edges, 100 s and 400 s (inserted SLOW FIRST). The time to v is 100 s and the path uses the fast one."""
    import networkx as nx
    G = nx.MultiDiGraph(crs="EPSG:4326")
    for n, x in ((1, _X0), (2, _X0 + _SP)):
        lon, lat = _ll(x, _Y0); G.add_node(n, x=lon, y=lat)
    G.add_edge(1, 2, length=_SP, travel_time=400.0, highway="track", name="Slow")
    G.add_edge(1, 2, length=_SP, travel_time=100.0, highway="primary", name="Fast")
    RG = rt.RoutingGraph(G, "EPSG:32736")
    dist, pred, used = RG.dijkstra(RG.idx[1])
    assert dist[RG.idx[2]] == pytest.approx(100.0, abs=1e-6)
    e = RG.path_edges(pred, used, RG.idx[2])
    assert len(e) == 1 and RG.w[e[0]] == 100.0


def _reloc_inputs():
    W = _lattice(3)
    D = _lattice(3, kph=30, drive=True)
    wet, tf = _wet([])
    hand = np.full(wet.shape, 10.0)                       # every node is high ground (>= 5 m), equal HAND
    return W, D, wet, tf, hand


def test_relocation_prefers_the_shorter_walk_when_all_else_is_equal():
    """F6.4 (X8): two candidates identical except walk time (10 vs 30 min); the 10-min one ranks first, by score, not
    only by the tie-break."""
    W, D, wet, tf, hand = _reloc_inputs()
    dist = np.full(len(W.nodes), np.inf)
    dist[W.idx[2]], dist[W.idx[20]] = 1800.0, 600.0       # node 20: 10 min, node 2: 30 min
    c = rt.relocation_candidates(W, wet, tf, hand, tf, [-180, -90, 180, 90], D, [], dist, 0.0)
    assert [x["node"] for x in c] == [W.idx[20], W.idx[2]]
    assert c[0]["score"] > c[1]["score"]


def test_relocation_drops_sites_beyond_the_walk_limit():
    """F6.4 (X9): RELOC_MAX_MIN = 120. A site at 121 min is no candidate; one at 119 min is."""
    W, D, wet, tf, hand = _reloc_inputs()
    dist = np.full(len(W.nodes), np.inf)
    dist[W.idx[2]], dist[W.idx[20]] = 121 * 60.0, 119 * 60.0
    c = rt.relocation_candidates(W, wet, tf, hand, tf, [-180, -90, 180, 90], D, [], dist, 0.0)
    assert [x["node"] for x in c] == [W.idx[20]]
    dist[W.idx[20]] = 121 * 60.0
    assert rt.relocation_candidates(W, wet, tf, hand, tf, [-180, -90, 180, 90], D, [], dist, 0.0) == []


def test_relocation_drops_sites_outside_the_area_bbox():
    """F6.4 (X6): only nodes inside the AOI bbox are candidates. The bbox here holds column 0 only (nodes 0, 10, 20)."""
    W, D, wet, tf, hand = _reloc_inputs()
    dist = np.full(len(W.nodes), 600.0)
    w, s = _ll(_X0 - 50, _Y0 - 2 * _SP - 50)
    e, n = _ll(_X0 + 50, _Y0 + 50)
    c = rt.relocation_candidates(W, wet, tf, hand, tf, [w, s, e, n], D, [], dist, 0.0)
    assert sorted(x["node"] for x in c) == sorted(W.idx[k] for k in (0, 10, 20))


def test_shelter_further_than_the_snap_limit_from_any_path_is_not_chosen():
    """F6.6 (X3): MAX_DEST_SNAP_M = 500. A shelter 700 m off the graph (700 s straight 'walk') would beat the in-graph
    shelter at node 22 (1,200 s); it must not be chosen. Alone, it gives no route."""
    W = _lattice(3)
    o = _ll(_X0, _Y0)                                     # node 0
    far = {"id": "far", "name": "Far", "type": "school", "safe": True}
    far["lon"], far["lat"] = _ll(_X0 - 700, _Y0)
    near = {"id": "n22", "name": "Node 22", "type": "school", "safe": True}
    near["lon"], near["lat"] = _ll(_X0 + 2 * _SP, _Y0 - 2 * _SP)
    cut = np.zeros(W.n_edges, bool)
    s, leg = rt._nearest_safe_shelter(W, o, [far, near], cut)
    assert s["id"] == "n22" and leg["minutes"] == 20
    s, why = rt._nearest_safe_shelter(W, o, [far], cut)
    assert s is None and "no safe shelter reachable" in why


# ---- R6 F6.5: cut() must not miss a flooded edge (found during E-09) ----
def test_cut_samples_every_vertex_of_the_edge_geometry():
    """A 2-node edge whose geometry bends through one corner of a wet 30 m cell. 15 m steps at fractions of the whole
    edge (the old sampling) put no sample in that cell (asserted below, so the fixture really is the failing case);
    the edge must still be cut because its vertex lies in the cell."""
    import networkx as nx
    from rasterio.transform import rowcol
    from shapely.geometry import LineString as L
    a, v, b = (_X0 + 5, _Y0 - 45), (_X0 + 33, _Y0 - 27), (_X0 + 61, _Y0 - 45)    # v is 3 m inside cell (x 30-60, y -30..0)
    G = nx.MultiDiGraph(crs="EPSG:4326")
    G.add_node(1, x=_ll(*a)[0], y=_ll(*a)[1]); G.add_node(2, x=_ll(*b)[0], y=_ll(*b)[1])
    geom = L([_ll(*a), _ll(*v), _ll(*b)])
    G.add_edge(1, 2, length=66.6, travel_time=66.6, highway="residential", geometry=geom)
    RG = rt.RoutingGraph(G, "EPSG:32736")
    wet, tf = _wet([v])
    line = L([a, v, b]); n = int(np.ceil(line.length / 15.0))
    old = [line.interpolate(t, normalized=True) for t in np.linspace(0, 1, n + 1)]
    rv, cv = rowcol(tf, *v)
    assert all(tuple(rowcol(tf, p.x, p.y)) != (rv, cv) for p in old)       # the old sampling misses this cell
    assert RG.cut(wet, tf).tolist() == [True]
    assert RG.cut(np.zeros_like(wet), tf).tolist() == [False]


def test_cut_catches_a_corner_clip_longer_than_the_sample_step():
    """F6.5 guarantee: a STRAIGHT edge clipping a wet cell's corner with a 0.81 m chord (line x' + y' = 0.57 m through
    the corner) must be cut. 2 m steps miss it (asserted, so the fixture really is the failing case); 0.5 m steps cannot."""
    import networkx as nx
    from rasterio.transform import rowcol
    from shapely.geometry import LineString as L
    cx, cy = _X0 + 30, _Y0 - 30                              # lower-left corner of the cell x 30..60, y -30..0
    a, b = (cx - 100.5, cy + 101.07), (cx + 100.57, cy - 100)
    G = nx.MultiDiGraph(crs="EPSG:4326")
    G.add_node(1, x=_ll(*a)[0], y=_ll(*a)[1]); G.add_node(2, x=_ll(*b)[0], y=_ll(*b)[1])
    G.add_edge(1, 2, length=284.4, travel_time=284.4, highway="residential")
    RG = rt.RoutingGraph(G, "EPSG:32736")
    wet, tf = _wet([(cx + 15, cy + 15)])
    rv, cv = rowcol(tf, cx + 15, cy + 15)
    xy2 = np.asarray(L([a, b]).segmentize(2.0).coords)
    assert all(tuple(rowcol(tf, x, y, op=np.floor)) != (rv, cv) for x, y in xy2)   # 2 m steps miss the clip
    assert rt.SAMPLE_STEP_M <= 0.5
    assert RG.cut(wet, tf).tolist() == [True]


def test_a_bridge_on_a_later_edge_is_exempt_where_it_is(tmp_path):
    """The bridge exemption is computed on the samples of bridge-adjacent edges only; it must land on THOSE samples. The
    bridge is edge 10-11 (bottom row), not the first edge in the sample arrays. Wet under it: not cut; wet under edge
    0-1 (no bridge): cut."""
    lon0, lat0 = _ll(_X0, _Y0 - _SP)
    lon1, lat1 = _ll(_X0 + 100, _Y0 - _SP)
    xml = tmp_path / "b.osm"
    rt.write_osm_xml(xml, {1: (lon0, lat0), 2: (lon1, lat1)}, [(9, [1, 2], {"highway": "primary", "bridge": "yes"})])
    RG = rt.RoutingGraph(_lattice(2).G, "EPSG:32736", rt.bridge_lines(xml))
    first = [i for i in range(RG.n_edges) if {RG.nodes[RG.u[i]], RG.nodes[RG.v[i]]} == {10, 11}]
    assert first and min(first) > 0 and RG.se.min() == 0     # the bridge edge is not edge 0
    wet, tf = _wet([(_X0 + 50, _Y0 - _SP)])
    assert not RG.cut(wet, tf).any()
    wet, tf = _wet([(_X0 + 50, _Y0)])
    assert RG.cut(wet, tf).sum() == 2
