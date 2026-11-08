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

/** Every POLYGON of every feature (a feature is one MultiPolygon per risk class with thousands of polygons, so a
 * per-feature box filters nothing), bucketed in a grid of CELL_DEG cells by its box padded with the search radius. */
const CELL_DEG = 0.002; // ~220 m
type Poly = { k: number; poly: number[][][] };
type Index = { polys: Poly[]; cells: Map<string, number[]> };
const indexes = new WeakMap<FloodCollection, Map<number, Index>>();
function polyIndex(flood: FloodCollection, r: number): Index {
  let byR = indexes.get(flood);
  if (!byR) indexes.set(flood, (byR = new Map()));
  const hit = byR.get(r);
  if (hit) return hit;
  const pad = r / M_PER_DEG_LAT / 0.98; // degrees, generous enough in longitude below |lat| 10
  const polys: Poly[] = [];
  const cells = new Map<string, number[]>();
  flood.features.forEach((f, k) => {
    const list = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
    for (const poly of list) {
      let w = Infinity, so = Infinity, e = -Infinity, n = -Infinity;
      for (const [x, y] of poly[0]) {
        if (x < w) w = x;
        if (x > e) e = x;
        if (y < so) so = y;
        if (y > n) n = y;
      }
      const id = polys.push({ k, poly }) - 1;
      for (let i = Math.floor((w - pad) / CELL_DEG); i <= Math.floor((e + pad) / CELL_DEG); i++)
        for (let j = Math.floor((so - pad) / CELL_DEG); j <= Math.floor((n + pad) / CELL_DEG); j++) {
          const c = `${i},${j}`;
          const l = cells.get(c);
          if (l) l.push(id);
          else cells.set(c, [id]);
        }
    }
  });
  const idx = { polys, cells };
  byR.set(r, idx);
  return idx;
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
  const { polys, cells } = polyIndex(flood, r);
  let risk: Risk | null = null;
  let depthMax = 0;
  let metres = 0;
  for (const p of sampleLine(coords)) {
    let hit = false;
    for (const id of cells.get(`${Math.floor(p.lon / CELL_DEG)},${Math.floor(p.lat / CELL_DEG)}`) ?? []) {
      const { k, poly } = polys[id];
      const props = flood.features[k].properties;
      // a polygon of a feature already counted at this sample cannot raise risk or depth: skip the geometry test
      if (hit && risk && RANK[props.risk] <= RANK[risk] && props.depth_m <= depthMax) continue;
      if (!touches(p.lon, p.lat, poly, r)) continue;
      hit = true;
      if (!risk || RANK[props.risk] > RANK[risk]) risk = props.risk;
      if (props.depth_m > depthMax) depthMax = props.depth_m;
    }
    if (hit) metres += p.w;
  }
  return risk ? { risk, depthMax, metres } : null;
}
