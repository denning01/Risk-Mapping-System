import { test } from "node:test";
import assert from "node:assert/strict";
import { growthRate, parseCensusCsv, project, projectScenarios } from "./lib/population";

// Hand-calculated example:
//   r = (130000/100000)^(1/10) - 1 = 1.3^0.1 - 1 = 0.0265836
//   P(2026) = 130000 * 1.3^(7/10) = 130000 * 1.2016012 = 156,208
test("growth rate matches hand calculation", () => {
  const r = growthRate(100_000, 130_000);
  assert.ok(Math.abs(r - 0.0265836) < 1e-6, `r = ${r}`);
});

test("projection to 2026 matches hand calculation", () => {
  const r = growthRate(100_000, 130_000);
  assert.equal(Math.round(project(130_000, r, 2026)), 156_208);
});

test("projection to 2019 returns the 2019 count", () => {
  assert.equal(project(130_000, 0.03, 2019), 130_000);
});

test("scenarios are ordered low < medium < high", () => {
  const p = projectScenarios(130_000, growthRate(100_000, 130_000), 2026);
  assert.ok(p.low < p.medium && p.medium < p.high);
  assert.equal(p.medium, 156_208);
});

test("csv parser reads rows and the placeholder flag", () => {
  const { rows, placeholder } = parseCensusCsv("# PLACEHOLDER\narea,unit,level,p2009,p2019\nnyando,Test,county,100,130\n");
  assert.equal(placeholder, true);
  assert.deepEqual(rows[0], { area: "nyando", unit: "Test", level: "county", p2009: 100, p2019: 130 });
});
