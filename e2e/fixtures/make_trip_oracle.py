"""M-16 second method for FROM -> TO: shortest walking time by scipy.sparse.csgraph.dijkstra on graph.json, with its own
snapping (pyproj + scipy KD-tree), sharing no code with web/src/lib/routing.ts. Flooded edges removed; parallel edges
between the same two nodes keep the MINIMUM time (a sparse matrix would sum them). Seeded pairs, every scenario.

    .venv/bin/python e2e/fixtures/make_trip_oracle.py   # writes e2e/fixtures/trip-oracle.json
"""
import json
import math
import random
from pathlib import Path

import numpy as np
from pyproj import Transformer
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "web" / "public" / "data"
PAIRS_PER_SCENARIO = 8
out = []
for area in json.loads((DATA / "areas.json").read_text()):
    a = area["id"]
    g = json.loads((DATA / a / "graph.json").read_text())
    E = np.array(g["walk"]["edges"]).reshape(-1, 3)
    F = np.array(g["walk"]["flooded"])
    nodes = np.array(g["nodes"]).reshape(-1, 2)
    walk = np.unique(E[:, :2])
    to = Transformer.from_crs("EPSG:4326", f"EPSG:{g['utm_epsg']}", always_xy=True).transform
    wx, wy = to(nodes[walk, 0], nodes[walk, 1])
    tree = cKDTree(np.c_[wx, wy])
    vms = g["walk_kph"] / 3.6
    rnd = random.Random(f"m16-{a}")
    for ki, key in enumerate(g["scenarios"]):
        keep = (F >> ki & 1) == 0
        best = {}
        for u, v, t in E[keep]:
            k = (min(u, v), max(u, v))
            if k != (u, u) and t < best.get(k, math.inf):
                best[k] = t
        n = len(nodes)
        uu = np.array([k[0] for k in best]); vv = np.array([k[1] for k in best]); tt = np.array(list(best.values()), float)
        # a zero-time edge would vanish from a sparse matrix: store it as a tiny positive weight and round back
        tt_s = np.where(tt == 0, 1e-9, tt)
        M = csr_matrix((np.r_[tt_s, tt_s], (np.r_[uu, vv], np.r_[vv, uu])), shape=(n, n))
        open_ = np.zeros(n, bool); open_[uu] = True; open_[vv] = True
        def jitter(nd):
            lon, lat = nodes[nd]
            return round(lon + rnd.uniform(-3e-4, 3e-4), 6), round(lat + rnd.uniform(-3e-4, 3e-4), 6)
        for p in range(PAIRS_PER_SCENARIO):
            flon, flat = jitter(int(rnd.choice(walk)))
            if p % 2 == 0:
                t = rnd.choice(g["shelters"])
                dest = {"lon": t["lon"], "lat": t["lat"], "targetId": t["id"]}
                dnode, dleg = t["node"], t["snap_m"]
            else:
                tlon, tlat = jitter(int(rnd.choice(walk)))
                dest = {"lon": tlon, "lat": tlat}
                d, j = tree.query(to(tlon, tlat)); dnode, dleg = int(walk[j]), float(d)
            d, j = tree.query(to(flon, flat)); snode, sleg = int(walk[j]), float(d)
            row = {"area": a, "key": key, "pair": p, "from": {"lon": flon, "lat": flat}, "to": dest}
            if sleg > g["max_dest_snap_m"]:
                row["error"] = "far_start"
            elif dleg > g["max_dest_snap_m"]:
                row["error"] = "far_dest"
            elif not open_[snode]:
                row["error"] = "cut_off_start"
            elif not open_[dnode]:
                row["error"] = "cut_off_dest"
            else:
                ds = dijkstra(M, indices=snode)[dnode]
                if not np.isfinite(ds):
                    row["error"] = "unreachable"
                else:
                    ds = round(ds)          # undo the 1e-9 stand-ins (all true weights are integers)
                    row.update(ds=int(ds), minutes=int(math.ceil(round((ds / 10 + (sleg + dleg) / vms) / 60.0, 6))),
                               snap_m=[sleg, dleg])
            out.append(row)
(Path(__file__).parent / "trip-oracle.json").write_text(json.dumps(out, separators=(",", ":")))
print(len(out), "pairs;", {e: sum(r.get("error") == e for r in out) for e in ("far_start", "far_dest", "cut_off_start", "cut_off_dest", "unreachable")})
