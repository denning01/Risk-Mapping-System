"""M-06 model -> exposure hand-off (AGENTS.md § model -> exposure interface).

    .venv/bin/python pipeline/06_handoff.py nyando

Checks every hand-off raster in $RMS_DATA/processed/<area>/model/ — scenarios/<rain>_<enso>_depth.tif (10),
hand.tif, channels.tif — for: the area's UTM CRS, north-up 30 m grid, float32 depth with NaN = dry, and a footprint
that covers the config's handoff_bbox (densified projection) by >= 1 pixel on every side. Refuses (exit 1) on any
failure. Then writes ../rms-audit/handoffs/flood-<area>.md naming the files, CRS, k, the producing commits and the
coverage test.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.lib import config, handoff  # noqa: E402
from pipeline.lib.paths import REPO_ROOT, model_dir  # noqa: E402

RAINS = (50, 100, 150, 200, 250)
ENSO = ("normal", "elnino")
COVERAGE_TESTS = ("pipeline/tests/test_handoff.py::test_grid_for_covers_the_densified_bbox_with_at_least_one_pixel",
                  "pipeline/tests/test_handoff.py::test_a_grid_sized_from_the_four_corners_under_covers_a_bowed_edge",
                  "pipeline/tests/test_handoff.py::test_handoff_bbox_is_the_ruled_nyando_box_and_inside_the_export_box")


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check(path: Path, cfg: dict, kind: str) -> dict:
    with rasterio.open(path) as ds:
        problems = []
        if ds.crs.to_epsg() != cfg["utm_epsg"]:
            problems.append(f"CRS {ds.crs} != EPSG:{cfg['utm_epsg']}")
        if ds.transform.b or ds.transform.d or abs(ds.transform.a - 30) > 1e-6 or abs(ds.transform.e + 30) > 1e-6:
            problems.append(f"not a north-up 30 m grid: {tuple(ds.transform)[:6]}")
        tags = ds.tags()
        if tags.get("calibrated") not in ("false", "true"):
            problems.append(f"no calibrated tag (tags {sorted(tags)})")
        m = handoff.margin_px(ds.transform, ds.width, ds.height, ds.crs, cfg["handoff_bbox"])
        if m < handoff.MIN_MARGIN_PX:
            problems.append(f"covers handoff_bbox by {m:.2f} px < {handoff.MIN_MARGIN_PX}")
        if kind == "depth":
            if ds.dtypes[0] != "float32" or not (ds.nodata is not None and np.isnan(ds.nodata)):
                problems.append(f"depth must be float32 with NaN nodata, got {ds.dtypes[0]} nodata={ds.nodata}")
            a = ds.read(1)
            if np.nanmin(a) < 0:
                problems.append(f"negative depth {np.nanmin(a)}")
        out = {"file": str(path.relative_to(model_dir(cfg["id"]))), "crs": f"EPSG:{ds.crs.to_epsg()}",
               "shape": [ds.height, ds.width], "dtype": ds.dtypes[0], "nodata": str(ds.nodata),
               "margin_px": round(m, 1), "calibrated": tags.get("calibrated"), "sha256": sha256(path), "bytes": path.stat().st_size, "problems": problems}
        if kind == "depth":
            # flooded area inside handoff_bbox, for exposure to cross-check its own count
            from pyproj import Transformer
            from rasterio.features import rasterize
            from shapely import box, ops
            to = Transformer.from_crs(4326, ds.crs, always_xy=True).transform
            inside = rasterize([(ops.transform(to, box(*cfg["handoff_bbox"]).segmentize(0.001)), 1)],
                               out_shape=a.shape, transform=ds.transform).astype(bool)
            out["flooded_km2_in_handoff_bbox"] = round(float((np.isfinite(a) & inside).sum()) * 900 / 1e6, 2)
        return out


def main(area: str):
    cfg = config.load(area)
    m = model_dir(area)
    files = [(m / "scenarios" / f"{r}_{e}_depth.tif", "depth") for e in ENSO for r in RAINS]
    files += [(m / "hand.tif", "hand"), (m / "channels.tif", "channels")]
    missing = [str(p) for p, _ in files if not p.exists()]
    if missing:
        sys.exit(f"REFUSED: missing {missing}")
    results = [check(p, cfg, k) for p, k in files]
    bad = [r for r in results if r["problems"]]
    for r in results:
        print(json.dumps({k: r[k] for k in ("file", "crs", "shape", "margin_px", "problems")}
                         | ({"flooded_km2": r["flooded_km2_in_handoff_bbox"]} if "flooded_km2_in_handoff_bbox" in r
                            else {})), flush=True)
    if bad:
        sys.exit(f"REFUSED: {len(bad)} file(s) fail the hand-off checks")
    rf = json.loads((m / "runoff_flood.json").read_text())
    tj = json.loads((m / "terrain.json").read_text())
    # The producing commit is what the producing run stamped, not "the last commit touching the script" (a later
    # refactor would claim rasters it never made). Refuse a run with no stamp or with uncommitted pipeline edits.
    for name, rep in (("runoff_flood.json", rf), ("terrain.json", tj)):
        pv = rep.get("provenance")
        if not pv or pv.get("dirty") is not False:
            sys.exit(f"REFUSED: {name} provenance {pv}: re-run its script from a clean committed tree")
    commit_depth, commit_terrain = rf["provenance"]["git_commit"], tj["provenance"]["git_commit"]
    cal = rf["k_calibrated"]
    if any(r["calibrated"] != str(cal).lower() for r in results):
        sys.exit(f"REFUSED: raster calibrated tags {sorted({r['calibrated'] for r in results})} != runoff_flood.json {cal}")
    first = (f"**k = {rf['k']} is PROVISIONAL and UNCALIBRATED (M-05 BLOCKED:ee-auth).** Every raster below is tagged "
             "calibrated=false; numbers built on them are provisional." if not cal else
             f"k = {rf['k']} calibrated in M-05 (see ROUND).")
    lines = [
        first,
        "",
        f"# Hand-off: flood rasters, {cfg['name']} (model → exposure)",
        "",
        f"Written {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')} by pipeline/06_handoff.py at commit {git('rev-parse', '--short', 'HEAD')}.",
        "",
        f"- **Where:** `$RMS_DATA/processed/{area}/model/` (RMS_DATA default /Users/mac/IGAD/data)",
        f"- **CRS:** EPSG:{cfg['utm_epsg']} (UTM), north-up, 30 m; grid {results[0]['shape'][0]}×{results[0]['shape'][1]} "
        f"(the M-03 export_bbox grid {cfg['export_bbox']}).",
        "- **Depth:** float32 metres above ground, **NaN = dry**. Risk per DATA_CONTRACT: < 0.3 low, 0.3–1 medium, > 1 high.",
        f"- **Coverage:** every file covers handoff_bbox {cfg['handoff_bbox']} (densified UTM projection, "
        f"{handoff.DENSIFY} pts/edge) by ≥ {handoff.MIN_MARGIN_PX:.0f} px; smallest margin here "
        f"{min(r['margin_px'] for r in results)} px. Tests: " + ", ".join(f"`{t}`" for t in COVERAGE_TESTS) + ".",
        f"- **k = {rf['k']}, α = {rf['alpha']} — NOT CALIBRATED.** {rf['k_note']}. The depth rasters WILL be "
        "regenerated after M-05; exposure numbers built on these are provisional and must say so.",
        f"- **El Niño:** P × {rf['elnino']['ratio']} (CHIRPS OND {rf['elnino']['event'][-4:]} / OND "
        f"{rf['elnino']['clim_years'][0]}–{rf['elnino']['clim_years'][1]} mean over bbox {rf['elnino']['bbox']}). "
        "PROVISIONAL, not a slide number: the final ratio is computed over the ruled 34.80 AOI after the bbox flip.",
        f"- **Produced by** (stamped by the producing run, clean tree): depth rasters — 03_runoff_flood.py at commit "
        f"{commit_depth}; hand.tif, channels.tif — 02_terrain.py at commit {commit_terrain}.",
        "- **Known limits:** screening-level HAND + SCS-CN, not a hydraulic model; closed depressions have HAND 0 and "
        "flood in every scenario with depth = h (not pond depth); HAND drain term is the filled level (F2.13).",
        "",
        "| file | flooded km² in handoff_bbox | margin px | bytes | sha256 |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| `{r['file']}` | {r.get('flooded_km2_in_handoff_bbox', '–')} | {r['margin_px']} | {r['bytes']:,} "
                     f"| `{r['sha256'][:16]}…` |")
    dest = REPO_ROOT.parent / "rms-audit" / "handoffs" / f"flood-{area}.md"
    dest.write_text("\n".join(lines) + "\n")
    print(f"wrote {dest}")


if __name__ == "__main__":
    main(sys.argv[1])
