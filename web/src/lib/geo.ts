import type { FloodCollection, Risk } from "./types";

function inRing(x: number, y: number, ring: number[][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function inPolygon(x: number, y: number, poly: number[][][]): boolean {
  if (!inRing(x, y, poly[0])) return false;
  for (let h = 1; h < poly.length; h++) if (inRing(x, y, poly[h])) return false;
  return true;
}

const RANK: Record<Risk, number> = { low: 1, medium: 2, high: 3 };

/** Highest flood risk class covering a point, or null if the point is dry. */
export function riskAt(flood: FloodCollection, lon: number, lat: number): Risk | null {
  let best: Risk | null = null;
  for (const f of flood.features) {
    const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
    if (polys.some((p) => inPolygon(lon, lat, p))) {
      const r = f.properties.risk;
      if (!best || RANK[r] > RANK[best]) best = r;
    }
  }
  return best;
}

/** Highest risk class within ~radius degrees of a point (samples a small cross). */
export function riskNear(flood: FloodCollection, lon: number, lat: number, radiusDeg: number): Risk | null {
  const pts: [number, number][] = [[0, 0]];
  for (const k of [0.5, 1]) {
    const r = radiusDeg * k;
    pts.push([r, 0], [-r, 0], [0, r], [0, -r]);
  }
  let best: Risk | null = null;
  for (const [dx, dy] of pts) {
    const r = riskAt(flood, lon + dx, lat + dy);
    if (r && (!best || RANK[r] > RANK[best])) best = r;
  }
  return best;
}
