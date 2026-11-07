"""M-11 forecast anchor: official seasonal outlook + a dated forecast snapshot, mapped to the slider scenarios.

    .venv/bin/python pipeline/08_forecast.py nyando                      # new snapshot (network)
    .venv/bin/python pipeline/08_forecast.py nyando 2026-11-06T1102Z     # rebuild from that cached snapshot, no network

Writes $RMS_DATA/processed/<area>/forecast/forecast.json and caches every raw API response under
$RMS_DATA/raw/<area>/forecast/<UTC timestamp>/. NOT written to web/public/data: the contract for it is pending Person B.
Labels: "official outlook" (ICPAC) and "forecast snapshot" (Open-Meteo / GloFAS) — never "our forecast".

(a) ICPAC GHACOF74 OND 2026 outlook. ICPAC publishes no gridded file for it (none found); the above-normal probability
    band for each AOI was READ from the official map (Figure 1 of the technical statement) by pixel colour against the
    map's own legend (rounded to the 10 % band) — see OUTLOOK below and the ROUND for the method and its output.
(b) Open-Meteo forecast API (daily precipitation_sum, 16 days) at a 3x3 grid of points over the AOI bbox, averaged;
    GloFAS v4 river discharge (Open-Meteo flood API, 30 days) at the model's outlet cell (highest flow accumulation on a
    channel inside the AOI), with the same cell's daily record for context. 1991-2020 is REQUESTED, but the API's GloFAS
    record holds nulls before 1997-01-01, so the climatology is over the finite days only and its real period is reported.
(c) Mapping rule to the slider: rain_mm = the slider value (50..250 mm in 24 h, DATA_CONTRACT) nearest to the WETTEST
    forecast day (AOI mean); if that day is < 25 mm the forecast is below every scenario and maps to none.
    enso = "elnino" when the official statement says El Nino conditions are established (GHACOF74: yes), else "normal".
    GloFAS is context only: discharge is not 24 h rainfall, so it does not pick a scenario.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.lib import config, terrain  # noqa: E402
from pipeline.lib.paths import model_dir, provenance, raw_dir  # noqa: E402
from pipeline.lib.rio import grid_of, read  # noqa: E402

RAINS = (50, 100, 150, 200, 250)
MIN_MAPPED_MM = 25.0
# Open-Meteo's licence page (open-meteo.com/en/licence) lists GloFAS under its OWN licence, linked to ECMWF's
# cems-floods_428a6e10....pdf, titled "CEMS-FLOODS datasets licence (rev. 1)". It is NOT the CC BY 4.0 that covers Open-Meteo's
# own API data (the earlier label was wrong). The licence text could not be read: ECMWF hosts refused connections 2026-11-07.
GLOFAS_SOURCE = ("GloFAS v4 (Copernicus Emergency Management Service) via the Open-Meteo flood API; licence: CEMS-FLOODS "
                 "datasets licence (rev. 1), as linked from open-meteo.com/en/licence; terms NOT read (ECMWF hosts "
                 "unreachable 2026-11-07); attribute as Copernicus Emergency Management Service information")

OUTLOOK = {
    "source": "ICPAC, Technical Statement from the 74th Greater Horn of Africa Climate Outlook Forum (GHACOF74), "
              "17-18 August 2026, Kigali — OND 2026 Seasonal Climate Outlook",
    "url": "https://www.icpac.net/documents/1118/GHACOF74_Final_Technical_Statement.pdf",
    "pdf_sha256": "94adc7002f457c7f0305b1f2ed9465caa50002fa1cd442ecad7fbbea38f489b8",
    "season": "OND 2026",
    "categories": "terciles of 1991-2020 (statement p.3)",
    "enso_statement": "El Niño conditions are currently established, with NOAA's Climate Prediction Centre maintaining an "
                      "El Niño Advisory as of 10 August 2026 (statement p.3)",
    "enso_established": True,
    "method": "Figure 1 (p.4) image extracted from the PDF; AOI bbox projected on the map's lon/lat ticks (47.1 px/deg "
              "at display scale); each pixel matched to the nearest legend swatch; band = majority",
    "above_normal_pct_band": {"nyando": [70, 80], "nairobi": [80, 90]},
    "pixels": {"nyando": "722 of 728 in 70-80 (6 lake/border pixels)", "nairobi": "72 of 72 in 80-90"},
    "gridded_file": None,
    "gridded_note": "no gridded outlook file found on icpac.net; probabilities are read from the published map",
}


def get(url: str, cache: Path, name: str) -> dict:
    f = cache / f"{name}.json"
    if f.exists():
        print(f"cached: {f}")
        return json.loads(f.read_bytes())
    cache.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "igad-flood-ews-mvp"})
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read()
    (cache / f"{name}.json").write_bytes(body)
    return json.loads(body)


def outlet(area: str) -> tuple[float, float, float]:
    """lon, lat and upstream km2 of the highest-accumulation channel cell inside the AOI (the model's own outlet)."""
    import importlib.util
    from pyproj import Transformer
    import rasterio
    spec = importlib.util.spec_from_file_location("rf", Path(__file__).resolve().parent / "03_runoff_flood.py")
    rf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rf)
    cfg = config.load(area)
    m = model_dir(area)
    g = grid_of(m / "hand.tif")
    acc = read(m / "acc.tif")
    ch = read(m / "channels.tif") == 1
    cand = np.where(ch & rf.aoi_mask(cfg, g), acc, -1)
    r, c = np.unravel_index(int(np.argmax(cand)), cand.shape)
    x, y = rasterio.transform.xy(g["transform"], r, c)
    lon, lat = Transformer.from_crs(g["crs"], 4326, always_xy=True).transform(x, y)
    return round(lon, 4), round(lat, 4), round(float(acc[r, c]) * 900 / 1e6, 1)


def clim(times: list, values: list, peak: float) -> dict:
    """Climatology over the FINITE days of the record (nulls dropped), with the period those days actually span."""
    t = np.array(times)
    q = np.array([np.nan if v is None else v for v in values], dtype=float)
    ok = np.isfinite(q)
    t, q = t[ok], q[ok]
    return {"period": f"{t[0]}..{t[-1]}", "days": int(q.size), "missing_days_in_request": int((~ok).sum()),
            "p50_m3s": round(float(np.median(q)), 2), "p95_m3s": round(float(np.percentile(q, 95)), 2),
            "p99_m3s": round(float(np.percentile(q, 99)), 2), "max_m3s": round(float(q.max()), 2),
            "peak_percentile": round(float((q < peak).mean() * 100), 1)}


def rain_summary(pr, days: list) -> dict:
    """pr: points x days. The wettest day is by AOI mean; the point max ON that day and the 16-day single-point max are
    reported separately (F9.2: they can fall on different days)."""
    m = np.nanmean(pr, axis=0)
    i = int(np.nanargmax(m))
    jp, j = np.unravel_index(int(np.nanargmax(pr)), pr.shape)
    return {"wettest_day": days[i], "wettest_day_mm": round(float(m[i]), 1),
            "wettest_day_point_max_mm": round(float(np.nanmax(pr[:, i])), 1),
            "max_single_point_day": days[j], "max_single_point_day_mm": round(float(pr[jp, j]), 1)}


def distinct_cells(fc: list) -> list:
    """F9.6: the 3x3 requested points snap to Open-Meteo model grid cells, and several can snap to the same cell (Nairobi:
    9 points -> 6 cells). Keep each cell once (first occurrence) so no cell is weighted twice in the mean."""
    seen, out = set(), []
    for loc in fc:
        key = (round(loc["longitude"], 5), round(loc["latitude"], 5))
        if key not in seen:
            seen.add(key)
            out.append(loc)
    return out


def map_rain(max_day_mm: float):
    if max_day_mm < MIN_MAPPED_MM:
        return None
    return min(RAINS, key=lambda r: abs(r - max_day_mm))


def main(area: str, stamp: str | None = None):
    prov = provenance()
    cfg = config.load(area)
    if stamp is not None and not (raw_dir(area) / "forecast" / stamp).is_dir():
        sys.exit(f"no cached snapshot {stamp}")
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    cache = raw_dir(area) / "forecast" / stamp
    w, s, e, n = cfg["bbox"]
    lats = [round(v, 4) for v in np.linspace(s, n, 3) for _ in range(3)]
    lons = [round(v, 4) for _ in range(3) for v in np.linspace(w, e, 3)]
    fc_url = ("https://api.open-meteo.com/v1/forecast?latitude=" + ",".join(map(str, lats)) + "&longitude="
              + ",".join(map(str, lons)) + "&daily=precipitation_sum&forecast_days=16&timezone=Africa%2FNairobi")
    fc = get(fc_url, cache, "open_meteo_forecast")
    days = fc[0]["daily"]["time"]
    cells = distinct_cells(fc)
    pr = np.array([loc["daily"]["precipitation_sum"] for loc in cells], dtype=float)   # distinct cells x 16
    inside = [c for c in cells if w <= c["longitude"] <= e and s <= c["latitude"] <= n]
    aoi_mean = np.nanmean(pr, axis=0)
    i = int(np.nanargmax(aoi_mean))
    lon, lat, up_km2 = outlet(area)
    fl_url = (f"https://flood-api.open-meteo.com/v1/flood?latitude={lat}&longitude={lon}"
              "&daily=river_discharge,river_discharge_mean,river_discharge_max&forecast_days=30")
    fl = get(fl_url, cache, "glofas_forecast")
    hist_url = (f"https://flood-api.open-meteo.com/v1/flood?latitude={lat}&longitude={lon}"
                "&daily=river_discharge&start_date=1991-01-01&end_date=2020-12-31")
    hist = get(hist_url, cache, "glofas_1991_2020")
    q = np.array(fl["daily"]["river_discharge_max"], dtype=float)
    qm = np.array(fl["daily"]["river_discharge_mean"], dtype=float)
    peak = float(np.nanmax(qm))
    cl = clim(hist["daily"]["time"], hist["daily"]["river_discharge"], peak)
    rain = map_rain(float(aoi_mean[i]))
    enso = "elnino" if OUTLOOK["enso_established"] else "normal"
    rep = {
        "provenance": prov, "area": area, "snapshot_utc": stamp, "label": "official outlook + forecast snapshot (not our forecast)",
        "official_outlook": {k: v for k, v in OUTLOOK.items() if k not in ("above_normal_pct_band", "pixels")}
                            | {"above_normal_pct_band": OUTLOOK["above_normal_pct_band"][area],
                               "pixels": OUTLOOK["pixels"][area]},
        "precipitation": {"source": "Open-Meteo forecast API (best_match models), CC BY 4.0", "url": fc_url,
                          "requested_points": len(fc), "distinct_model_cells": len(cells),
                          "distinct_cells_inside_bbox": len(inside),
                          "averaging": "mean over the DISTINCT Open-Meteo model grid cells the 3x3 requested points snap "
                                       "to (cells near the AOI, some outside its bbox), not points inside the AOI",
                          "grid_cell_points": [[loc["longitude"], loc["latitude"]] for loc in cells],
                          "days": days, "aoi_mean_mm": [round(float(v), 1) for v in aoi_mean],
                          "total_16d_mm": round(float(np.nansum(aoi_mean)), 1),
                          **rain_summary(pr, days)},
        "river": {"source": GLOFAS_SOURCE, "url": fl_url,
                  "model_outlet": {"lon": lon, "lat": lat, "upstream_km2": up_km2},
                  "glofas_cell": [fl["longitude"], fl["latitude"]],
                  "days": fl["daily"]["time"],
                  "ensemble_mean_m3s": [round(float(v), 2) for v in qm],
                  "ensemble_max_m3s": [round(float(v), 2) for v in q],
                  "peak_ensemble_mean_m3s": round(peak, 2),
                  "peak_day": fl["daily"]["time"][int(np.nanargmax(qm))],
                  "clim": {"url": hist_url, "requested": "1991-01-01..2020-12-31"}
                          | {k: v for k, v in cl.items() if k != "peak_percentile"},
                  "peak_percentile_of_clim_days": cl["peak_percentile"],
                  "note": "context only; discharge does not select a slider scenario"},
        "mapping": {"rule": f"rain_mm = slider value nearest to the wettest forecast day (mean of {len(cells)} distinct Open-Meteo model cells near the AOI); "
                            f"< {MIN_MAPPED_MM:g} mm maps to none. enso = elnino when the official statement says El "
                            "Niño conditions are established.",
                    "rain_mm": rain, "enso": enso,
                    "scenario": f"{rain}_{enso}" if rain else None,
                    "why": (f"wettest forecast day {days[i]}: {aoi_mean[i]:.1f} mm AOI mean -> nearest slider value {rain} mm"
                            if rain else f"wettest forecast day {days[i]}: {aoi_mean[i]:.1f} mm < {MIN_MAPPED_MM:g} mm, "
                            "below the lowest scenario (50 mm): no scenario is triggered by this snapshot")},
        "raw_cache": str(cache),
    }
    out = model_dir(area).parent / "forecast"
    out.mkdir(parents=True, exist_ok=True)
    (out / "forecast.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    print(json.dumps({"area": area, "snapshot": stamp, "outlook_above_normal": rep["official_outlook"]["above_normal_pct_band"],
                      "precip": {k: rep["precipitation"][k] for k in ("total_16d_mm", "wettest_day", "wettest_day_mm",
                                                                       "wettest_day_point_max_mm", "max_single_point_day",
                                                                       "max_single_point_day_mm")},
                      "river": {k: rep["river"][k] for k in ("model_outlet", "glofas_cell", "peak_ensemble_mean_m3s",
                                                             "peak_day", "peak_percentile_of_clim_days")}
                      | {"clim": rep["river"]["clim"]},
                      "mapping": rep["mapping"]}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
