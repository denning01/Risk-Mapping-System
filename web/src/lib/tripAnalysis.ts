/**
 * M-16 route analysis: the flood NEXT TO a route, read from the scenario's flood GeoJSON (the polygons on the map).
 * The route line is sampled every <= SAMPLE_M metres; a sample "touches" a flood feature when it is inside the polygon or
 * within RADIUS_M of its boundary (local equirectangular metres: < 0.1 % error over 30 m at these latitudes).
 * Independent of the graph's near bit (which exposure computed from the wet RASTER): the two need not agree exactly.
 */
import type { FloodCollection, Risk } from "./types";

export const RADIUS_M = 30;
export const SAMPLE_M = 10;
const M_PER_DEG_LAT = 110574;
const RANK: Record<Risk, number> = { low: 1, medium: 2, high: 3 };

export interface FloodNext {
  /** highest risk class of any flood feature within RADIUS_M of the route */
  risk: Risk;
  /** largest depth_m of those features */
  depthMax: number;
  /** metres of the route line with a flood feature within RADIUS_M */
  metres: number;
}

type Box = { w: number; s: number; e: number; n: number };
const boxes = new WeakMap<FloodCollection, Box[]>();
function featureBoxes(flood: FloodCollection): Box[] {
  const hit = boxes.get(flood);
  if (hit) return hit;
  const out = flood.features.map((f) => {
    const b = { w: Infinity, s: Infinity, e: -Infinity, n: -Infinity };
    const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
    for (const p of polys)
      for (const [x, y] of p[0]) {
        if (x < b.w) b.w = x;
        if (x > b.e) b.e = x;
        if (y < b.s) b.s = y;
        if (y > b.n) b.n = y;
      }
    return b;
  });
  boxes.set(flood, out);
  return out;
}

function inRing(x: number, y: number, ring: number[][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** squared distance in metres from (px, py) to segment a-b, all in local metres */
function seg2(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax;
  const dy = by - ay;
  const L = dx * dx + dy * dy;
  const t = L ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L)) : 0;
  const qx = ax + t * dx - px;
  const qy = ay + t * dy - py;
  return qx * qx + qy * qy;
}

/** Is (lon, lat) inside the polygon (holes excluded) or within r metres of any of its rings? */
function touches(lon: number, lat: number, poly: number[][][], r: number): boolean {
  const kx = M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180);
  const ky = M_PER_DEG_LAT;
  const r2 = r * r;
  for (const ring of poly)
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++)
      if (seg2(0, 0, (ring[j][0] - lon) * kx, (ring[j][1] - lat) * ky, (ring[i][0] - lon) * kx, (ring[i][1] - lat) * ky) <= r2) return true;
  if (!inRing(lon, lat, poly[0])) return false;
  for (let h = 1; h < poly.length; h++) if (inRing(lon, lat, poly[h])) return false;
  return true;
}

/** Points every <= step metres along the line, with the length each one stands for. */
export function sampleLine(coords: [number, number][], step = SAMPLE_M): { lon: number; lat: number; w: number }[] {
  const out: { lon: number; lat: number; w: number }[] = [];
  for (let i = 1; i < coords.length; i++) {
    const [x0, y0] = coords[i - 1];
    const [x1, y1] = coords[i];
    const kx = M_PER_DEG_LAT * Math.cos((((y0 + y1) / 2) * Math.PI) / 180);
    const len = Math.hypot((x1 - x0) * kx, (y1 - y0) * M_PER_DEG_LAT);
    const n = Math.max(1, Math.ceil(len / step));
    for (let k = 0; k < n; k++) {
      const t = (k + 0.5) / n; // segment midpoints: each sample stands for len / n metres
      out.push({ lon: x0 + t * (x1 - x0), lat: y0 + t * (y1 - y0), w: len / n });
    }
  }
  return out;
}

/** Length of a lon/lat line in metres (same local metric as the samples). */
export function lineMetres(coords: [number, number][]): number {
  return sampleLine(coords, Infinity).reduce((s, p) => s + p.w, 0);
}

/** The flood within RADIUS_M of a route line, or null when none is. */
export function floodNextTo(flood: FloodCollection, coords: [number, number][], r = RADIUS_M): FloodNext | null {
  const B = featureBoxes(flood);
  const pts = sampleLine(coords);
  let risk: Risk | null = null;
  let depthMax = 0;
  let metres = 0;
  const pad = r / M_PER_DEG_LAT / 0.98; // degrees, generous enough in longitude below |lat| 10
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
  for (const [x, y] of coords) {
    w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y);
  }
  const near = flood.features
    .map((f, k) => ({ f, b: B[k] }))
    .filter(({ b }) => !(b.e < w - pad || b.w > e + pad || b.n < s - pad || b.s > n + pad));
  for (const p of pts) {
    let hit = false;
    near.forEach(({ f, b }) => {
      if (p.lon < b.w - pad || p.lon > b.e + pad || p.lat < b.s - pad || p.lat > b.n + pad) return;
      const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
      if (!polys.some((poly) => touches(p.lon, p.lat, poly, r))) return;
      hit = true;
      if (!risk || RANK[f.properties.risk] > RANK[risk]) risk = f.properties.risk;
      if (f.properties.depth_m > depthMax) depthMax = f.properties.depth_m;
    });
    if (hit) metres += p.w;
  }
  return risk ? { risk, depthMax, metres } : null;
}
