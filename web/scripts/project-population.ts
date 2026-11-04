/**
 * Census-calibrated population projection (Person B owns this).
 *
 * Input : data-inputs/census.csv   columns: area,unit,level,p2009,p2019
 * Output: public/data/{area}/population.json  + a printed table showing the working
 *
 * Why county / sub-county level: ward boundaries changed between the 2009 and 2019
 * censuses (wards were created in 2013), so ward-level growth rates are not comparable.
 *
 * Maths:
 *   r      = (p2019 / p2009)^(1/10) - 1
 *   P(t)   = p2019 * (1 + r)^(t - 2019)
 *   low    uses r * 0.7, medium uses r, high uses r * 1.2   (ASSUMPTIONS, state them on the slide)
 *
 * Run: npm run population
 */
import fs from "node:fs";
import path from "node:path";
import { AREA_IDS } from "../src/lib/schema";
import { SCENARIO_MULTIPLIERS, growthRate, parseCensusCsv, projectScenarios } from "./lib/population";

const ROOT = path.join(__dirname, "..");
const csv = fs.readFileSync(path.join(ROOT, "data-inputs", "census.csv"), "utf8");
const { rows, placeholder } = parseCensusCsv(csv);
const now = new Date().getFullYear();
const years = [now, now + 10];

if (placeholder) {
  console.warn("WARNING: census.csv is marked PLACEHOLDER. Replace it with verified KNBS figures before the pitch.\n");
}

const fmt = (n: number) => n.toLocaleString("en-US");
console.log(
  ["area", "unit", "p2009", "p2019", "r", ...years.flatMap((y) => [`${y} low`, `${y} med`, `${y} high`])].join(" | "),
);

for (const area of AREA_IDS) {
  const units = rows
    .filter((r) => r.area === area)
    .map((row) => {
      const r = growthRate(row.p2009, row.p2019);
      const projections = Object.fromEntries(years.map((y) => [String(y), projectScenarios(row.p2019, r, y)]));
      console.log(
        [
          area,
          row.unit,
          fmt(row.p2009),
          fmt(row.p2019),
          `${(r * 100).toFixed(3)}%  [(${row.p2019}/${row.p2009})^(1/10) - 1]`,
          ...years.flatMap((y) => {
            const p = projections[String(y)];
            return [fmt(p.low), fmt(p.medium), fmt(p.high)];
          }),
        ].join(" | "),
      );
      return { unit: row.unit, level: row.level, p2009: row.p2009, p2019: row.p2019, r: Number(r.toFixed(6)), projections };
    });
  if (!units.length) {
    console.warn(`No census rows for area "${area}", skipping.`);
    continue;
  }
  const out = { area, base_year: 2019, assumptions: SCENARIO_MULTIPLIERS, placeholder, units };
  const file = path.join(ROOT, "public", "data", area, "population.json");
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(out, null, 2));
}
console.log(`\nAssumptions: growth multipliers low=${SCENARIO_MULTIPLIERS.low}, medium=${SCENARIO_MULTIPLIERS.medium}, high=${SCENARIO_MULTIPLIERS.high}`);
console.log("Written public/data/{area}/population.json");
