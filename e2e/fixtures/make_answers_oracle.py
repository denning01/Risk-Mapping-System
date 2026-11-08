"""R20 oracle: the Python reference client_answers() (pipeline/06_routing.py at exposure commit e972b7e, RULING R20, not yet
merged into data: read with `git show`, never written into this tree) on every preset origin (with its user type) and on
seeded random free taps (no user type), every scenario, both areas, reading ONLY web/public/data/<area>/graph.json.

    .venv/bin/python e2e/fixtures/make_answers_oracle.py   # writes e2e/fixtures/answers-oracle.json
"""
import json
import random
import subprocess
import sys
import tempfile
import importlib.util
from pathlib import Path

ORACLE_COMMIT = "e972b7e"
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "web" / "public" / "data"
src = subprocess.run(["git", "-C", str(ROOT), "show", f"{ORACLE_COMMIT}:pipeline/06_routing.py"], check=True, capture_output=True, text=True).stdout
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "routing_r20.py"
    p.write_text(src)
    sys.path.insert(0, str(ROOT / "pipeline"))           # its own `lib` imports
    spec = importlib.util.spec_from_file_location("rt20", p)
    rt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rt)

RANDOM_PER_SCENARIO = 12
out = []
for area in json.loads((DATA / "areas.json").read_text()):
    a = area["id"]
    g = json.loads((DATA / a / "graph.json").read_text())
    origins = json.loads((DATA / a / "origins.json").read_text())
    rnd = random.Random(f"r20-{a}")
    w, s, e, n = area["bbox"]
    for key in g["scenarios"]:
        pts = [(o["id"], o["lon"], o["lat"], o["user_type"]) for o in origins]
        pts += [(f"r{i}", round(rnd.uniform(w, e), 6), round(rnd.uniform(s, n), 6), None) for i in range(RANDOM_PER_SCENARIO)]
        for pid, lon, lat, ut in pts:
            for user_type in ([ut, None] if ut else [None]):
                ans = rt.client_answers(g, key, lon, lat, user_type)
                slim = {}
                for kind, x in ans.items():
                    if "error" in x:
                        slim[kind] = {"error": x["error"]}
                        continue
                    slim[kind] = {"primary": {k: x["primary"][k] for k in ("shelter", "minutes", "edges")}}
                    if "safer" in x:
                        slim[kind]["safer"] = {k: x["safer"][k] for k in ("shelter", "minutes", "edges", "extra_min")}
                out.append({"area": a, "key": key, "pt": pid, "lon": lon, "lat": lat, "user_type": user_type, "answers": slim})
(Path(__file__).parent / "answers-oracle.json").write_text(json.dumps({"oracle_commit": ORACLE_COMMIT, "rows": out}, separators=(",", ":")))
n_safer = sum(1 for r in out for x in r["answers"].values() if "safer" in x)
print(len(out), "points;", sum(1 for r in out for x in r["answers"].values() if "error" in x), "refused answers;", n_safer, "with a safer alternative")
