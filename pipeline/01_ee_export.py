"""M-02 exports for one area into $RMS_DATA/raw/<area>/, each raster with a sidecar .json.

    .venv/bin/python pipeline/01_ee_export.py nyando --no-ee

--no-ee  (Earth Engine not authenticated) fetches the public copies directly:
  dem_glo30.tif        Copernicus GLO-30 DEM, AWS open data  s3://copernicus-dem-30m (COG, read by window)
  worldcover_2021.tif  ESA WorldCover 10 m v200 (2021), AWS  s3://esa-worldcover
  jrc_occurrence.tif   JRC Global Surface Water v1.4 occurrence (1984-2021), %, Google Cloud Storage
  worldpop_2020.tif    WorldPop Kenya 2020, 100 m, unconstrained (ken_ppp_2020), worldpop.org
  chirps/daily/        CHIRPS v2.0 Africa daily, 0.05 deg, 2023-10-01..2023-12-31 (event season)
  chirps/monthly/      CHIRPS v2.0 Africa monthly, Oct/Nov/Dec 1991-2023 (1991-2020 = WMO normal; full record for ranks)
All are clipped to the config's export_bbox (wider than the AOI; see configs/<area>.yaml).
The Sentinel-1 2023 flood mask needs Earth Engine and is NOT produced on this route.
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.lib import config, fetch  # noqa: E402
from pipeline.lib.paths import raw_dir  # noqa: E402

CHIRPS = "https://data.chc.ucsb.edu/products/CHIRPS/v2.0"
SOILGRIDS = "https://files.isric.org/soilgrids/latest/data"
SOIL_RES = 0.0025   # deg (~280 m), close to SoilGrids' native 250 m
CHIRPS_LIC = "CHIRPS: public domain (CC0); cite Funk et al. 2015, doi:10.1038/sdata.2015.66"


def _ns(lat, width=2):
    return f"{'N' if lat >= 0 else 'S'}{abs(lat):0{width}d}"


def glo30_urls(bbox):
    w, s, e, n = bbox
    urls = []
    for lat in range(math.floor(s), math.floor(n) + 1):
        for lon in range(math.floor(w), math.floor(e) + 1):
            name = f"Copernicus_DSM_COG_10_{_ns(lat)}_00_E{lon:03d}_00_DEM"
            urls.append(f"https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif")
    return urls


def worldcover_urls(bbox):
    w, s, e, n = bbox
    urls = []
    for lat in range(math.floor(s / 3) * 3, math.floor(n / 3) * 3 + 1, 3):
        for lon in range(math.floor(w / 3) * 3, math.floor(e / 3) * 3 + 1, 3):
            urls.append("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
                        f"ESA_WorldCover_10m_2021_v200_{_ns(lat, 2)}E{lon:03d}_Map.tif")
    return urls


def jrc_urls(bbox):
    w, s, e, n = bbox  # tiles are 10 deg, named by their top-left corner
    urls = []
    for top in range(math.ceil(n / 10) * 10, math.ceil(s / 10) * 10 - 1, -10):
        if top - 10 >= n or top <= s:
            continue
        for left in range(math.floor(w / 10) * 10, math.floor(e / 10) * 10 + 1, 10):
            lat = f"{abs(top)}{'N' if top >= 0 else 'S'}"
            urls.append("https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/"
                        f"occurrence_{left}E_{lat}v1_4_2021.tif")
    return urls


def vsi(urls):
    return [f"/vsicurl/{u}" for u in urls]


def chirps_job(url, cache: Path, dest: Path, bbox, date_range):
    if dest.exists() and dest.with_suffix(".json").exists():
        return json.loads(dest.with_suffix(".json").read_text())
    gz = fetch.download(url, cache / url.rsplit("/", 1)[1])
    tif = fetch.gunzip(gz, gz.with_suffix(""))
    fetch.clip([str(tif)], bbox, dest)
    meta = fetch.sidecar(dest, product="CHIRPS v2.0 Africa", sources=[url], bbox=bbox, date_range=date_range,
                         native_scale="0.05 deg", licence=CHIRPS_LIC, note="units: mm; nodata -9999")
    gz.unlink(missing_ok=True)
    tif.unlink(missing_ok=True)
    return meta


def run(area: str, use_ee: bool, only: set[str] | None):
    cfg = config.load(area)
    box = cfg["export_bbox"]
    out = raw_dir(area)
    out.mkdir(parents=True, exist_ok=True)
    if use_ee:
        raise SystemExit("EE route not written yet: Earth Engine is not authenticated (BLOCKED:ee-auth)")
    want = lambda k: only is None or k in only  # noqa: E731
    report = {}
    singles = [
        ("dem", "dem_glo30.tif", glo30_urls(box), "Copernicus DEM GLO-30 (DSM)", "1 arcsec (~30 m)",
         "Copernicus DEM (c) DLR e.V. 2010-2014 and (c) Airbus 2014-2018, provided under COPERNICUS by the "
         "European Union and ESA; free licence",
         # F2.4: "Data were acquired by the TanDEM-X mission between 2011 and 2015." (pre-2011 = gap fill)
         # https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM
         ["2011-01-01", "2015-12-31"]),
        ("worldcover", "worldcover_2021.tif", worldcover_urls(box), "ESA WorldCover 10 m 2021 v200", "10 m",
         "(c) ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021); CC BY 4.0",
         ["2021-01-01", "2021-12-31"]),
        ("jrc", "jrc_occurrence.tif", jrc_urls(box), "JRC Global Surface Water v1.4 occurrence", "0.00025 deg (~28 m)",
         "Pekel et al. 2016, Nature 540:418-422; EC JRC/Google; CC BY 4.0", ["1984-03-16", "2021-12-31"]),
        ("worldpop", "worldpop_2020.tif",
         ["https://data.worldpop.org/GIS/Population/Global_2000_2020/2020/KEN/ken_ppp_2020.tif"],
         "WorldPop Kenya 2020 unconstrained, people per pixel", "3 arcsec (~100 m)",
         "WorldPop (www.worldpop.org), doi:10.5258/SOTON/WP00645; CC BY 4.0", ["2020-01-01", "2020-12-31"]),
    ]
    for key, fname, urls, product, scale, lic, dr in singles:
        if not want(key):
            continue
        dest = out / fname
        print(f"[{key}] {len(urls)} source(s) -> {dest}", flush=True)
        try:
            fetch.clip(vsi(urls), box, dest)
        except Exception as err:  # e.g. worldpop.org: "Range downloading not supported by this server!"
            print(f"[{key}] windowed read failed ({err}); downloading whole file(s) then clipping", flush=True)
            local = [fetch.download(u, out / "_cache" / u.rsplit("/", 1)[1]) for u in urls]
            fetch.clip([str(p) for p in local], box, dest)
            # kept in _cache (outside git): worldpop.org cannot resume, so a re-clip must not need a re-download
        report[key] = fetch.sidecar(dest, product=product, sources=urls, bbox=box, date_range=dr,
                                    native_scale=scale, licence=lic)
        print(json.dumps({k: report[key][k] for k in ("shape", "covers_bbox", "min", "max", "nodata_share")}),
              flush=True)

    if want("soilgrids"):
        # Topsoil texture for hydrologic soil groups (M-04). Thickness-weighted mean over 0-30 cm.
        layers = (("0-5cm", 5), ("5-15cm", 10), ("15-30cm", 15))
        for var in ("clay", "sand"):
            urls = [f"{SOILGRIDS}/{var}/{var}_{d}_mean.vrt" for d, _ in layers]
            acc = sum(fetch.warp_read(f"/vsicurl/{u}", box, SOIL_RES) * t for u, (_, t) in zip(urls, layers))
            pct = (acc / sum(t for _, t in layers) / 10.0).astype("float32")   # g/kg -> %
            dest = fetch.write_wgs84(pct, box, SOIL_RES, out / f"soilgrids_{var}_0-30cm.tif")
            report[f"soilgrids_{var}"] = fetch.sidecar(
                dest, product=f"SoilGrids 2.0 {var} content, thickness-weighted mean 0-30 cm (%)", sources=urls,
                bbox=box, native_scale="250 m (Interrupted Goode Homolosine), resampled bilinear to 0.0025 deg",
                licence="ISRIC SoilGrids 2.0, Poggio et al. 2021, doi:10.5194/soil-7-217-2021; CC BY 4.0",
                note="units: percent by mass (g/kg / 10); weights 5/10/15 cm")
            print(json.dumps({k: report[f"soilgrids_{var}"][k] for k in ("shape", "covers_bbox", "min", "max",
                                                                         "nodata_share")}), flush=True)

    cache = out / "_cache"
    jobs = []
    if want("chirps_daily"):
        for m in (10, 11, 12):
            for d in range(1, calendar.monthrange(2023, m)[1] + 1):
                f = f"chirps-v2.0.2023.{m:02d}.{d:02d}.tif.gz"
                day = f"2023-{m:02d}-{d:02d}"
                jobs.append((f"{CHIRPS}/africa_daily/tifs/p05/2023/{f}", out / "chirps" / "daily" / f"{day}.tif",
                             [day, day]))
    if want("chirps_monthly"):
        for y in range(1991, 2024):   # F5.3: the FULL record 1991-2023, so a rank is over every season (no gaps)
            for m in (10, 11, 12):
                last = calendar.monthrange(y, m)[1]
                jobs.append((f"{CHIRPS}/africa_monthly/tifs/chirps-v2.0.{y}.{m:02d}.tif.gz",
                             out / "chirps" / "monthly" / f"{y}-{m:02d}.tif",
                             [f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last}"]))
    if jobs:
        print(f"[chirps] {len(jobs)} files", flush=True)
        with ThreadPoolExecutor(2) as ex:  # CHC returns 429 at 4 workers
            metas = list(ex.map(lambda j: chirps_job(j[0], cache, j[1], box, j[2]), jobs))
        bad = [m["file"] for m in metas if m["all_nodata"] or not m["covers_bbox"]]
        report["chirps"] = {"files": len(metas), "bad": bad,
                            "min": min(m["min"] for m in metas), "max": max(m["max"] for m in metas)}
        print(json.dumps(report["chirps"]), flush=True)
    rep = out / "export_report.json"  # merge, so an --only run does not drop earlier products
    merged = json.loads(rep.read_text()) if rep.exists() else {}
    merged.update(report)
    rep.write_text(json.dumps(merged, indent=2, default=str))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("area")
    ap.add_argument("--no-ee", action="store_true", help="direct downloads (EE not authenticated)")
    ap.add_argument("--only", nargs="*", help="dem worldcover jrc worldpop soilgrids chirps_daily chirps_monthly")
    a = ap.parse_args()
    run(a.area, use_ee=not a.no_ee, only=set(a.only) if a.only else None)
