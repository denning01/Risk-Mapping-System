"""Load configs/<area>.yaml and derive what must not be typed by hand (the UTM zone)."""
from __future__ import annotations

import math
from pathlib import Path

import yaml
from pyproj import Geod, Transformer

from .paths import CONFIG_DIR

REQUIRED = ("id", "name", "type", "bbox", "dem", "backtest_event", "before_period", "user_types")
_GEOD = Geod(ellps="WGS84")


def utm_epsg(lon: float, lat: float) -> int:
    """WGS84 / UTM EPSG for a point: 326zz north of the equator, 327zz south (zone = floor((lon+180)/6)+1)."""
    if not (-180 <= lon < 180 and -80 <= lat <= 84):
        raise ValueError(f"outside UTM range: {lon}, {lat}")
    zone = int(math.floor((lon + 180) / 6)) + 1
    return (32600 if lat >= 0 else 32700) + zone


def bbox_area_km2_geodesic(bbox) -> float:
    w, s, e, n = bbox
    area, _ = _GEOD.polygon_area_perimeter([w, e, e, w], [s, s, n, n])
    return abs(area) / 1e6


def bbox_area_km2_utm(bbox, epsg: int, densify: int = 50) -> float:
    """Second method: densified bbox ring projected to UTM, shoelace area."""
    w, s, e, n = bbox
    t = [i / densify for i in range(densify)]
    ring = ([(w + (e - w) * f, s) for f in t] + [(e, s + (n - s) * f) for f in t]
            + [(e - (e - w) * f, n) for f in t] + [(w, n - (n - s) * f) for f in t])
    tr = Transformer.from_crs(4326, epsg, always_xy=True)
    xy = [tr.transform(x, y) for x, y in ring]
    a = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(xy, xy[1:] + xy[:1]))
    return abs(a) / 2 / 1e6


def load(area: str, config_dir: Path | None = None) -> dict:
    path = (config_dir or CONFIG_DIR) / f"{area}.yaml"
    cfg = yaml.safe_load(path.read_text())
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise ValueError(f"{path}: missing keys {missing}")
    if "utm_epsg" in cfg:
        raise ValueError(f"{path}: utm_epsg is derived from the bbox centre; do not type it")
    if cfg["id"] != area:
        raise ValueError(f"{path}: id {cfg['id']!r} != file name {area!r}")
    w, s, e, n = cfg["bbox"]
    if not (w < e and s < n):
        raise ValueError(f"{path}: bbox must be [west, south, east, north], got {cfg['bbox']}")
    zones = {utm_epsg(w, (s + n) / 2) % 100, utm_epsg(e - 1e-9, (s + n) / 2) % 100}
    if len(zones) > 1:
        raise ValueError(f"{path}: bbox straddles UTM zones {sorted(zones)}")
    if "export_bbox" in cfg:
        ew, es, ee_, en = cfg["export_bbox"]
        if not (ew <= w and es <= s and ee_ >= e and en >= n):
            raise ValueError(f"{path}: export_bbox {cfg['export_bbox']} must contain bbox {cfg['bbox']}")
    else:
        cfg["export_bbox"] = list(cfg["bbox"])
    hb = cfg.setdefault("handoff_bbox", list(cfg["bbox"]))
    eb = cfg["export_bbox"]
    if not (eb[0] <= hb[0] and eb[1] <= hb[1] and eb[2] >= hb[2] and eb[3] >= hb[3]):
        raise ValueError(f"{path}: export_bbox {eb} must contain handoff_bbox {hb}")
    # M-07: which DEM file 01 writes and 02 reads. FABDEM (buildings/trees removed) for the urban area; GLO-30 otherwise.
    cfg["dem_file"] = "dem_fabdem.tif" if "FABDEM" in str(cfg["dem"]) else "dem_glo30.tif"
    cfg["center"] = [(w + e) / 2, (s + n) / 2]
    cfg["utm_epsg"] = utm_epsg(*cfg["center"])
    cfg["area_km2"] = bbox_area_km2_geodesic(cfg["bbox"])
    return cfg


def areas() -> list[str]:
    return sorted(p.stem for p in CONFIG_DIR.glob("*.yaml"))
