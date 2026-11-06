#!/usr/bin/env python
"""06_routing.py — OSM road graphs, travel times and shelter candidates per area (E-02).

Source: Geofabrik Kenya extract (a fixed, dated OSM snapshot, md5-checked) rather than live Overpass,
so the run is reproducible and citable ("© OpenStreetMap contributors, extract <date>").

  prepare --area <a> [--area <b>]   one pass over the PBF ->
      $RMS_DATA/raw/osm/<area>_{drive,walk}.osm                 ways matching osmnx's own network filters
      $RMS_DATA/processed/<area>/exposure/graph_{drive,walk}.graphml   with speed_kph, travel_time (s)
      $RMS_DATA/processed/<area>/exposure/shelter_candidates.geojson   points, WGS84, mapped `type`
      $RMS_DATA/processed/<area>/exposure/osm_manifest.json      counts, assumptions, source

Area bbox comes from web/public/data/areas.json (operator-ruled; Nyando west edge 34.80).

TRAVEL-TIME ASSUMPTIONS (stated, with sources):
  * Walking: 1.0 m/s = 3.6 km/h. FHWA-HRT-98-107 (1998), "Capacity Analysis of Pedestrian and Bicycle
    Facilities", §2.2: 1.2 m/s for most conditions, 1.0 m/s "when the percentage of elderly using the
    facility ... exceeds 20 percent". https://www.fhwa.dot.gov/publications/research/safety/pedbike/98107/section2.cfm
    We take the slower value: an evacuating household moves with children, elderly and belongings. CHOICE.
  * Driving: an OSM `maxspeed` tag is used where present (osmnx add_edge_speeds). Untagged edges get the
    per-class value in HWY_KPH (ASSUMPTION, free-flow, not congested — real Nairobi travel is slower).
    Urban areas (Nairobi) cap untagged edges at 50 km/h: Traffic Act Cap 403 s.42(3), no vehicle "at a speed
    exceeding fifty kilometres per hour" on "any road within the boundaries of any trading centre, township,
    municipality or city". https://www.sheriaplex.com/kenya-acts/3100-section-42-speed-of-motor-vehicles
  * HWY_KPH (rural untagged) has NO source for free-flow speeds; the only sourced bounds are legal maxima
    (single-carriage highway 100 km/h, dual 110 km/h, PSV/commercial 80 km/h; GRSP 2015 below), and every HWY_KPH value
    is at or below them. LIMITATION: Cap 403 s.42(3) also limits roads "within ... any trading centre, township" to
    50 km/h; the rural AOI does NOT apply that inside Ahero/Awasi etc., so rural drive minutes through towns are
    optimistic. Recorded in osm_manifest.json "speed_limitations" for the limitations slide (E-08).
  * Graph simplification merges consecutive ways into one edge; when their classes differ osmnx returns
    `highway` as a list in set order (changes with PYTHONHASHSEED). Such an edge is timed as its SLOWEST class
    (slowest_class; CHOICE, conservative), the full set kept in `highway_merged`, so builds are reproducible (F3.13).
  * A tagged maxspeed above 110 km/h is a tagging error (e.g. OSM way 262775043, a residential street tagged
    "120 mph") and gets the class value instead. 110 km/h is the highest limit, for private vehicles on dual-
    carriage highways, per the Traffic Act and Traffic (Speed Limit) Rules as summarised by GRSP (2015, secondary):
    https://www.grsproadsafety.org/wp-content/uploads/2023/03/Kenya-s-speeding-laws-call-for-review-.pdf
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
from xml.sax.saxutils import quoteattr

REPO = Path(__file__).resolve().parents[1]
PBF_NAME = "kenya-261104.osm.pbf"
PBF_URL = "https://download.geofabrik.de/africa/kenya-261104.osm.pbf"
BUFFER_DEG = 0.02  # graph extends ~2 km past the bbox so routes near the edge are not cut

WALK_KPH = 3.6
URBAN_CAP_KPH = 50.0
MAX_TAGGED_KPH = 110.0
# ASSUMPTION: free-flow speeds for edges without a maxspeed tag (km/h)
HWY_KPH = {
    "motorway": 80, "motorway_link": 50, "trunk": 80, "trunk_link": 50, "primary": 60, "primary_link": 40,
    "secondary": 50, "secondary_link": 40, "tertiary": 40, "tertiary_link": 30, "unclassified": 30,
    "residential": 25, "living_street": 15, "road": 25, "busway": 40,
}
FALLBACK_KPH = 25.0

# OSM tag -> contract shelter type. "police" is cached but has NO contract type (not emitted to the app).
SHELTER_TAGS = {
    ("amenity", "school"): "school",
    ("amenity", "place_of_worship"): "church",
    ("amenity", "hospital"): "hospital",
    ("amenity", "clinic"): "hospital",
    ("healthcare", "hospital"): "hospital",
    ("healthcare", "clinic"): "hospital",
    ("amenity", "community_centre"): "community_hall",
    ("amenity", "police"): "police",
}


def rms_data() -> Path:
    return Path(os.environ.get("RMS_DATA", "/Users/mac/IGAD/data"))


def load_area(area: str, data_dir: Path | None = None) -> dict:
    data_dir = data_dir or REPO / "web" / "public" / "data"
    for a in json.loads((data_dir / "areas.json").read_text()):
        if a["id"] == area:
            return a
    raise SystemExit(f"area {area!r} not in areas.json")


# ---------------------------------------------------------------------------------------------
# osmnx network filters, applied to PBF ways with the same semantics as Overpass
# ---------------------------------------------------------------------------------------------

_CLAUSE = re.compile(r'\["([^"]+)"(?:(!?~)"([^"]*)")?\]')


def parse_overpass_filter(flt: str) -> list[tuple[str, str | None, re.Pattern | None]]:
    """'["highway"]["access"!~"private"]' -> [("highway", None, None), ("access", "!~", re)].
    Only the clause forms osmnx uses (key exists, key !~ regex, key ~ regex) are supported."""
    clauses = _CLAUSE.findall(flt)
    if "".join(f'["{k}"' + (f'{op}"{v}"' if op else "") + "]" for k, op, v in clauses) != flt.replace(" ", ""):
        raise ValueError(f"unsupported filter syntax: {flt}")
    return [(k, op or None, re.compile(v) if op else None) for k, op, v in clauses]


def way_passes(tags: dict, rules) -> bool:
    """Overpass semantics: ["k"] needs the key; ["k"!~"re"] passes if the key is absent or no match
    (unanchored search); ["k"~"re"] needs the key and a match."""
    for k, op, rx in rules:
        v = tags.get(k)
        if op is None:
            if v is None:
                return False
        elif op == "!~":
            if v is not None and rx.search(v):
                return False
        elif op == "~":
            if v is None or not rx.search(v):
                return False
    return True


def network_rules(network_type: str):
    from osmnx import _overpass
    return parse_overpass_filter(_overpass._get_network_filter(network_type))


def shelter_type(tags: dict) -> str | None:
    for (k, v), t in SHELTER_TAGS.items():
        if tags.get(k) == v:
            return t
    return None


# ---------------------------------------------------------------------------------------------
# PBF -> per-area XML + shelter candidates (one pass for all areas)
# ---------------------------------------------------------------------------------------------

def write_osm_xml(path: Path, nodes: dict[int, tuple[float, float]], ways: list[tuple[int, list[int], dict]]) -> None:
    """Minimal OSM XML that osmnx.graph_from_xml reads. nodes: id -> (lon, lat)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" generator="06_routing.py">\n')
        for nid, (lon, lat) in nodes.items():
            f.write(f'<node id="{nid}" lat="{lat:.7f}" lon="{lon:.7f}"/>\n')
        for wid, refs, tags in ways:
            f.write(f'<way id="{wid}">')
            f.writelines(f'<nd ref="{r}"/>' for r in refs)
            f.writelines(f"<tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in tags.items())
            f.write("</way>\n")
        f.write("</osm>\n")


def extract(pbf: Path, areas: dict[str, list[float]]) -> dict:
    """areas: id -> bbox. Returns id -> {"drive"/"walk": (nodes, ways), "shelters": [...]}"""
    import osmium
    from shapely.geometry import MultiPolygon, Polygon

    rules = {"drive": network_rules("drive"), "walk": network_rules("walk")}
    buf = {a: (b[0] - BUFFER_DEG, b[1] - BUFFER_DEG, b[2] + BUFFER_DEG, b[3] + BUFFER_DEG) for a, b in areas.items()}
    out = {a: {"drive": ({}, []), "walk": ({}, []), "shelters": []} for a in areas}

    def inside(lon, lat, bb):
        return bb[0] <= lon <= bb[2] and bb[1] <= lat <= bb[3]

    n_seen = 0
    fp = osmium.FileProcessor(str(pbf)).with_locations().with_areas()
    for obj in fp:
        n_seen += 1
        tags = None
        if obj.is_node():
            if not len(obj.tags):
                continue
            tags = dict(obj.tags)
            st = shelter_type(tags)
            if st:
                lon, lat = obj.location.lon, obj.location.lat
                for a, bb in areas.items():
                    if inside(lon, lat, bb):
                        out[a]["shelters"].append({"osm": f"n{obj.id}", "type": st, "lon": lon, "lat": lat,
                                                   "area_m2": None, "tags": tags})
        elif obj.is_way():
            if "highway" not in obj.tags:
                continue
            tags = dict(obj.tags)
            try:
                pts = [(n.ref, n.lon, n.lat) for n in obj.nodes]
            except osmium.InvalidLocationError:
                continue  # node outside the extract
            for a, bb in buf.items():
                if not any(inside(lon, lat, bb) for _, lon, lat in pts):
                    continue
                for nt in ("drive", "walk"):
                    if way_passes(tags, rules[nt]):
                        nodes, ways = out[a][nt]
                        for ref, lon, lat in pts:
                            nodes[ref] = (lon, lat)
                        ways.append((obj.id, [p[0] for p in pts], tags))
        elif obj.is_area():
            tags = dict(obj.tags)
            st = shelter_type(tags)
            if not st:
                continue
            try:
                polys = [Polygon([(n.lon, n.lat) for n in ring],
                                 [[(n.lon, n.lat) for n in inner] for inner in obj.inner_rings(ring)])
                         for ring in obj.outer_rings()]
            except osmium.InvalidLocationError:
                continue
            geom = MultiPolygon(polys) if len(polys) > 1 else polys[0]
            c = geom.representative_point()  # inside the footprint, unlike a centroid of an L-shape
            src = f"w{obj.orig_id()}" if obj.from_way() else f"r{obj.orig_id()}"
            for a, bb in areas.items():
                if inside(c.x, c.y, bb):
                    out[a]["shelters"].append({"osm": src, "type": st, "lon": c.x, "lat": c.y, "geom": geom,
                                               "area_m2": None, "tags": tags})
    out["_objects_read"] = n_seen
    return out


def dedupe_shelters(sh: list[dict]) -> tuple[list[dict], int]:
    """Drop a node shelter that lies inside an area shelter of the same type (same facility mapped twice)."""
    from shapely.geometry import Point
    from shapely.strtree import STRtree
    areas = [s for s in sh if "geom" in s]
    if not areas:
        return sh, 0
    tree = STRtree([s["geom"] for s in areas])
    keep, dropped = [], 0
    for s in sh:
        if "geom" not in s:
            hits = tree.query(Point(s["lon"], s["lat"]), predicate="within")
            if any(areas[i]["type"] == s["type"] for i in hits):
                dropped += 1
                continue
        keep.append(s)
    return keep, dropped


# ---------------------------------------------------------------------------------------------
# graphs + travel times
# ---------------------------------------------------------------------------------------------

def add_travel_times(G, network_type: str, urban: bool):
    """speed_kph and travel_time (s) on every edge. See module docstring for the assumptions."""
    import osmnx as ox
    if network_type == "walk":
        for _, _, d in G.edges(data=True):
            d["speed_kph"] = WALK_KPH
            d["speed_src"] = "walk"
    else:
        hwy = {k: (min(v, URBAN_CAP_KPH) if urban else v) for k, v in HWY_KPH.items()}
        for _, _, d in G.edges(data=True):
            if isinstance(d.get("highway"), list):  # F3.13: merged ways come back in set order; fix the class first
                d["highway_merged"] = ";".join(sorted(set(d["highway"])))
                d["highway"] = slowest_class(d["highway"])
        G = ox.routing.add_edge_speeds(G, hwy_speeds=hwy, fallback=FALLBACK_KPH)
        for _, _, d in G.edges(data=True):
            tag = d.get("maxspeed")
            if parsed_maxspeed(tag) is not None:
                d["speed_src"] = "maxspeed"
            else:  # untagged, or a tag osmnx cannot parse (e.g. "80-110") -> osmnx used the class value
                d["speed_src"] = "maxspeed_unparsed" if tag else "class"
            if d["speed_kph"] > MAX_TAGGED_KPH:  # only a tag can exceed it; class values are all lower
                h = d.get("highway")
                h = h[0] if isinstance(h, list) else h
                d["speed_kph"] = float(hwy.get(h, FALLBACK_KPH))
                d["speed_src"] = "tag_invalid"
    return ox.routing.add_edge_travel_times(G)


def slowest_class(classes) -> str:
    """The one class a merged (list-valued) edge is timed as: the slowest by HWY_KPH, unknown classes at
    FALLBACK_KPH, ties by name. Conservative and independent of list order (osmnx builds the list from a set,
    so its order changes with PYTHONHASHSEED and element [0] made travel times non-reproducible, F3.13)."""
    return min(set(classes), key=lambda k: (HWY_KPH.get(k, FALLBACK_KPH), k))


def parsed_maxspeed(tag):
    """The km/h value osmnx derives from a maxspeed tag (a list after simplification), or None."""
    from osmnx import routing as r
    if isinstance(tag, list):
        return r._collapse_multiple_maxspeed_values(tag, np.mean)
    return r._clean_maxspeed(tag) if isinstance(tag, str) else None


def build_graph(xml: Path, network_type: str, bbox_buf, urban: bool):
    import osmnx as ox
    G = ox.graph_from_xml(xml, bidirectional=(network_type == "walk"), simplify=True, retain_all=True)
    G = ox.truncate.truncate_graph_bbox(G, bbox_buf)
    # drive: strongly connected, so a one-way cannot strand a route; walk is bidirectional anyway
    G = ox.truncate.largest_component(G, strongly=(network_type == "drive"))
    return add_travel_times(G, network_type, urban)


def graph_stats(G) -> dict:
    import collections
    km = sum(d["length"] for _, _, d in G.edges(data=True)) / 1000
    src = collections.Counter(d.get("speed_src") for _, _, d in G.edges(data=True))
    return {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "edge_km": round(float(km), 1),
            "speed_src": dict(src)}


# ---------------------------------------------------------------------------------------------

def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_prepare(args) -> int:
    import osmnx as ox
    pbf = Path(args.pbf or rms_data() / "raw" / "osm" / PBF_NAME)
    md5_file = pbf.with_suffix(pbf.suffix + ".md5")
    digest = md5(pbf)
    expected = md5_file.read_text().split()[0] if md5_file.exists() else None
    print(f"pbf {pbf} md5 {digest} expected {expected}")
    if expected and digest != expected:
        print("ERROR: PBF checksum mismatch", file=sys.stderr)
        return 1
    meta = {a: load_area(a) for a in args.area}
    t0 = time.time()
    ex = extract(pbf, {a: m["bbox"] for a, m in meta.items()})
    print(f"read {ex['_objects_read']} OSM objects in {time.time() - t0:.0f} s")
    for a, m in meta.items():
        b = m["bbox"]
        bbox_buf = (b[0] - BUFFER_DEG, b[1] - BUFFER_DEG, b[2] + BUFFER_DEG, b[3] + BUFFER_DEG)
        urban = m["type"] == "urban"
        outd = rms_data() / "processed" / a / "exposure"
        outd.mkdir(parents=True, exist_ok=True)
        manifest = {"area": a, "bbox": b, "buffer_deg": BUFFER_DEG, "source": PBF_URL, "pbf_md5": digest,
                    "osm_copyright": "© OpenStreetMap contributors (ODbL)", "walk_kph": WALK_KPH,
                    "hwy_kph_untagged": {k: (min(v, URBAN_CAP_KPH) if urban else v) for k, v in HWY_KPH.items()},
                    "urban_cap_kph": URBAN_CAP_KPH if urban else None,
                    "max_tagged_kph": MAX_TAGGED_KPH,
                    "speed_model": "free-flow, uncongested: drive minutes understate real travel time (no sourced congestion factor)",
                    "speed_limitations": [
                        "drive speeds are free-flow; real travel (trucks, matatus, market days, wet roads) is slower",
                        "rural untagged class speeds (hwy_kph_untagged) are assumptions with no source beyond legal maxima",
                        "Cap 403 s.42(3) 50 km/h in trading centres/townships is applied only to urban Nairobi, not to towns "
                        "inside the rural AOI, so rural drive minutes through towns are optimistic",
                    ] if not urban else [
                        "drive speeds are free-flow; real Nairobi travel is slower",
                        "untagged edges capped at 50 km/h (Cap 403 s.42(3)); tagged edges use OSM maxspeed",
                    ],
                    "graphs": {}}
        for nt in ("drive", "walk"):
            nodes, ways = ex[a][nt]
            xml = rms_data() / "raw" / "osm" / f"{a}_{nt}.osm"
            write_osm_xml(xml, nodes, ways)
            G = build_graph(xml, nt, bbox_buf, urban)
            ox.save_graphml(G, outd / f"graph_{nt}.graphml")
            st = graph_stats(G)
            st["osm_ways_in"] = len(ways)
            manifest["graphs"][nt] = st
            print(f"{a} {nt}: {len(ways)} ways in -> {st}")
        sh, dropped = dedupe_shelters(ex[a]["shelters"])
        feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(s["lon"], 6), round(s["lat"], 6)]},
                  "properties": {"osm": s["osm"], "type": s["type"], "name": s["tags"].get("name"),
                                 "religion": s["tags"].get("religion"),
                                 "osm_tag": next(f"{k}={v}" for (k, v) in SHELTER_TAGS if s["tags"].get(k) == v)}}
                 for s in sh]
        (outd / "shelter_candidates.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
        import collections
        by_type = collections.Counter(f["properties"]["type"] for f in feats)
        named = collections.Counter(f["properties"]["type"] for f in feats if f["properties"]["name"])
        worship = collections.Counter(f["properties"]["religion"] for f in feats if f["properties"]["type"] == "church")
        by_tag = collections.Counter(f["properties"]["osm_tag"] for f in feats)
        manifest["shelters"] = {"by_type": dict(by_type), "named_by_type": dict(named), "by_osm_tag": dict(by_tag),
                                "type_note": "contract type 'hospital' = health facilities: amenity=hospital + amenity=clinic + "
                                             "healthcare=hospital|clinic; see by_osm_tag. Do not call the total 'hospitals'.",
                                "place_of_worship_by_religion": dict(worship), "node_duplicates_dropped": dropped}
        (outd / "osm_manifest.json").write_text(json.dumps(manifest, indent=1))
        print(f"{a} shelters: {dict(by_type)}  named: {dict(named)}  worship religion: {dict(worship)}  "
              f"node duplicates dropped: {dropped}  by OSM tag: {dict(by_tag)}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("prepare")
    s.add_argument("--area", action="append", required=True, choices=["nairobi", "nyando"])
    s.add_argument("--pbf", default=None)
    s.set_defaults(fn=cmd_prepare)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
