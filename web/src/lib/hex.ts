/**
 * M-19 · the H3 hexagon risk layer. Reads {area}/scenarios/{key}.h3.json (exposure E-18/E-19/E-20, res 9, one row per
 * hexagon with any wet 30 m cell) and turns it into GeoJSON with h3-js. Not part of docs/DATA_CONTRACT.md: these files
 * exist on branch ui/route-weather only (operator GO M-19).
 */
import { cellToBoundary } from "h3-js";
import type { FeatureCollection, Polygon } from "geojson";
import { arrivalMinSentence } from "./arrival";
import type { Risk } from "./types";

export interface HexRow {
  h3: string;
  /** the hexagon is not wholly inside the study-area box: only its inside part is counted */
  edge: boolean;
  flooded_share: number;
  flooded_m2: number;
  depth_mean_m: number;
  depth_max_m: number;
  /** contract class of the hexagon's DEEPEST cell */
  risk: Risk;
  buildings_flooded: number;
  people_low: number;
  people_medium: number;
  people_high: number;
  arrival_h_min?: number | null;
  arrival_h_min_slow?: number | null;
  arrival_band_min?: string | null;
  people_medium_by_band?: Record<string, number>;
  /** the PRIMARY (fastest safe) walk to a safe shelter, min over the hexagon's walk nodes */
  walk_min: number | null;
  shelter_id: string | null;
  /** Nyando: the same to the nearest relocation site (high ground) */
  relocation_walk_min?: number | null;
  relocation_id?: string | null;
  shelter_reachable: boolean | null;
  no_route: "inside_flood" | "cut_off_outside_flood" | null;
}

export const HEX_RES = 9;

/** One polygon per row, [lon, lat] order (h3-js formatAsGeoJson = true), ring closed; the row is the properties. */
export function hexFeatures(rows: HexRow[]): FeatureCollection<Polygon, HexRow> {
  return {
    type: "FeatureCollection",
    features: rows.map((r) => {
      const ring = cellToBoundary(r.h3, true);
      const [a, b] = [ring[0], ring[ring.length - 1]];
      if (a[0] !== b[0] || a[1] !== b[1]) ring.push(a);
      return { type: "Feature", geometry: { type: "Polygon", coordinates: [ring] }, properties: r };
    }),
  };
}

const n = (x: number) => x.toLocaleString("en-US");

/** The lines a hexagon's popup shows, in order (plain text; FloodMap escapes and joins them). */
export function hexLines(r: HexRow, names: Map<string, string>): string[] {
  const name = (id: string | null | undefined) => (id && names.get(id) ? ` (${names.get(id)})` : "");
  const lines = [
    `${r.risk[0].toUpperCase()}${r.risk.slice(1)} risk (deepest water in this hexagon)`,
    `Flooded: ${Math.round(r.flooded_share * 100)} % of the hexagon`,
    `Depth: mean ~${r.depth_mean_m} m, max ~${r.depth_max_m} m`,
    `People in flooded buildings: ${n(r.people_medium)} (range ${n(r.people_low)} to ${n(r.people_high)})`,
    `Buildings flooded: ${n(r.buildings_flooded)}`,
  ];
  if (r.arrival_h_min !== undefined) lines.push(arrivalMinSentence(r.arrival_h_min ?? null, r.arrival_band_min)); // a true minimum (F18.1), its band (F18.4)
  if (r.walk_min !== null && r.walk_min !== undefined) lines.push(`Safe shelter reachable: ~${r.walk_min} min walk${name(r.shelter_id)}`);
  if (r.relocation_walk_min !== null && r.relocation_walk_min !== undefined)
    lines.push(`High ground reachable: ~${r.relocation_walk_min} min walk${name(r.relocation_id)}`);
  if (r.no_route === "inside_flood") lines.push("No dry way out: shelter in place or on an upper floor; emergency 1199");
  else if (r.no_route === "cut_off_outside_flood") lines.push("Cut off: no dry road or path from here reaches a safe place");
  else if (!r.shelter_reachable) lines.push("No safe place reachable on foot in this scenario");
  if (r.edge) lines.push("At the edge of the study area: only the part inside it is counted");
  return lines;
}
