"""M-12: web/public/data/<area>/forecast.json (DATA_CONTRACT.md § forecast.json) from the cached M-11 snapshot.

    .venv/bin/python pipeline/09_web_forecast.py nyando nairobi [--out DIR]

Offline: reads only $RMS_DATA/processed/<area>/forecast/forecast.json (written by 08_forecast.py). wettest_day_mm is
the AOI-mean wettest day (mean over the distinct Open-Meteo model cells), never the point max. River discharge is
left null: GloFAS is context only (M-11) and the contract does not say which day's flow the field means.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.lib.paths import REPO_ROOT, data_root  # noqa: E402

RAIN_VALUES = (50, 100, 150, 200, 250)


def build(snap: dict) -> dict:
    o, p, m = snap["official_outlook"], snap["precipitation"], snap["mapping"]
    as_of = datetime.strptime(snap["snapshot_utc"], "%Y-%m-%dT%H%MZ").strftime("%Y-%m-%dT%H:%M:00Z")
    band = o["above_normal_pct_band"]
    if m["scenario"] is None:
        suggested = None
    else:
        assert m["rain_mm"] in RAIN_VALUES, m
        suggested = {"rain": m["rain_mm"], "enso": m["enso"], "rule": m["rule"]}
    return {
        "as_of": as_of,
        "icpac": {"season": o["season"], "statement": "GHACOF74", "url": o["url"],
                  "above_normal_pct": [band[0], band[1]]},
        "short_range": {"source": f"Open-Meteo, mean of {p['distinct_model_cells']} model cells near the area",
                        "wettest_day_mm": p["wettest_day_mm"], "river_discharge_m3s": None, "url": p["url"]},
        "suggested_scenario": suggested,
    }


def load_snapshot(area: str, root: Path | None = None) -> dict:
    """The cached M-11 snapshot for <area>. Refuses one written for another area or by uncommitted code (dirty)."""
    p = (root or data_root()) / "processed" / area / "forecast" / "forecast.json"
    snap = json.loads(p.read_text())
    if snap.get("area") != area:
        raise SystemExit(f"REFUSED: {p} is for area {snap.get('area')!r}, not {area!r}")
    prov = snap.get("provenance") or {}
    if prov.get("dirty") is not False or not prov.get("git_commit"):
        raise SystemExit(f"REFUSED: {p} provenance {prov} is not a clean committed run")
    return snap


def main(argv: list | None = None):
    ap = argparse.ArgumentParser()
    ap.add_argument("areas", nargs="+")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "web" / "public" / "data")
    a = ap.parse_args(argv)
    for area in a.areas:
        snap = load_snapshot(area)
        dest = a.out / area / "forecast.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(build(snap), ensure_ascii=False, indent=1) + "\n")
        print(f"wrote {dest}")


if __name__ == "__main__":
    main()
