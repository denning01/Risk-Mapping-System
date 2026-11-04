/**
 * Runtime schemas for every file in the data contract (docs/DATA_CONTRACT.md).
 * Person A's pipeline output is validated against these. Shapes must not change
 * without updating the contract doc and telling Person A.
 */
import { z } from "zod";

export const AREA_IDS = ["nairobi", "nyando"] as const;
export const RAIN_VALUES = [50, 100, 150, 200, 250] as const;
export const ENSO_VALUES = ["normal", "elnino"] as const;
export const RISK_LEVELS = ["low", "medium", "high"] as const;

const LonLat = z.tuple([z.number(), z.number()]);
const BBox = z.tuple([z.number(), z.number(), z.number(), z.number()]);

export const AreaSchema = z.object({
  id: z.enum(AREA_IDS),
  name: z.string(),
  type: z.enum(["urban", "rural"]),
  bbox: BBox,
  center: LonLat,
  zoom: z.number(),
  user_types: z.array(z.string()).min(1),
});
export const AreasSchema = z.array(AreaSchema).min(1);

const Position = z.array(z.number()).min(2);
const PolygonGeom = z.object({
  type: z.literal("Polygon"),
  coordinates: z.array(z.array(Position)),
});
const MultiPolygonGeom = z.object({
  type: z.literal("MultiPolygon"),
  coordinates: z.array(z.array(z.array(Position))),
});
export const LineStringGeom = z.object({
  type: z.literal("LineString"),
  coordinates: z.array(Position),
});

export const FloodFeatureSchema = z.object({
  type: z.literal("Feature"),
  geometry: z.union([PolygonGeom, MultiPolygonGeom]),
  properties: z.object({
    risk: z.enum(RISK_LEVELS),
    depth_m: z.number(),
    arrival_h: z.number().nullable(),
  }),
});
export const FloodCollectionSchema = z.object({
  type: z.literal("FeatureCollection"),
  features: z.array(FloodFeatureSchema),
});

export const ExposureSchema = z.object({
  year: z.number().int(),
  population: z.object({ low: z.number(), medium: z.number(), high: z.number() }),
  buildings: z.number(),
  flooded_area_km2: z.number(),
  roads_cut: z.array(z.string()),
  source: z.string(),
});

export const ShelterSchema = z.object({
  id: z.string(),
  name: z.string(),
  type: z.enum(["school", "church", "hospital", "community_hall", "high_ground"]),
  lon: z.number(),
  lat: z.number(),
  capacity: z.number().nullable(),
  safe: z.boolean(),
});
export const SheltersSchema = z.array(ShelterSchema);

export const OriginSchema = z.object({
  id: z.string(),
  name: z.string(),
  lon: z.number(),
  lat: z.number(),
  user_type: z.string(),
});
export const OriginsSchema = z.array(OriginSchema).min(1);

const RouteLeg = z.object({ geometry: LineStringGeom, minutes: z.number() });
export const RouteSchema = z.object({
  origin_id: z.string(),
  kind: z.enum(["to_shelter", "commute", "relocation"]),
  shelter_id: z.string().nullable(),
  destination_name: z.string(),
  baseline: RouteLeg.nullable(),
  safe: RouteLeg,
  avoided: z.array(z.string()),
});
export const RoutesSchema = z.array(RouteSchema);

export const CropRuleSchema = z.object({
  crop: z.string(),
  season: z.enum(["short_rains", "long_rains"]),
  enso: z.enum(ENSO_VALUES),
  risk: z.enum(RISK_LEVELS),
  actions: z.array(z.string()).min(1),
  sources: z.array(z.string()).min(1),
});
export const CropsSchema = z.array(CropRuleSchema).min(1);

export const MetaSchema = z.object({
  mock: z.boolean(),
  generated_at: z.string(),
  sources: z.array(z.string()),
  notes: z.string(),
});

export const PopulationSchema = z.object({
  area: z.enum(AREA_IDS),
  base_year: z.literal(2019),
  assumptions: z.object({ low: z.number(), medium: z.number(), high: z.number() }),
  placeholder: z.boolean(),
  units: z
    .array(
      z.object({
        unit: z.string(),
        level: z.enum(["county", "subcounty"]),
        p2009: z.number(),
        p2019: z.number(),
        r: z.number(),
        projections: z.record(z.string(), z.object({ low: z.number(), medium: z.number(), high: z.number() })),
      }),
    )
    .min(1),
});

/** Validate data and log a clear error. Returns the parsed value or throws. */
export function validate<T>(schema: z.ZodType<T>, data: unknown, label: string): T {
  const res = schema.safeParse(data);
  if (!res.success) {
    const issues = res.error.issues
      .slice(0, 5)
      .map((i) => `  - ${i.path.join(".") || "(root)"}: ${i.message}`)
      .join("\n");
    const msg = `[data contract] ${label} does not match the contract:\n${issues}`;
    console.error(msg);
    throw new Error(msg);
  }
  return res.data;
}
