/** Pure population-projection maths (see scripts/project-population.ts). */

export const SCENARIO_MULTIPLIERS = { low: 0.7, medium: 1.0, high: 1.2 } as const;
export type ScenarioName = keyof typeof SCENARIO_MULTIPLIERS;

/** Annual compound growth rate between the 2009 and 2019 censuses. r = (p2019/p2009)^(1/10) - 1 */
export function growthRate(p2009: number, p2019: number): number {
  if (p2009 <= 0 || p2019 <= 0) throw new Error("Census counts must be positive");
  return Math.pow(p2019 / p2009, 1 / 10) - 1;
}

/** P(t) = p2019 * (1 + r)^(t - 2019) */
export function project(p2019: number, r: number, year: number): number {
  return p2019 * Math.pow(1 + r, year - 2019);
}

/** Low / medium / high projections using the scenario multipliers on r. */
export function projectScenarios(p2019: number, r: number, year: number): Record<ScenarioName, number> {
  return {
    low: Math.round(project(p2019, r * SCENARIO_MULTIPLIERS.low, year)),
    medium: Math.round(project(p2019, r * SCENARIO_MULTIPLIERS.medium, year)),
    high: Math.round(project(p2019, r * SCENARIO_MULTIPLIERS.high, year)),
  };
}

export interface CensusRow {
  area: string;
  unit: string;
  level: "county" | "subcounty";
  p2009: number;
  p2019: number;
}

/** Parse census.csv. Lines starting with # are comments. */
export function parseCensusCsv(text: string): { rows: CensusRow[]; placeholder: boolean } {
  const lines = text.split(/\r?\n/);
  const placeholder = lines.some((l) => l.startsWith("#") && l.toUpperCase().includes("PLACEHOLDER"));
  const data = lines.filter((l) => l.trim() && !l.startsWith("#"));
  const [header, ...body] = data;
  const cols = header.split(",").map((c) => c.trim());
  const expected = ["area", "unit", "level", "p2009", "p2019"];
  if (expected.some((c, i) => cols[i] !== c)) {
    throw new Error(`census.csv header must be: ${expected.join(",")} (got ${cols.join(",")})`);
  }
  const rows = body.map((line, i) => {
    const [area, unit, level, p2009, p2019] = line.split(",").map((c) => c.trim());
    if (level !== "county" && level !== "subcounty") throw new Error(`Row ${i + 2}: level must be county or subcounty`);
    const a = Number(p2009), b = Number(p2019);
    if (!Number.isFinite(a) || !Number.isFinite(b)) throw new Error(`Row ${i + 2}: p2009/p2019 must be numbers`);
    return { area, unit, level, p2009: a, p2019: b } as CensusRow;
  });
  return { rows, placeholder };
}
