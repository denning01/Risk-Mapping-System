import type { z } from "zod";
import type {
  AreaSchema,
  CropRuleSchema,
  ExposureSchema,
  FloodCollectionSchema,
  FloodFeatureSchema,
  MetaSchema,
  OriginSchema,
  PopulationSchema,
  RouteSchema,
  ShelterSchema,
  AREA_IDS,
  ENSO_VALUES,
  RAIN_VALUES,
  RISK_LEVELS,
} from "./schema";

export type AreaId = (typeof AREA_IDS)[number];
export type Rain = (typeof RAIN_VALUES)[number];
export type Enso = (typeof ENSO_VALUES)[number];
export type Risk = (typeof RISK_LEVELS)[number];

export type Area = z.infer<typeof AreaSchema>;
export type FloodFeature = z.infer<typeof FloodFeatureSchema>;
export type FloodCollection = z.infer<typeof FloodCollectionSchema>;
export type Exposure = z.infer<typeof ExposureSchema>;
export type Shelter = z.infer<typeof ShelterSchema>;
export type Origin = z.infer<typeof OriginSchema>;
export type Route = z.infer<typeof RouteSchema>;
export type CropRule = z.infer<typeof CropRuleSchema>;
export type Meta = z.infer<typeof MetaSchema>;
export type Population = z.infer<typeof PopulationSchema>;

export interface Scenario {
  flood: FloodCollection;
  exposure: Exposure;
  shelters: Shelter[];
  routes: Route[];
}

export const RISK_COLORS: Record<Risk, string> = {
  low: "#facc15",
  medium: "#f97316",
  high: "#dc2626",
};
