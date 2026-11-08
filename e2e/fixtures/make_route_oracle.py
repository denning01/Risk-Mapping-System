"""M-14 oracle: run the E-16 Python reference client (pipeline/06_routing.py client_route) on every preset origin and on
seeded random taps, for every scenario of both areas, reading ONLY web/public/data/<area>/graph.json. The JS port
(web/src/lib/routing.ts) must reproduce each result exactly (shelter, minutes, edge list, snap legs).

    .venv/bin/python e2e/fixtures/make_route_oracle.py   # writes e2e/fixtures/route-oracle.json
"""
import importlib.util
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "web" / "public" / "data"
spec = importlib.util.spec_from_file_location("rt", ROOT / "pipeline" / "06_routing.py")
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)

RANDOM_PER_SCENARIO = 12
out = []
for area in json.loads((DATA / "areas.json").read_text()):
    a = area["id"]
    g = json.loads((DATA / a / "graph.json").read_text())
    origins = json.loads((DATA / a / "origins.json").read_text())
    rnd = random.Random(f"m14-{a}")
    w, s, e, n = area["bbox"]
    for key in g["scenarios"]:
        taps = [(o["id"], o["lon"], o["lat"]) for o in origins]
        taps += [(f"r{i}", round(rnd.uniform(w, e), 6), round(rnd.uniform(s, n), 6)) for i in range(RANDOM_PER_SCENARIO)]
        for tid, lon, lat in taps:
            r = rt.client_route(g, key, lon, lat)
            out.append({"area": a, "key": key, "tap": tid, "lon": lon, "lat": lat, **r})
(Path(__file__).parent / "route-oracle.json").write_text(json.dumps(out, separators=(",", ":")))
print(len(out), "results;", sum("error" in r for r in out), "refusals")
