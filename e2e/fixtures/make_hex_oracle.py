"""M-19 second method for the hexagon outlines: Python h3 (h3==4.5.0, requirements.txt; C library via its own
bindings, not h3-js) cell_to_boundary for EVERY row of every published {key}.h3.json, both areas.
Output: hex-oracle.json {area: {h3: [[lon, lat] x 6 rounded to 1e-9]}} (each cell once; cells repeat across scenarios).

    .venv/bin/python e2e/fixtures/make_hex_oracle.py
"""
import json
from pathlib import Path

import h3

DATA = Path(__file__).resolve().parents[2] / "web" / "public" / "data"
out, rows = {}, 0
for area in json.loads((DATA / "areas.json").read_text()):
    a = area["id"]
    cells = {}
    for f in sorted((DATA / a / "scenarios").glob("*.h3.json")):
        for r in json.loads(f.read_text()):
            rows += 1
            if r["h3"] not in cells:
                assert h3.get_resolution(r["h3"]) == 9, r["h3"]
                cells[r["h3"]] = [[round(lng, 9), round(lat, 9)] for lat, lng in h3.cell_to_boundary(r["h3"])]
    out[a] = cells
(Path(__file__).parent / "hex-oracle.json").write_text(json.dumps(out, separators=(",", ":")))
print(rows, "rows;", {a: len(c) for a, c in out.items()}, "distinct cells")
