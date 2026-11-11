"""M-01 AOI check: print each bbox's area/UTM and draw it over OpenStreetMap so a human can see it is
the right place. Independent place check: geocode named landmarks and the area's river with Nominatim.

    .venv/bin/python -m pipeline.lib.aoi_check nyando nairobi

Writes $RMS_DATA/processed/<area>/model/aoi/ (cached OSM tiles + geocodes) and
docs/slides/figures/methods_aoi_<area>.png. Network: tile.openstreetmap.org, nominatim.openstreetmap.org
(light use, cached, 1 req/s, generic User-Agent per their usage policies).
"""
from __future__ import annotations

import io
import json
import math
import sys
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import requests  # noqa: E402

from . import config  # noqa: E402
from .paths import REPO_ROOT, model_dir  # noqa: E402

UA = {"User-Agent": "igad-flood-ews-mvp/0.1 (hackathon AOI check)"}
# What a human expects to see. Reported as inside/outside, never asserted (the map is the check).
LANDMARKS = {
    # (Muhoroni dropped: Nominatim's hit sat ~13 km west of the town OSM labels. A wrong pin misleads.)
    "nyando": ["Ahero", "Awasi", "Kisumu"],
    "nairobi": ["Mathare", "Kibera", "Eastleigh", "Dandora"],
}
RIVER = {"nyando": "Nyando River", "nairobi": "Nairobi River"}


def _deg2tile(lon, lat, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def _tile2lonlat(x, y, z):
    n = 2 ** z
    return x / n * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))


def osm_mosaic(bbox, cache, max_tiles=25):
    w, s, e, n = bbox
    pad = 0.15 * max(e - w, n - s)
    w, s, e, n = w - pad, s - pad, e + pad, n + pad
    for z in range(16, 5, -1):
        x0, y0 = _deg2tile(w, n, z)
        x1, y1 = _deg2tile(e, s, z)
        xs, ys = range(int(x0), int(x1) + 1), range(int(y0), int(y1) + 1)
        if len(xs) * len(ys) <= max_tiles:
            break
    rows = []
    for ty in ys:
        row = []
        for tx in xs:
            f = cache / f"tile_{z}_{tx}_{ty}.png"
            if not f.exists():
                for attempt in range(4):
                    try:
                        r = requests.get(f"https://tile.openstreetmap.org/{z}/{tx}/{ty}.png", headers=UA, timeout=30)
                        r.raise_for_status()
                        break
                    except requests.RequestException:
                        if attempt == 3:
                            raise
                        time.sleep(5 * (attempt + 1))
                f.write_bytes(r.content)
                time.sleep(0.2)
            row.append(plt.imread(io.BytesIO(f.read_bytes()))[..., :3])
        rows.append(np.concatenate(row, axis=1))
    img = np.concatenate(rows, axis=0)
    lon0, lat1 = _tile2lonlat(xs[0], ys[0], z)
    lon1, lat0 = _tile2lonlat(xs[-1] + 1, ys[-1] + 1, z)
    # Tiles are Web Mercator; drawn on a lon/lat axis. Within 1.5 deg of the equator the y-scale
    # error of that shortcut is < 0.04 %, far below one pixel here.
    return img, (lon0, lon1, lat0, lat1), z


def nominatim(q, cache, polygon=False, limit=1):
    f = cache / ("geo_" + "".join(c if c.isalnum() else "_" for c in q) + f"_{limit}.json")
    if not f.exists():
        params = {"q": f"{q}, Kenya", "format": "json", "limit": limit}
        if polygon:
            params["polygon_geojson"] = 1
        for wait in (0, 5, 15, 30, 60):  # back off on 429 (Nominatim usage policy)
            time.sleep(wait)
            r = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers=UA, timeout=30)
            if r.status_code != 429:
                break
        r.raise_for_status()
        f.write_text(r.text)
        time.sleep(1.1)
    d = json.loads(f.read_text())
    return d if limit > 1 else (d[0] if d else None)


def _inside(bbox, lon, lat):
    w, s, e, n = bbox
    return w <= lon <= e and s <= lat <= n


def _lines(geojson):
    t, c = geojson["type"], geojson["coordinates"]
    return [c] if t == "LineString" else c if t == "MultiLineString" else []


def check(area: str) -> dict:
    cfg = config.load(area)
    bbox = cfg["bbox"]
    cache = model_dir(area) / "aoi"
    cache.mkdir(parents=True, exist_ok=True)
    w, s, e, n = bbox
    km_ew = config._GEOD.inv(w, cfg["center"][1], e, cfg["center"][1])[2] / 1000
    km_ns = config._GEOD.inv(cfg["center"][0], s, cfg["center"][0], n)[2] / 1000
    out = {
        "area": area, "bbox": bbox, "center": cfg["center"], "utm_epsg": cfg["utm_epsg"],
        "area_km2_geodesic": round(cfg["area_km2"], 2),
        "area_km2_utm": round(config.bbox_area_km2_utm(bbox, cfg["utm_epsg"]), 2),
        "extent_km_ew_ns": [round(km_ew, 2), round(km_ns, 2)],
        "landmarks": {},
    }
    img, ext, z = osm_mosaic(bbox, cache)
    fig, ax = plt.subplots(figsize=(8, 8 * (ext[3] - ext[2]) / (ext[1] - ext[0])))
    ax.imshow(img, extent=ext, origin="upper", interpolation="bilinear")
    ax.plot([w, e, e, w, w], [s, s, n, n, s], color="red", lw=2.5, label=f"AOI bbox ({out['area_km2_geodesic']:.0f} km²)")
    for name in LANDMARKS[area]:
        hit = nominatim(name, cache)
        if hit is None:
            out["landmarks"][name] = "NOT FOUND"
            continue
        lon, lat = float(hit["lon"]), float(hit["lat"])
        ins = _inside(bbox, lon, lat)
        out["landmarks"][name] = {"lon": round(lon, 4), "lat": round(lat, 4), "inside": ins}
        ax.plot(lon, lat, "o", color="blue" if ins else "grey", mec="white", ms=7)
        ax.annotate(name, (lon, lat), xytext=(4, 4), textcoords="offset points", fontsize=8,
                    bbox=dict(fc="white", alpha=0.7, lw=0))
    # A river in OSM is many ways; take every waterway hit whose name contains the river's first word.
    key = RIVER[area].split()[0].lower()
    hits = [h for h in nominatim(RIVER[area], cache, polygon=True, limit=10) or []
            if h.get("class") == "waterway" and key in (h.get("name") or "").lower() + " " + RIVER[area].lower()
            and "geojson" in h]
    lines = [line for h in hits for line in _lines(h["geojson"])]
    pts = [p for line in lines for p in line]
    for line in lines:
        a = np.array(line)
        ax.plot(a[:, 0], a[:, 1], color="cyan", lw=1.8)
    if pts:
        # F1.4: share inside by LENGTH in UTM metres (vertex counts depend on how densely a way is mapped)
        from pyproj import Transformer
        from shapely import LineString, box as sbox, ops
        to_utm = Transformer.from_crs(4326, cfg["utm_epsg"], always_xy=True).transform
        geoms = [ops.transform(to_utm, LineString(line)) for line in lines if len(line) > 1]
        aoi_utm = ops.transform(to_utm, sbox(*bbox).segmentize(0.001))
        total = sum(g.length for g in geoms)
        inside = sum(g.intersection(aoi_utm).length for g in geoms)
        west = min(pts, key=lambda p: p[0])
        out["river"] = {"name": RIVER[area], "osm": sorted(f"{h['osm_type']}/{h['osm_id']}" for h in hits),
                        "length_km": round(total / 1000, 1), "length_inside_km": round(inside / 1000, 1),
                        "share_inside_by_length": round(inside / total, 3) if total else None,
                        # westmost vertex of the mapped ways — NOT necessarily the mouth (F1.3)
                        "westmost_vertex": [round(west[0], 4), round(west[1], 4)]}
        ax.plot([], [], color="cyan", label=f"{RIVER[area]} ({len(hits)} OSM features via Nominatim)")
    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])
    ax.set_xlabel("longitude (°E)")
    ax.set_ylabel("latitude (°)")
    ax.set_title(f"{cfg['name']} — AOI {bbox}, UTM EPSG:{cfg['utm_epsg']}", fontsize=10)
    ax.legend(loc="lower left", fontsize=8)
    ax.text(0.99, 0.01, "Map © OpenStreetMap contributors (ODbL)", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=7, bbox=dict(fc="white", alpha=0.7, lw=0))
    png = REPO_ROOT / "docs" / "slides" / "figures" / f"methods_aoi_{area}.png"
    fig.savefig(png, dpi=110, bbox_inches="tight")
    plt.close(fig)
    out["png"] = str(png.relative_to(REPO_ROOT))
    out["osm_zoom"] = z
    (cache / "aoi_check.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    for a in sys.argv[1:] or config.areas():
        print(json.dumps(check(a), indent=2))
