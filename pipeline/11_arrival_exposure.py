"""E-20 (b): who the warning time affects, DATA ONLY ($RMS_DATA; the contract field is pending Person B).

Per area and scenario -> {out}/{rain}_{enso}.arrival.json:
  bands        ["<1", "1-3", "3-6", ">6"] hours (RULING E-20: bands on the FAST bound = the headline)
  fast / slow  per band: people_low / people_medium / people_high, buildings, flooded_km2 -- on the FAST bound
               (arrival_h_fast.tif, the headline: "as little as") and on the SLOW bound (arrival_h.tif, the velocity
               method), so the range is visible
  unknown      the same for wet cells with no arrival estimate (NaN), if any
RULES:
  * A building (and its people: the writer's W2 rule, building-weighted, mode B) takes the band of the 30 m cell holding
    its centroid -- the cell that decided it is flooded. Flooded area takes each wet cell's own band.
  * People are integers by LARGEST REMAINDER over the bands, so each bound's band sums equal exposure.json exactly.
  * "<1" includes the 0-h cells (nothing upstream: local rain / ponding). The app must label that band "within the
    hour / local rain" and never print "0 h" (operator addendum).
  * SCREENING, NOT CALIBRATED (model M-20): time to the cell, not the time the depth there is reached.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BANDS = ("<1", "1-3", "3-6", ">6")
PROJ = ("low", "medium", "high")


def _mod(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(HERE))
    spec.loader.exec_module(m)
    return m


def band_table(cell_band: np.ndarray, wet: np.ndarray, cell_m2: float, b_band: np.ndarray, b_wet: np.ndarray,
               ppl: np.ndarray | None, targets: dict | None) -> dict:
    """{band name | "unknown": {people_*, buildings, flooded_km2}} for one bound.
    cell_band: per cell band index (-1 = NaN); b_band / b_wet: per kept building its cell's band and whether that cell
    is wet; ppl (n, 3) its people; targets {low, medium, high} exposure.json integers."""
    hm = _mod("h3m", "10_h3.py")
    keys = list(range(len(BANDS))) + [-1]
    names = list(BANDS) + ["unknown"]
    out = {n: {"buildings": int(((b_band == k) & b_wet).sum()),
               "flooded_km2": round(float(((cell_band == k) & wet).sum()) * cell_m2 / 1e6, 4)} for k, n in zip(keys, names)}
    if ppl is not None:
        for j, s in enumerate(PROJ):
            v = np.array([float(ppl[(b_band == k) & b_wet, j].sum()) for k in keys])
            ints = hm.largest_remainder(v, names, targets[s])
            for n, x in zip(names, ints):
                out[n][f"people_{s}"] = int(x)
    if not any(out["unknown"].values()):
        del out["unknown"]
    return out


def main(argv=None) -> int:
    import rasterio
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--area", required=True)
    ap.add_argument("--depth-dir", required=True)
    ap.add_argument("--arrival-snapshot", required=True, help="<depth snapshot>/arrival/<commit> (07 snapshot-arrival)")
    ap.add_argument("--out-dir", required=True, help="under $RMS_DATA (never web/)")
    ap.add_argument("--population-mode", default="B", choices=["A", "B"])
    a = ap.parse_args(argv)
    out = Path(a.out_dir).resolve()
    if (REPO / "web").resolve() in [out, *out.parents]:
        print("ERROR: --out-dir is inside web/ (E-20 (b) is DATA ONLY)", file=sys.stderr)
        return 1
    sc, pop, hm = _mod("sc07", "07_scenarios.py"), _mod("pop05", "05_population.py"), _mod("h3m", "10_h3.py")
    data = REPO / "web" / "public" / "data"
    bbox = next(x for x in json.loads((data / "areas.json").read_text()) if x["id"] == a.area)["bbox"]
    pdir = sc.rms_data() / "processed" / a.area / "exposure"
    man = json.loads((pdir / "population_manifest.json").read_text())
    bld = dict(np.load(pdir / "open_buildings_aoi.npz"))
    with rasterio.open(pdir / "county_id_aoi.tif") as cds:
        ids, ids_tf = cds.read(1), cds.transform
    snap = json.loads((Path(a.arrival_snapshot) / "snapshot.json").read_text())
    out.mkdir(parents=True, exist_ok=True)
    grid, bad = None, 0
    print(f"arrival exposure {a.area}: arrival snapshot {a.arrival_snapshot} (model commit {snap['git_commit']}) -> {out}")
    for key in sc.scenario_keys():
        depth, tf, crs, _ = sc._read(Path(a.depth_dir) / f"{key}_depth.tif")
        if grid != (tf, str(crs), depth.shape):
            grid = (tf, str(crs), depth.shape)
            mask = sc.aoi_mask(depth.shape, tf, crs, bbox)
            county = pop.ids_on_grid(ids, ids_tf, depth.shape, tf, crs)
            r, c, ok, ppl = hm.building_people(bld, county, mask, tf, crs, man, a.population_mode, pop.OB_PRECISION)
            fast, slow = sc.read_arrival_snapshot(Path(a.arrival_snapshot), grid)
            bands = {"fast": sc.classify_arrival_band(fast), "slow": sc.classify_arrival_band(slow)}
            cell_m2 = abs(tf.a * tf.e)
        depth = np.where(mask, depth, np.nan)
        wet = sc.classify_risk(depth) > 0
        exp = json.loads((data / a.area / "scenarios" / f"{key}.exposure.json").read_text())
        b_wet = np.zeros(len(r), bool); b_wet[ok] = wet[r[ok], c[ok]]
        res = {"scenario": key, "area": a.area, "bands_h": list(BANDS), "headline": "fast",
               "arrival_model_commit": snap["git_commit"], "arrival_sha256": snap["sha256"],
               "population_year": exp["year"], "source": exp["source"],
               "note": "SCREENING, NOT CALIBRATED: hours until water from the most remote upstream point reaches the "
                       "cell (NRCS NEH 630 velocity method; fast bound = /2.44). '<1' includes local-rain (0 h) cells: "
                       "label 'within the hour / local rain', never '0 h'."}
        for bound in ("fast", "slow"):
            bb = np.full(len(r), -1, np.int64); bb[ok] = bands[bound][r[ok], c[ok]]
            res[bound] = band_table(bands[bound], wet, cell_m2, bb, b_wet, ppl, exp["population"])
            t = res[bound]
            for s in PROJ:
                if sum(v[f"people_{s}"] for v in t.values()) != exp["population"][s]:
                    bad += 1; print(f"  CHECK FAILED {key} {bound} people_{s}")
            if sum(v["buildings"] for v in t.values()) != exp["buildings"]:
                bad += 1; print(f"  CHECK FAILED {key} {bound} buildings")
            if abs(sum(v["flooded_km2"] for v in t.values()) - wet.sum() * cell_m2 / 1e6) > 1e-3:
                bad += 1; print(f"  CHECK FAILED {key} {bound} flooded_km2")
        (out / f"{key}.arrival.json").write_text(json.dumps(res, indent=1))
        f = res["fast"]
        print(f"{key:<12} fast: " + "  ".join(f"{n} {f[n]['people_medium']:,}p/{f[n]['buildings']:,}b/{f[n]['flooded_km2']}km2"
                                             for n in f) + "   slow medium: "
              + "/".join(f"{res['slow'][n]['people_medium']:,}" for n in res["slow"]))
    print("CHECKS:", "ALL PASS (each bound's band sums == exposure.json people x3, buildings; area == wet cells)"
          if not bad else f"{bad} FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
