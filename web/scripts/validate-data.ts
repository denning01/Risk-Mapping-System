/**
 * Validates every file under public/data against the data contract.
 * Run after generating mock data AND after dropping in Person A's real files:
 *   npm run validate:data
 * Exits with code 1 and lists every problem if anything is missing or malformed.
 */
import fs from "node:fs";
import path from "node:path";
import type { z } from "zod";
import {
  AREA_IDS,
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
} from "../src/lib/schema";

const DATA = path.join(__dirname, "..", "public", "data");
const errors: string[] = [];
let checked = 0;

function check(rel: string, schema: z.ZodType, optional = false) {
  const file = path.join(DATA, rel);
  if (!fs.existsSync(file)) {
    if (!optional) errors.push(`MISSING  ${rel}`);
    return;
  }
  checked++;
  let json: unknown;
  try {
    json = JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (e) {
    errors.push(`BAD JSON ${rel}: ${(e as Error).message}`);
    return;
  }
  const res = schema.safeParse(json);
  if (!res.success) {
    const first = res.error.issues.slice(0, 3).map((i) => `${i.path.join(".") || "(root)"}: ${i.message}`);
    errors.push(`INVALID  ${rel}\n           ${first.join("\n           ")}`);
  }
}

check("areas.json", AreasSchema);
check("meta.json", MetaSchema);
check("advice/crops.json", CropsSchema);
for (const area of AREA_IDS) {
  check(`${area}/origins.json`, OriginsSchema);
  check(`${area}/population.json`, PopulationSchema, true);
  for (const rain of RAIN_VALUES) {
    for (const enso of ENSO_VALUES) {
      const base = `${area}/scenarios/${rain}_${enso}`;
      check(`${base}.geojson`, FloodCollectionSchema);
      check(`${base}.exposure.json`, ExposureSchema);
      check(`${base}.shelters.json`, SheltersSchema);
      check(`${base}.routes.json`, RoutesSchema);
    }
  }
}

if (errors.length) {
  console.error(`Data contract check FAILED (${errors.length} problem(s), ${checked} files read):\n`);
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log(`Data contract check passed: ${checked} files valid.`);
