"""E-18: H3 hexagon layer (pipeline/10_h3.py)."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
_s = importlib.util.spec_from_file_location("h3mod", HERE / "10_h3.py")
hm = importlib.util.module_from_spec(_s)
_s.loader.exec_module(hm)
_p = importlib.util.spec_from_file_location("pop05t", HERE / "05_population.py")
pop = importlib.util.module_from_spec(_p)
_p.loader.exec_module(pop)

h3 = pytest.importorskip("h3")
from rasterio.transform import from_origin  # noqa: E402
from pyproj import Transformer  # noqa: E402

CRS = "EPSG:32737"
TF = from_origin(257000.0, 9857000.0, 30.0, 30.0)     # Nairobi, UTM 37S; 60 x 60 cells = 1.8 km
SHAPE = (60, 60)
TO_LL = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
TO_UTM = Transformer.from_crs("EPSG:4326", CRS, always_xy=True).transform


def _centre(r, c):
    return TO_LL(TF.c + (c + 0.5) * 30.0, TF.f - (r + 0.5) * 30.0)


def test_each_cell_goes_to_the_one_hex_holding_its_centre_and_outside_the_mask_is_zero():
    mask = np.zeros(SHAPE, bool)
    mask[5:55, 3:58] = True
    hx = hm.cell_hexes(mask, TF, CRS, 9)
    assert (hx[~mask] == 0).all() and (hx[mask] != 0).all()
    rr, cc = np.nonzero(mask)                            # EVERY cell (a corner-vs-centre slip moves only border cells)
    lon, lat = TO_LL(TF.c + (cc + 0.5) * 30.0, TF.f - (rr + 0.5) * 30.0)
    assert all(h3.int_to_str(int(hx[r, c])) == h3.latlng_to_cell(la, lo, 9) for r, c, lo, la in zip(rr, cc, lon, lat))
    n = np.unique(hx[mask], return_counts=True)[1]
    assert n.sum() == mask.sum()                         # every cell once
    assert 115 < n.max() < 140 and (n > 115).sum() >= 10  # a FULL hex: ~128 cells of 900 m2 (0.116 km2); edge hexes fewer


def test_largest_remainder_hits_the_target_and_breaks_ties_by_key():
    v = np.array([1.5, 2.5, 0.25, 0.75])
    out = hm.largest_remainder(v, ["d", "a", "c", "b"], 5)
    assert out.sum() == 5 and list(out) == [1, 3, 0, 1]   # 1+2+0+0 = 3 floors; +1 to the 0.75 (b) and the 0.5 tie "a" < "d"
    assert list(hm.largest_remainder(v, ["a", "d", "c", "b"], 5)) == [2, 2, 0, 1]
    with pytest.raises(ValueError):
        hm.largest_remainder(v, list("abcd"), 9)


def test_edge_flag_is_set_only_for_a_hex_crossing_the_aoi_bbox():
    bbox = [36.80, -1.32, 36.84, -1.28]
    inner = h3.latlng_to_cell(-1.30, 36.82, 9)
    assert not hm.hex_on_edge(inner, bbox)
    on = h3.latlng_to_cell(-1.30, 36.80, 9)              # centre within ~200 m of the west edge
    assert hm.hex_on_edge(on, bbox)
    outside_bbox = [36.0, -1.0, 36.1, -0.9]
    assert hm.hex_on_edge(inner, outside_bbox)


def _buildings(points):
    """Open-Buildings-like dict: (lon, lat, area_m2, conf) rows; threshold 0.85 for precision "85"."""
    a = np.array(points, float)
    return {"lon": a[:, 0], "lat": a[:, 1], "area_m2": a[:, 2], "conf": a[:, 3], "thr85": np.float64(0.85)}


def _scene():
    """AOI = the whole 60x60 grid; county 1 left half (factors), county 2 right half (no factors -> A). Wet: a 10x12
    block straddling hexes, depths 0.05..1.6 m. Buildings: 6 wet (one below the confidence threshold), 3 dry."""
    mask = np.ones(SHAPE, bool)
    county = np.ones(SHAPE, np.int32); county[:, 30:] = 2
    depth = np.full(SHAPE, np.nan)
    rr, cc = np.mgrid[20:30, 24:36]
    depth[rr, cc] = 0.05 + (rr - 20) * 0.17                  # rows 20..29 -> 0.05 .. 1.58 m
    pts = []
    for (r, c, area, conf) in ((21, 25, 100, 0.9), (22, 26, 50, 0.95), (28, 34, 200, 0.9), (29, 35, 80, 0.99),
                               (25, 30, 120, 0.9), (26, 31, 60, 0.70),                 # last one: conf < 0.85
                               (5, 5, 300, 0.9), (50, 50, 90, 0.9), (40, 10, 150, 0.9)):
        lon, lat = TO_LL(TF.c + (c + 0.3) * 30.0, TF.f - (r + 0.6) * 30.0)
        pts.append((lon, lat, area, conf))
    man = {"factors_A": {"low": 1.1, "medium": 1.2, "high": 1.3},
           "counties": [{"id": 1, "factors": {"low": 1.5, "medium": 1.6, "high": 1.7}, "worldpop_aoi_2020": 1000.0},
                        {"id": 2, "worldpop_aoi_2020": 400.0}]}
    return mask, county, depth, _buildings(pts), man


def test_aggregate_sums_equal_the_exposure_functions_and_each_row_is_right():
    mask, county, depth, b, man = _scene()
    hexes = hm.cell_hexes(mask, TF, CRS, 9)
    wet = np.isfinite(depth) & (depth > 0)
    r, c, ok, ppl = hm.building_people(b, county, mask, TF, CRS, man, "B", "85")
    target = pop.exposed_building_weighted(b, wet, county, mask, TF, CRS, man, "85")["B"]
    nb = pop.buildings_in_wet(b, wet, TF, CRS, "85")
    assert nb == 5
    bbox = [*TO_LL(TF.c, TF.f - 1800), *TO_LL(TF.c + 1800, TF.f)]
    rows = hm.aggregate(depth, hexes, 900.0, (r, c, ok), ppl, target, bbox)
    for s in ("low", "medium", "high"):
        assert sum(x[f"people_{s}"] for x in rows) == target[s]
    assert sum(x["buildings_flooded"] for x in rows) == nb
    assert sum(x["flooded_m2"] for x in rows) == int(wet.sum()) * 900
    # every written hex has a wet cell, and every hex with a wet cell is written
    assert {x["h3"] for x in rows} == {h3.int_to_str(int(h)) for h in np.unique(hexes[wet])}
    # one row by hand
    x = rows[0]
    sel = hexes == h3.str_to_int(x["h3"])
    dw = depth[sel & wet]
    assert x["flooded_share"] == round(len(dw) / int(sel.sum()), 3)
    assert x["depth_mean_m"] == round(float(dw.mean()), 2) and x["depth_max_m"] == round(float(dw.max()), 2)
    cls = {1: "low", 2: "medium", 3: "high"}[1 if dw.max() < 0.3 else 2 if dw.max() <= 1.0 else 3]
    assert x["risk"] == cls
    # a high hex exists (rows 27..29 are > 1.0 m) and risk follows the hex's DEEPEST cell, not its mean
    hi = [x for x in rows if x["risk"] == "high"]
    assert hi and all(x["depth_max_m"] > 1.0 for x in hi) and any(x["depth_mean_m"] <= 1.0 for x in hi)


def test_building_people_matches_the_writer_rule_before_rounding():
    mask, county, depth, b, man = _scene()
    wet = np.isfinite(depth) & (depth > 0)
    r, c, ok, ppl = hm.building_people(b, county, mask, TF, CRS, man, "B", "85")
    bw = np.zeros(len(r), bool); bw[ok] = wet[r[ok], c[ok]]
    for mode, f1, f2 in (("B", man["counties"][0]["factors"], man["factors_A"]),):
        # county 1: 1000 x factor x wet-area share; county 2 (no factors): 400 x A factor x share
        a = b["area_m2"][b["conf"] >= 0.85]
        cid = county[r, c]
        exp_low = (1000 * f1["low"] * a[(cid == 1) & bw].sum() / a[cid == 1].sum()
                   + 400 * f2["low"] * a[(cid == 2) & bw].sum() / a[cid == 2].sum())
        assert ppl[bw, 0].sum() == pytest.approx(exp_low, rel=1e-12)
    assert ppl.sum(axis=0) == pytest.approx([1000 * 1.5 + 400 * 1.1, 1000 * 1.6 + 400 * 1.2, 1000 * 1.7 + 400 * 1.3])


def test_node_best_takes_the_lowest_minutes_over_the_hexs_walk_nodes():
    """Two walk nodes in hex H (field: 610 s + 0 m snap -> 11 min to sB; 300 s + 120 m -> 7 min to sA) and one in hex K
    (unreached: absent from the field). H -> (7, "sA"); K has no entry (its row would say shelter_reachable false)."""
    g = {"walk_kph": 3.6, "nodes": [], "walk": {"edges": []}}
    field = {0: (0.0, "sB", 6100, 0.0), 1: (0.0, "sA", 3000, 120.0), 7: (0.0, "sC", 100, 0.0)}
    node_hex = {0: "H", 1: "H", 2: "K"}
    assert hm.node_best(g, field, node_hex) == {"H": (7, "sA")}
    field[0] = (0.0, "sB", 4200, 0.0)                      # 420 s = 7 min: a tie on minutes -> shelter id "sA" < "sB"
    assert hm.node_best(g, field, node_hex)["H"] == (7, "sA")


def test_people_integers_use_largest_remainder_not_plain_rounding():
    """Each hex holding wet buildings gets exactly 0.4 people in all (shared by its buildings): plain rounding writes 0
    everywhere, but the total 0.4 x hexes rounds to >= 1; the written integers must sum to that target."""
    mask, county, depth, b, man = _scene()
    hexes = hm.cell_hexes(mask, TF, CRS, 9)
    r, c, ok, _ = hm.building_people(b, county, mask, TF, CRS, man, "B", "85")
    wet = np.isfinite(depth) & (depth > 0)
    bw = np.zeros(len(r), bool); bw[ok] = wet[r[ok], c[ok]]
    hb = np.zeros(len(r), np.uint64); hb[bw] = hexes[r[bw], c[bw]]
    n_in = {h: int((hb[bw] == h).sum()) for h in np.unique(hb[bw])}
    ppl = np.array([0.4 / n_in[h] if w else 0.0 for h, w in zip(hb, bw)])[:, None] * np.ones((1, 3))
    exact = np.full(len(n_in), 0.4)
    assert len(n_in) >= 2
    target = int(round(exact.sum()))
    assert np.round(exact).sum() != target                    # precondition: plain rounding would miss
    bbox = [*TO_LL(TF.c, TF.f - 1800), *TO_LL(TF.c + 1800, TF.f)]
    rows = hm.aggregate(depth, hexes, 900.0, (r, c, ok), ppl, dict.fromkeys(("low", "medium", "high"), target), bbox)
    assert sum(x["people_low"] for x in rows) == target


def test_rural_area_without_relocation_targets_gets_null_shelter_fields_with_a_reason():
    """RULING R19 (2): rural + no shelter of kind "relocation" in graph.json -> null with the stated reason; urban, or
    rural once relocation targets exist (E-19), -> computed."""
    g = {"shelters": [{"id": "s1"}]}
    assert hm.shelter_null_reason({"type": "rural"}, g) == "relocation sites not yet in graph"
    assert hm.shelter_null_reason({"type": "urban"}, g) is None
    assert hm.shelter_null_reason({"type": "rural"}, {"shelters": [{"id": "r1", "kind": "relocation"}]}) is None


def test_no_route_class_inside_flood_vs_cut_off_outside_flood():
    assert hm.no_route_class([5, 6], live={1, 2}) == "inside_flood"
    assert hm.no_route_class([5, 2], live={1, 2}) == "cut_off_outside_flood"


def test_fill_shelter_fields_two_kinds_min_over_nodes_and_no_route_split():
    """On the 4-lattice (one scenario "a"): shelter s at node 0, high ground hg at node 3. Node 33 has both edges cut
    (in the flood); nodes 30-31 form a dry island (20-30, 21-31, 31-32 cut). Fake hex ids map nodes to hexes."""
    import importlib.util as iu
    sp = iu.spec_from_file_location("rtt", HERE / "06_routing.py"); rt = iu.module_from_spec(sp); sp.loader.exec_module(rt)
    tsp = iu.spec_from_file_location("trt", HERE / "tests" / "test_routing.py"); tr = iu.module_from_spec(tsp); tsp.loader.exec_module(tr)
    W, D = tr._lattice(4), tr._lattice(4, drive=True)
    g = tr._client_graph(W, D, cut_pairs=[(32, 33), (23, 33), (20, 30), (21, 31), (31, 32)], shelters=[("s", 0), ("hg", 3)])
    g["shelters"][1]["kind"] = "relocation"
    ids = sorted(W.nodes)
    nh = {ids.index(1): "H1", ids.index(2): "H1", ids.index(33): "Hdead", ids.index(30): "Hisl", ids.index(31): "Hisl"}
    rows = [{"h3": h} for h in ("H1", "Hdead", "Hisl")]
    hm.fill_shelter_fields(rows, g, "a", nh, set(nh.values()))
    r = {x["h3"]: x for x in rows}
    assert (r["H1"]["walk_min"], r["H1"]["shelter_id"]) == (5, "s")           # node 1 -> 0: 300 s
    assert (r["H1"]["relocation_walk_min"], r["H1"]["relocation_id"]) == (5, "hg")   # node 2 -> 3: 300 s
    assert r["H1"]["shelter_reachable"] and r["H1"]["no_route"] is None
    assert not r["Hdead"]["shelter_reachable"] and r["Hdead"]["no_route"] == "inside_flood"
    assert not r["Hisl"]["shelter_reachable"] and r["Hisl"]["no_route"] == "cut_off_outside_flood"


def test_hex_walk_min_is_the_primary_route_at_penalty_1():
    """RULING R20 (b): node 2 -> shelter at node 0 is 600 s straight on near-flood edges (0-1, 1-2): the primary is 10
    min. At x3 the dry detour 2-12-11-10-0 (1,200 s = 20 min) would win, so a penalty-3 hex field would say 20."""
    import importlib.util as iu
    sp = iu.spec_from_file_location("trt2", HERE / "tests" / "test_routing.py"); tr = iu.module_from_spec(sp); sp.loader.exec_module(tr)
    W, D = tr._lattice(4), tr._lattice(4, drive=True)
    g = tr._client_graph(W, D, near_pairs=[(0, 1), (1, 2)], shelters=[("s", 0)])
    nh = {sorted(W.nodes).index(2): "H2"}
    rows = [{"h3": "H2"}]
    hm.fill_shelter_fields(rows, g, "a", nh, {"H2"})
    assert (rows[0]["walk_min"], rows[0]["shelter_id"]) == (10, "s") and "relocation_walk_min" not in rows[0]


def test_hex_arrival_fields_earliest_fast_band_and_people_by_band():
    """E-20: fast = column index x 0.2 h (cols 24..35 -> 4.8..7.0 h), slow = fast x 2.44. Per hex: arrival_h_min = the
    earliest fast hours over its WET cells, arrival_band_min its band, arrival_h_min_slow = that x 2.44 (same cell),
    people_medium_by_band sums to people_medium and holds only bands of the hex's wet buildings' cells."""
    import importlib.util as iu
    sp = iu.spec_from_file_location("sc07t", HERE / "07_scenarios.py"); sc = iu.module_from_spec(sp); sp.loader.exec_module(sc)
    mask, county, depth, b, man = _scene()
    hexes = hm.cell_hexes(mask, TF, CRS, 9)
    r, c, ok, ppl = hm.building_people(b, county, mask, TF, CRS, man, "B", "85")
    wet = np.isfinite(depth) & (depth > 0)
    target = pop.exposed_building_weighted(b, wet, county, mask, TF, CRS, man, "85")["B"]
    fast = np.tile(np.arange(SHAPE[1]) * 0.2, (SHAPE[0], 1))
    slow = fast * 2.44
    bbox = [*TO_LL(TF.c, TF.f - 1800), *TO_LL(TF.c + 1800, TF.f)]
    rows = hm.aggregate(depth, hexes, 900.0, (r, c, ok), ppl, target, bbox, (fast, slow))
    for x in rows:
        sel = (hexes == h3.str_to_int(x["h3"])) & wet
        assert x["arrival_h_min"] == round(float(fast[sel].min()), 2)
        assert x["arrival_h_min_slow"] == round(float(slow[sel].min()), 2)
        assert x["arrival_band_min"] == ("<1", "1-3", "3-6", ">6")[int(sc.classify_arrival_band(np.array([x["arrival_h_min"]]))[0])]
        assert sum(x["people_medium_by_band"].values()) == x["people_medium"]
    assert {k for x in rows for k, v in x["people_medium_by_band"].items() if v} <= {"3-6", ">6"}
    assert sum(x["people_medium"] for x in rows) == target["medium"]
    # E-20 F-A10/A11: recompute each hex's split independently: wet buildings, their FAST band (slow x2.44 would put
    # every cell in ">6"), fractional medium people, then floors + 1 to the largest fractional parts (not plain rounding)
    bw = ok & wet[r, c]
    band = np.digitize(fast[r[bw], c[bw]], [1.0, 3.0, 6.0 + 1e-9])
    names = ["<1", "1-3", "3-6", ">6"]
    for x in rows:
        sel = hexes[r[bw], c[bw]] == h3.str_to_int(x["h3"])
        frac = np.array([ppl[bw][sel & (band == k), 1].sum() for k in range(4)])
        fl = np.floor(frac).astype(int)
        for i in sorted(range(4), key=lambda i: -(frac[i] - fl[i]))[: x["people_medium"] - fl.sum()]:
            fl[i] += 1
        assert [x["people_medium_by_band"].get(n, 0) for n in names] == fl.tolist(), x["h3"]
    assert sum(x["people_medium_by_band"].get("3-6", 0) for x in rows) > 0


def test_hex_people_by_band_is_largest_remainder_not_rounding():
    """F-A11: one hex, three wet buildings of 0.30 / 0.45 / 0.25 people in bands <1, 1-3, 3-6; people_medium 1. Plain
    rounding gives 0+0+0 = 0 != 1; largest remainder gives the 1 to the largest fraction (1-3)."""
    wet = np.ones((1, 3), bool)
    fast = np.array([[0.5, 2.0, 4.0]])
    rows = [{"h3": "x", "people_medium": 1}]
    hm.add_arrival_fields(rows, np.array([7]), np.zeros(3, np.int64), wet, (fast, fast * 2.44),
                          np.zeros(3, np.int64), np.array([0.30, 0.45, 0.25]), np.zeros(3, np.int64), np.arange(3))
    assert rows[0]["people_medium_by_band"] == {"<1": 0, "1-3": 1, "3-6": 0, ">6": 0}
    assert rows[0]["arrival_h_min"] == 0.5 and rows[0]["arrival_band_min"] == "<1" and rows[0]["arrival_h_min_slow"] == 1.22


def test_relocation_only_hex_is_reachable_with_no_no_route_class():
    """F20.4 (ruling R20-c: shelter_reachable = EITHER answer exists). The 4-lattice is cut between columns 1 and 2
    ((1,2), (11,12), (21,22), (31,32)): node 2 reaches the high ground hg at node 3 (300 s = 5 min) but never the
    shelter s at node 0. Its hex must be reachable with no_route null, not "shelter in place / 1199"."""
    import importlib.util as iu
    tsp = iu.spec_from_file_location("trt3", HERE / "tests" / "test_routing.py"); tr = iu.module_from_spec(tsp); tsp.loader.exec_module(tr)
    W, D = tr._lattice(4), tr._lattice(4, drive=True)
    g = tr._client_graph(W, D, cut_pairs=[(1, 2), (11, 12), (21, 22), (31, 32)], shelters=[("s", 0), ("hg", 3)])
    g["shelters"][1]["kind"] = "relocation"
    nh = {sorted(W.nodes).index(2): "Hrel"}
    rows = [{"h3": "Hrel"}]
    hm.fill_shelter_fields(rows, g, "a", nh, {"Hrel"})
    x = rows[0]
    assert (x["walk_min"], x["shelter_id"]) == (None, None)
    assert (x["relocation_walk_min"], x["relocation_id"]) == (5, "hg")
    assert x["shelter_reachable"] is True and x["no_route"] is None


def test_hex_band_comes_from_the_unrounded_minimum():
    """F21.1: earliest wet cell 0.996 h -> displayed arrival_h_min 1.0 (2 dp) but band "<1" (under one hour), never
    "1-3" (the unsafe side). A 6.004 h hex displays 6.0 and is ">6"."""
    wet = np.ones((1, 4), bool)
    fast = np.array([[0.996, 1.5, 6.004, 7.0]])
    inv = np.array([0, 0, 1, 1])
    rows = [{"h3": "a", "people_medium": 0}, {"h3": "b", "people_medium": 0}]
    hm.add_arrival_fields(rows, np.array([1, 2]), inv, wet, (fast, fast * 2.44), np.zeros(0, np.int64), None,
                          np.zeros(0, np.int64), np.zeros(0, np.int64))
    assert (rows[0]["arrival_h_min"], rows[0]["arrival_band_min"]) == (1.0, "<1")
    assert (rows[1]["arrival_h_min"], rows[1]["arrival_band_min"]) == (6.0, ">6")
