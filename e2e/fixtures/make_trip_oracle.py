"""M-16 second method for FROM -> TO: shortest walking time by scipy.sparse.csgraph.dijkstra on graph.json, with its own
snapping (pyproj + scipy KD-tree), sharing no code with web/src/lib/routing.ts. Flooded edges removed; parallel edges
between the same two nodes keep the MINIMUM time (a sparse matrix would sum them). Seeded pairs, every scenario.

F17.3: also the SAFER and THIRD routes, from the rules as stated (routing.ts routeBetween doc), computed here:
  safer = near-flood edges x near_penalty, kept when its edge list differs from the fastest;
  third = penalty 1 with the fastest route's edges x ALT_EDGE_FACTOR (2), kept when it differs from both and
          shares < MAX_ALT_OVERLAP (0.5) of its edge metres with the fastest.
Each route carries its edge ids (per node pair the cheapest parallel edge under that route's costs; lowest id on a
tie, and ties are counted), its penalised cost and its true walking time.

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
ALT_EDGE_FACTOR = 2      # CHOICE (M-16), restated here, not imported
MAX_ALT_OVERLAP = 0.5
ties = 0
out = []
for area in json.loads((DATA / "areas.json").read_text()):
    a = area["id"]
    g = json.loads((DATA / a / "graph.json").read_text())
    E = np.array(g["walk"]["edges"]).reshape(-1, 3)
    F = np.array(g["walk"]["flooded"])
    NEAR = np.array(g["walk"]["near"])
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
        near = (NEAR >> ki & 1) == 1
        vms_ = g["walk_kph"] / 3.6
        edge_m = E[:, 2] / 10 * vms_

        def search(cost, s, d):
            """Dijkstra on per-edge costs (flooded edges absent): node pair -> cheapest parallel edge."""
            global ties
            pick = {}
            for i in np.flatnonzero(keep):
                u, v = int(E[i, 0]), int(E[i, 1])
                k = (min(u, v), max(u, v))
                if u == v:
                    continue
                c = cost[i]
                if k not in pick or c < cost[pick[k]]:
                    pick[k] = i
                elif c == cost[pick[k]]:
                    ties += 1
            ks = list(pick)
            uu_ = np.array([k[0] for k in ks]); vv_ = np.array([k[1] for k in ks]); cc = np.array([cost[pick[k]] for k in ks], float)
            cc = np.where(cc == 0, 1e-9, cc)
            Mx = csr_matrix((np.r_[cc, cc], (np.r_[uu_, vv_], np.r_[vv_, uu_])), shape=(n, n))
            dist, pred = dijkstra(Mx, indices=s, return_predecessors=True)
            if not np.isfinite(dist[d]):
                return None
            path = [d]
            while path[-1] != s:
                path.append(int(pred[path[-1]]))
            path.reverse()
            edges = [int(pick[(min(x, y), max(x, y))]) for x, y in zip(path, path[1:])]
            return {"edges": edges, "cost": int(round(sum(cost[i] for i in edges))), "ds": int(sum(int(E[i, 2]) for i in edges))}

        base_t = E[:, 2].astype(float)
        cost_safer = base_t * np.where(near, g["near_penalty"], 1.0)

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
                    mins = lambda r: int(math.ceil(round((r["ds"] / 10 + (sleg + dleg) / vms) / 60.0, 6)))
                    r1 = search(base_t, snode, dnode)
                    assert r1["ds"] == row["ds"], "edge-level fastest disagrees with the node-level one"
                    alts = [{"label": "fastest", **r1, "minutes": mins(r1)}]
                    r2 = search(cost_safer, snode, dnode)
                    if r2 and r2["edges"] != r1["edges"]:
                        alts.append({"label": "safer", **r2, "minutes": mins(r2)})
                    if r1["edges"]:
                        cost3 = base_t.copy(); cost3[r1["edges"]] *= ALT_EDGE_FACTOR
                        r3 = search(cost3, snode, dnode)
                        if r3 and all(r3["edges"] != x["edges"] for x in alts):
                            em = sum(edge_m[i] for i in r3["edges"]); s1 = set(r1["edges"])
                            ov = sum(edge_m[i] for i in r3["edges"] if i in s1) / em if em > 0 else 0
                            if ov < MAX_ALT_OVERLAP:
                                alts.append({"label": "alternative", **r3, "minutes": mins(r3), "overlap": ov})
                    row["alts"] = alts
            out.append(row)
(Path(__file__).parent / "trip-oracle.json").write_text(json.dumps(out, separators=(",", ":")))
print("parallel-edge cost ties met:", ties, "| alts:", {l: sum(any(x["label"] == l for x in r.get("alts", [])) for r in out) for l in ("fastest", "safer", "alternative")})
print(len(out), "pairs;", {e: sum(r.get("error") == e for r in out) for e in ("far_start", "far_dest", "cut_off_start", "cut_off_dest", "unreachable")})
