"""No-Earth-Engine downloads (charter M-02 fallback): fetch, clip to a lon/lat box, check, write a sidecar."""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import math
import os
import shutil
import time
from pathlib import Path

import numpy as np
import rasterio
import requests
from rasterio.merge import merge

UA = "igad-flood-ews-mvp/0.1 (hackathon data download)"
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.tiff,.vrt,.zip")
os.environ.setdefault("GDAL_HTTP_USERAGENT", UA)
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "5")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "3")


def download(url: str, dest: Path, tries: int = 5) -> Path:
    """Whole-file download with retries; skipped if dest exists. Writes to .part then renames."""
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(tries):
        try:
            have = part.stat().st_size if part.exists() else 0   # resume a partial file (worldpop.org stalls)
            hdr = {"User-Agent": UA, **({"Range": f"bytes={have}-"} if have else {})}
            with requests.get(url, headers=hdr, stream=True, timeout=(30, 60)) as r:
                if r.status_code == 416:          # already complete
                    break
                r.raise_for_status()
                mode = "ab" if have and r.status_code == 206 else "wb"
                with open(part, mode) as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            break
        except requests.RequestException:
            if attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    part.rename(dest)
    return dest


def gunzip(src: Path, dest: Path) -> Path:
    if not dest.exists():
        with gzip.open(src, "rb") as fi, open(dest, "wb") as fo:
            shutil.copyfileobj(fi, fo)
    return dest


def snap_bounds(bbox, transform) -> tuple:
    """Grow bbox [w,s,e,n] outward to the native pixel EDGES of a north-up grid (F2.1). GLO-30 is pixel-centre
    registered on whole degrees (tile edge at 35.0 - 0.5 px), so 34.70 is a pixel CENTRE there; clipping at it
    shifted the DEM half a pixel. Tolerance 1e-6 px so float noise does not add a column."""
    a, e_, x0, y0 = transform.a, transform.e, transform.c, transform.f
    eps = 1e-6
    col_w = math.floor((bbox[0] - x0) / a + eps)
    col_e = math.ceil((bbox[2] - x0) / a - eps)
    row_n = math.floor((bbox[3] - y0) / e_ + eps)      # e_ < 0
    row_s = math.ceil((bbox[1] - y0) / e_ - eps)
    return (x0 + col_w * a, y0 + row_s * e_, x0 + col_e * a, y0 + row_n * e_)


def clip(sources: list[str], bbox, dest: Path) -> Path:
    """Mosaic + clip `sources` (local paths or /vsicurl/ URLs, same native grid) to bbox [w,s,e,n], with the bounds
    first snapped outward to the sources' native pixel edges so no value is shifted or resampled (F2.1/F2.2)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dss = [rasterio.open(s) for s in sources]
    try:
        bounds = snap_bounds(bbox, dss[0].transform)
        arr, transform = merge(dss, bounds=bounds, res=(dss[0].res[0], dss[0].res[1]))
        prof = dss[0].profile.copy()
        prof.update(driver="GTiff", height=arr.shape[1], width=arr.shape[2], transform=transform,
                    count=arr.shape[0], compress="deflate", tiled=True, blockxsize=256, blockysize=256,
                    BIGTIFF="IF_SAFER")
        prof.pop("photometric", None)
        with rasterio.open(dest, "w", **prof) as out:
            out.write(arr)
    finally:
        for d in dss:
            d.close()
    return dest


def warp_read(src: str, bbox, res: float, resampling=None) -> np.ndarray:
    """Read any-CRS raster `src` resampled onto a WGS84 grid covering bbox at `res` degrees (NaN = nodata)."""
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.vrt import WarpedVRT
    w, s, e, n = bbox
    width, height = round((e - w) / res), round((n - s) / res)
    tr = from_origin(w, n, res, res)
    with rasterio.open(src) as ds, WarpedVRT(ds, crs="EPSG:4326", transform=tr, width=width, height=height,
                                             resampling=resampling or Resampling.bilinear,
                                             src_nodata=ds.nodata, nodata=np.nan, dtype="float32") as vrt:
        return vrt.read(1)


def write_wgs84(arr: np.ndarray, bbox, res: float, dest: Path, nodata=np.nan) -> Path:
    from rasterio.transform import from_origin
    dest.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dest, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                       dtype=arr.dtype, crs="EPSG:4326", transform=from_origin(bbox[0], bbox[3], res, res),
                       nodata=nodata, compress="deflate") as ds:
        ds.write(arr, 1)
    return dest


def grid_phase_px(transform, native) -> tuple:
    """Offset of `transform`'s origin from `native`'s origin, in native pixels (integers when on-grid)."""
    return ((transform.c - native.c) / native.a, (transform.f - native.f) / native.e)


def stats(path: Path, bbox) -> dict:
    """The M-02 checks: bounds cover bbox (within one pixel), nodata share, value range."""
    with rasterio.open(path) as ds:
        a = ds.read(1, masked=True)
        b = ds.bounds
        px = max(abs(ds.res[0]), abs(ds.res[1]))
        nod = ds.nodata
        valid = a.compressed()
        if np.issubdtype(valid.dtype, np.floating):
            valid = valid[np.isfinite(valid)]
        covers = (b.left <= bbox[0] + px and b.bottom <= bbox[1] + px
                  and b.right >= bbox[2] - px and b.top >= bbox[3] - px)
        return {
            "crs": str(ds.crs), "res": [ds.res[0], ds.res[1]], "shape": [ds.height, ds.width],
            "dtype": ds.dtypes[0], "nodata": nod,
            "bounds": [round(b.left, 6), round(b.bottom, 6), round(b.right, 6), round(b.top, 6)],
            "covers_bbox": bool(covers),
            "min": float(valid.min()) if valid.size else None,
            "max": float(valid.max()) if valid.size else None,
            "mean": float(valid.mean()) if valid.size else None,
            "nodata_share": round(1 - valid.size / a.size, 6),
            "all_nodata": valid.size == 0,
        }


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sidecar(path: Path, *, product: str, sources: list[str], bbox, date_range=None,
            native_scale: str, licence: str, note: str = "") -> dict:
    meta = {
        "file": path.name, "product": product, "source_urls": sources, "requested_bbox_wgs84": list(bbox),
        "date_range": date_range, "native_scale": native_scale, "licence": licence,
        "retrieved_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "route": "no-EE fallback (direct download); Earth Engine not authenticated",
        "sha256": sha256(path), **stats(path, bbox),
    }
    if note:
        meta["note"] = note
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return meta
