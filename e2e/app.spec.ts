// E-14 · automated click-through of Person B's app on the committed data (web/public/data).
// Route LINES are drawn on the MapLibre canvas, which the DOM cannot see. A route "draws" here when
// (1) the routes.json the browser received has a LineString with >= 2 points for the origin, and
// (2) selecting the origin shows the route card with the file's destination and minutes.
import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  DATA,
  NO_ROUTE,
  RAINS,
  areas,
  card,
  expectExposure,
  openScenario,
  readJson,
  routeLines,
  safeCardTitle,
  scenarios,
  watch,
  type Origin,
  type Route,
} from "./helpers";

const meta = readJson<{ mock: boolean }>("meta.json");

test("the server serves every committed data file byte for byte", async ({ request }) => {
  // F10.5: population.json (Person B's) and advice/crops.json are served too
  const rels = ["areas.json", "meta.json", "advice/crops.json", ...areas().flatMap((a) => [`${a.id}/origins.json`, `${a.id}/population.json`])];
  for (const { area, rain, enso } of scenarios())
    for (const ext of ["geojson", "exposure.json", "shelters.json", "routes.json"]) rels.push(`${area.id}/scenarios/${rain}_${enso}.${ext}`);
  expect(rels.length).toBe(3 + 4 + 20 * 4); // areas, meta, crops, 2 x (origins, population), 20 scenarios x 4 files = 87
  for (const rel of rels) {
    const res = await request.get(`/data/${rel}`);
    expect(res.status(), rel).toBe(200);
    expect((await res.body()).equals(readFileSync(join(DATA, rel))), `${rel} differs from the committed file`).toBe(true);
  }
});

test("routes.json covers every origin except the stated no-route cases", () => {
  const seen: string[] = [];
  for (const { area, rain, enso } of scenarios()) {
    const origins = readJson<Origin[]>(`${area.id}/origins.json`);
    const routes = readJson<Route[]>(`${area.id}/scenarios/${rain}_${enso}.routes.json`);
    for (const o of origins) {
      const has = routes.some((r) => r.origin_id === o.id);
      expect(has, `${area.id} ${rain}_${enso} ${o.id}: route ${has ? "present but NO_ROUTE says none" : "missing"}`).toBe(!NO_ROUTE(area.id, rain, o.id));
      if (!has) seen.push(`${rain}_${enso}`);
    }
  }
  expect(seen.length).toBeGreaterThan(0); // the no-route case is exercised, not vacuous
});

test("labels agree: meta.mock is true while any exposure file is still mock, and false only when all are model", () => {
  const srcs = scenarios().map(({ area, rain, enso }) => readJson<{ source: string }>(`${area.id}/scenarios/${rain}_${enso}.exposure.json`).source);
  expect(srcs.length).toBe(20);
  for (const s of srcs) expect(["mock", "model"]).toContain(s);
  if (srcs.includes("mock")) expect(meta.mock, "an exposure file is mock but meta.json says mock:false").toBe(true);
  if (!meta.mock) expect(srcs.every((s) => s === "model")).toBe(true);
});

for (const { area, rain, enso } of scenarios()) {
  const id = `${area.id} ${rain}_${enso}`;
  const rel = `${area.id}/scenarios/${rain}_${enso}`;

  test(`${id}: loads with no console error; counter, badges and every route match the files`, async ({ page, baseURL }) => {
    const errors = await watch(page, baseURL!);
    const routesResp = page.waitForResponse((r) => r.url().endsWith(`/data/${rel}.routes.json`));
    await openScenario(page, area, rain, enso);
    const served = (await (await routesResp).json()) as Route[];

    const exposure = await expectExposure(page, `${rel}.exposure.json`);
    // F10.2: the roads-cut list is exposure.roads_cut, in the file's order (panels.tsx RoadsPanel)
    const roads = card(page, "Roads likely to be cut");
    if (exposure.roads_cut.length === 0) await expect(roads).toContainText("No main roads cut in this scenario.");
    else await expect(roads.locator("li")).toHaveText(exposure.roads_cut);
    // F10.2: the "N/M safe" badge counts shelters.json
    await expect(page.getByText("MOCK DATA", { exact: true })).toHaveCount(meta.mock ? 1 : 0);

    const origins = readJson<Origin[]>(`${area.id}/origins.json`);
    const routes = readJson<Route[]>(`${rel}.routes.json`);
    expect(served).toEqual(routes);
    const safe = card(page, safeCardTitle(area));
    const shelters = readJson<{ safe: boolean }[]>(`${rel}.shelters.json`);
    await expect(safe.getByText(`${shelters.filter((x) => x.safe).length}/${shelters.length} safe`, { exact: true })).toBeVisible();
    for (const o of origins) {
      await safe.locator("select#origin").selectOption(o.id);
      const r = routes.find((x) => x.origin_id === o.id);
      if (!r) {
        expect(NO_ROUTE(area.id, rain, o.id), `${o.id} has no route`).toBe(true);
        for (const t of ["Go to:", "Relocate to high ground", "Commute to", "min on foot"]) await expect(safe).not.toContainText(t);
        continue;
      }
      expect(r.safe.geometry.type).toBe("LineString");
      expect(r.safe.geometry.coordinates.length, `${o.id} route has < 2 points`).toBeGreaterThanOrEqual(2);
      for (const line of routeLines(r)) await expect(safe, `${o.id} (${o.name})`).toContainText(line);
      // F10.2: the route's "Avoid:" list is route.avoided, in order; absent when empty
      if (r.avoided.length) await expect(safe, `${o.id} avoided`).toContainText(`Avoid: ${r.avoided.join(", ")}`, { useInnerText: true });
      else await expect(safe, `${o.id} avoided`).not.toContainText("Avoid:");
    }
    expect(errors, errors.join("\n")).toEqual([]);
  });
}

// Origin in flood (operator ruling (a)): no route is drawn, which the test above asserts. The app does not yet tell the
// user why; Person B owns that message. test.fail() keeps this red-until-shipped visible without failing the suite;
// when the message ships this test passes "unexpectedly", the suite goes red, and test.fail() must come off.
for (const { area, rain, enso } of scenarios()) {
  for (const o of readJson<Origin[]>(`${area.id}/origins.json`)) {
    if (!NO_ROUTE(area.id, rain, o.id)) continue;
    test(`${area.id} ${rain}_${enso} ${o.id}: the no-route case tells the user to stay on high ground`, async ({ page, baseURL }) => {
      test.fail(true, "Person B has not shipped the no-route message yet");
      await watch(page, baseURL!);
      await openScenario(page, area, rain, enso);
      await card(page, safeCardTitle(area)).locator("select#origin").selectOption(o.id);
      await expect(card(page, safeCardTitle(area))).toContainText(/cut off|stay (where you are|on high ground)|no safe route/i, { timeout: 3_000 });
    });
  }
}

test("RAINS matches the app's RAIN_VALUES (web/src/lib/schema.ts)", () => {
  const src = readFileSync(join(__dirname, "..", "web", "src", "lib", "schema.ts"), "utf8");
  const m = src.match(/RAIN_VALUES = \[([^\]]*)\]/);
  expect(m?.[1].split(",").map((x) => Number(x.trim()))).toEqual([...RAINS]);
});
