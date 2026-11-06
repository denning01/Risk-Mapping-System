"""M-06 model -> exposure hand-off checks (AGENTS.md § model -> exposure interface).

Exposure's 07_scenarios.py refuses a depth/hand/channels raster whose footprint does not cover the area's bbox
to within half a pixel. A WGS84 box is not a rectangle in UTM (its edges bow), so its projected extent is taken
from a DENSIFIED edge transform (pyproj transform_bounds, densify_pts) — four corners can under-cover.
"""
from __future__ import annotations

import math

from pyproj import Transformer

DENSIFY = 101
MIN_MARGIN_PX = 1.0


def projected_bounds(bbox_wgs84, crs) -> tuple:
    """(xmin, ymin, xmax, ymax) in `crs` of the WGS84 box [w, s, e, n], edges densified."""
    return Transformer.from_crs(4326, crs, always_xy=True).transform_bounds(*bbox_wgs84, densify_pts=DENSIFY)


def margin_px(transform, width: int, height: int, crs, bbox_wgs84) -> float:
    """Smallest distance, in pixels, by which the raster footprint extends beyond the projected bbox on any side
    (negative = the bbox sticks out of the raster)."""
    a, e = transform.a, transform.e
    x0, y1 = transform.c, transform.f
    x1, y0 = x0 + width * a, y1 + height * e
    bx0, by0, bx1, by1 = projected_bounds(bbox_wgs84, crs)
    return min((bx0 - x0) / a, (x1 - bx1) / a, (by0 - y0) / -e, (y1 - by1) / -e)


def covers(transform, width, height, crs, bbox_wgs84, min_margin_px=MIN_MARGIN_PX) -> bool:
    return margin_px(transform, width, height, crs, bbox_wgs84) >= min_margin_px


def grid_for(bbox_wgs84, crs, res: float, pad_px: int = 1):
    """A north-up grid (transform, width, height) at `res` that covers the bbox's densified projection + pad_px."""
    from affine import Affine
    bx0, by0, bx1, by1 = projected_bounds(bbox_wgs84, crs)
    x0 = math.floor(bx0 / res) * res - pad_px * res
    y1 = math.ceil(by1 / res) * res + pad_px * res
    w = math.ceil((bx1 + pad_px * res - x0) / res)
    h = math.ceil((y1 - (by0 - pad_px * res)) / res)
    return Affine(res, 0, x0, 0, -res, y1), w, h
