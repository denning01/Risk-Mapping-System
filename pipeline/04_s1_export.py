"""M-05 Sentinel-1 backtest export (Earth Engine), once, cached in $RMS_DATA/raw/<area>/s1/.

    .venv/bin/python pipeline/04_s1_export.py nyando

Operator EE standing rule: (1) export ONCE — if the output exists it is skipped; tests, re-runs and the auditor read
the local file, never EE; (2) clipped to the area bbox (not the export box) at 30 m with an explicit maxPixels;
(3) one getDownloadURL per product, no getInfo in a loop; (4) EECU: getDownloadURL is not a batch task, so EE returns
no batchEecuUsageSeconds for it — recorded as null with that reason; (5) the project id comes from $EE_PROJECT only.

Products (GRD, IW, VV+VH, terrain-corrected sigma0 in dB as served by COPERNICUS/S1_GRD), on the model's own UTM 30 m
grid (crs + crsTransform of processed/<area>/model/hand.tif, so pixels align with the depth rasters exactly):
  s1_before.tif  median of every acquisition in before_period   (bands VV, VH)
  s1_event.tif   minimum of every acquisition in backtest_event (bands VV, VH) — open water darkens backscatter, so
                 the minimum is the maximum water extent seen in the window
The acquisitions used (date, orbit, direction) go to s1.json. The flood mask itself is computed locally (05_backtest.py)
so thresholds can be audited without EE.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.lib import config  # noqa: E402
from pipeline.lib.fetch import sha256  # noqa: E402
from pipeline.lib.paths import model_dir, raw_dir  # noqa: E402

MAX_PIXELS = 1e8


def load_env():
    env = Path(__file__).resolve().parents[1] / ".env"
    if env.exists() and "EE_PROJECT" not in os.environ:
        for line in env.read_text().splitlines():
            if line.startswith("EE_PROJECT="):
                os.environ["EE_PROJECT"] = line.split("=", 1)[1].strip().strip('"')


def main(area: str):
    cfg = config.load(area)
    out = raw_dir(area) / "s1"
    targets = {"before": out / "s1_before.tif", "event": out / "s1_event.tif"}
    if all(p.exists() for p in targets.values()) and (out / "s1.json").exists():
        print(f"cached: {out} (export once; delete to re-export)")
        return
    load_env()
    import ee
    ee.Initialize(project=os.environ["EE_PROJECT"])
    with rasterio.open(model_dir(area) / "hand.tif") as ds:
        crs, tr = f"EPSG:{ds.crs.to_epsg()}", list(ds.transform)[:6]
    region = ee.Geometry.Rectangle(cfg["bbox"], proj="EPSG:4326", geodesic=False)
    col = (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(region)
           .filter(ee.Filter.eq("instrumentMode", "IW"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
           .select(["VV", "VH"]))
    periods = {"before": (cfg["before_period"], "median"), "event": (cfg["backtest_event"], "min")}
    out.mkdir(parents=True, exist_ok=True)
    meta = {"product": "Copernicus Sentinel-1 GRD (COPERNICUS/S1_GRD), IW, VV+VH, sigma0 dB",
            "licence": "Contains modified Copernicus Sentinel data 2023 (free, full and open)",
            "region_wgs84": cfg["bbox"], "crs": crs, "crs_transform": tr, "scale_m": 30, "max_pixels": MAX_PIXELS,
            "route": "ee.Image.getDownloadURL, one per product",
            "eecu_seconds": None,
            "eecu_note": "getDownloadURL is an interactive request, not a batch task: EE reports no "
                         "batchEecuUsageSeconds for it",
            "retrieved_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "products": {}}
    for key, (per, reducer) in periods.items():
        sub = col.filterDate(per["start"], ee.Date(per["end"]).advance(1, "day"))
        # one getInfo per product (not per image): the acquisitions that went into the composite
        acq = sub.aggregate_array("system:time_start").zip(sub.aggregate_array("relativeOrbitNumber_start")) \
                 .zip(sub.aggregate_array("orbitProperties_pass")).getInfo()
        acq = sorted({(datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d"), o, d)
                      for (t, o), d in acq})
        img = (sub.median() if reducer == "median" else sub.min()).clip(region).toFloat()
        url = img.getDownloadURL({"region": region, "crs": crs, "crs_transform": tr, "format": "GEO_TIFF",
                                  "bands": ["VV", "VH"], "maxPixels": MAX_PIXELS})
        print(f"[{key}] {len(acq)} acquisitions, {reducer}; downloading", flush=True)
        with urllib.request.urlopen(url, timeout=600) as r:
            targets[key].write_bytes(r.read())
        with rasterio.open(targets[key]) as ds:
            shape, bounds = [ds.count, ds.height, ds.width], list(ds.bounds)
        meta["products"][key] = {"file": targets[key].name, "period": per, "reducer": reducer,
                                 "acquisitions": [{"date": d, "relative_orbit": o, "pass": p} for d, o, p in acq],
                                 "shape": shape, "bounds_utm": bounds, "sha256": sha256(targets[key])}
        print(json.dumps({"key": key, "shape": shape, "dates": sorted({a[0] for a in acq})}), flush=True)
    (out / "s1.json").write_text(json.dumps(meta, indent=1))
    print(f"wrote {out / 's1.json'}")


if __name__ == "__main__":
    main(sys.argv[1])
