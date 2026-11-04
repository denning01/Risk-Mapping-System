/**
 * Client-side data loader. Every file is fetched once, validated against the
 * contract, and cached in memory so the rainfall slider feels instant.
 */
import type { z } from "zod";
import {
  AreasSchema,
  CropsSchema,
  ENSO_VALUES,
  ExposureSchema,
  FloodCollectionSchema,
  MetaSchema,
  OriginsSchema,
  PopulationSchema,
  RAIN_VALUES,
  RoutesSchema,
  SheltersSchema,
  validate,
} from "./schema";
import type { Area, AreaId, CropRule, Enso, Meta, Origin, Population, Rain, Scenario } from "./types";

const BASE = "/data";
const cache = new Map<string, Promise<unknown>>();

function load<T>(rel: string, schema: z.ZodType<T>): Promise<T> {
  const url = `${BASE}/${rel}`;
  if (!cache.has(url)) {
    const p = fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`Could not load ${rel} (HTTP ${res.status})`);
        return res.json();
      })
      .then((json) => validate(schema, json, rel));
    // drop failed requests from the cache so a retry can succeed
    p.catch(() => cache.delete(url));
    cache.set(url, p);
  }
  return cache.get(url) as Promise<T>;
}

export const loadAreas = (): Promise<Area[]> => load("areas.json", AreasSchema);
export const loadMeta = (): Promise<Meta> => load("meta.json", MetaSchema);
export const loadCrops = (): Promise<CropRule[]> => load("advice/crops.json", CropsSchema);
export const loadOrigins = (area: AreaId): Promise<Origin[]> => load(`${area}/origins.json`, OriginsSchema);
export const loadPopulation = (area: AreaId): Promise<Population | null> =>
  load(`${area}/population.json`, PopulationSchema).catch(() => null);

export async function loadScenario(area: AreaId, rain: Rain, enso: Enso): Promise<Scenario> {
  const base = `${area}/scenarios/${rain}_${enso}`;
  const [flood, exposure, shelters, routes] = await Promise.all([
    load(`${base}.geojson`, FloodCollectionSchema),
    load(`${base}.exposure.json`, ExposureSchema),
    load(`${base}.shelters.json`, SheltersSchema),
    load(`${base}.routes.json`, RoutesSchema),
  ]);
  return { flood, exposure, shelters, routes };
}

/** Warm the cache for every scenario of an area (fire and forget). */
export function preloadArea(area: AreaId) {
  for (const rain of RAIN_VALUES) for (const enso of ENSO_VALUES) loadScenario(area, rain, enso).catch(() => {});
}
