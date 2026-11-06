"""Shared raster I/O for the model scripts: reproject onto the area's UTM grid, write a tiled GeoTIFF."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, calculate_default_transform, reproject

RES = 30.0


def to_utm(src_path: Path, epsg: int, resampling=Resampling.bilinear, res=RES, like=None):
    with rasterio.open(src_path) as src:
        if like is None:
            tr, w, h = calculate_default_transform(src.crs, f"EPSG:{epsg}", src.width, src.height,
                                                   *src.bounds, resolution=res)
        else:
            tr, w, h = like["transform"], like["width"], like["height"]
        dst = np.full((h, w), np.nan, dtype="float32")
        reproject(rasterio.band(src, 1), dst, src_transform=src.transform, src_crs=src.crs,
                  dst_transform=tr, dst_crs=f"EPSG:{epsg}", resampling=resampling,
                  src_nodata=src.nodata, dst_nodata=np.nan)
    return dst, {"transform": tr, "width": w, "height": h, "crs": f"EPSG:{epsg}"}


def grid_of(path: Path) -> dict:
    with rasterio.open(path) as ds:
        return {"transform": ds.transform, "width": ds.width, "height": ds.height, "crs": ds.crs.to_string()}


def read(path: Path) -> np.ndarray:
    with rasterio.open(path) as ds:
        a = ds.read(1)
        if ds.nodata is not None and not np.isnan(ds.nodata) and a.dtype.kind == "f":
            a = np.where(a == ds.nodata, np.nan, a)
        return a


def write(path: Path, arr, grid, dtype="float32", nodata=np.nan):
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", height=grid["height"], width=grid["width"], count=1,
                       dtype=dtype, crs=grid["crs"], transform=grid["transform"], nodata=nodata,
                       compress="deflate", tiled=True, blockxsize=256, blockysize=256) as ds:
        ds.write(arr.astype(dtype), 1)
