// M-19 · the H3 hexagon risk layer (branch ui/route-weather only; the .h3.json files are byte copies of exposure's
// E-18/E-19/E-20 hand-off, not in the data contract).
//  (1) every hexagon outline drawn by h3-js == Python h3 4.5.0 cell_to_boundary (fixtures/hex-oracle.json), every row
//      of every published scenario, both areas;
//  (2) the files' hex sums == the published exposure.json (people low / medium / high, buildings);
//  (3) the popup wording, each branch;
//  (4) browser, both areas: toggle -> every row drawn, hexagons UNDER routes / shelters / reports, shelters and the
//      preset's route still drawn, survives a basemap switch; tapping hexagons -> the popup of the hexagon tapped,
//      line for line; toggle off -> none drawn.
import { expect, test } from "@playwright/test";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { cellToLatLng } from "../web/node_modules/h3-js"; // the app's pinned copy (e2e has no h3-js of its own)
import { hexFeatures, hexLines, type HexRow } from "../web/src/lib/hex";
import { areas, openScenario, readJson, watch } from "./helpers";
import { clickAt } from "./map-helpers";

const PNG_1X1 = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "base64");
const ORACLE: Record<string, Record<string, [number, number][]>> = JSON.parse(readFileSync(join(__dirname, "fixtures", "hex-oracle.json"), "utf8"));
const DATA = join(__dirname, "..", "web", "public", "data");
const hexKeys = (area: string) =>
  readdirSync(join(DATA, area, "scenarios"))
    .filter((f) => f.endsWith(".h3.json"))
    .map((f) => f.replace(".h3.json", ""));

for (const area of areas()) {
  test(`${area.id}: h3-js outlines == Python h3 on every hexagon of every scenario; hex sums == exposure.json`, () => {
    const keys = hexKeys(area.id);
    expect(keys.length).toBe(10);
    const bad: string[] = [];
    let polys = 0;
    let maxErr = 0;
    for (const key of keys) {
      const rows = readJson<HexRow[]>(`${area.id}/scenarios/${key}.h3.json`);
      const fc = hexFeatures(rows);
      expect(fc.features.length).toBe(rows.length);
      fc.features.forEach((f, i) => {
        const ring = f.geometry.coordinates[0];
        const want = ORACLE[area.id][rows[i].h3];
        if (!want || ring.length !== want.length + 1) return void bad.push(`${key} ${rows[i].h3}: ${ring.length} vs ${want?.length}`);
        for (let k = 0; k < want.length; k++) maxErr = Math.max(maxErr, Math.abs(ring[k][0] - want[k][0]), Math.abs(ring[k][1] - want[k][1]));
        if (ring[0][0] !== ring.at(-1)![0] || ring[0][1] !== ring.at(-1)![1]) bad.push(`${key} ${rows[i].h3}: ring not closed`);
        if (f.properties !== rows[i]) bad.push(`${key} ${rows[i].h3}: properties are not the row`);
        polys++;
      });
      const e = readJson<{ population: { low: number; medium: number; high: number }; buildings: number }>(`${area.id}/scenarios/${key}.exposure.json`);
      const sum = (k: keyof HexRow) => rows.reduce((s, r) => s + (r[k] as number), 0);
      const got = [sum("people_low"), sum("people_medium"), sum("people_high"), sum("buildings_flooded")];
      const want = [e.population.low, e.population.medium, e.population.high, e.buildings];
      if (JSON.stringify(got) !== JSON.stringify(want)) bad.push(`${key}: hex sums ${got} vs exposure.json ${want}`);
    }
    expect(bad).toEqual([]);
    expect(maxErr, "largest vertex difference, degrees").toBeLessThan(1e-9);
    expect(polys).toBeGreaterThan(area.id === "nyando" ? 30_000 : 3_000);
  });
}

test("hexLines: every branch of the popup wording", () => {
  const base: HexRow = {
    h3: "897a6e40083ffff", edge: false, flooded_share: 0.101, flooded_m2: 11700, depth_mean_m: 0.22, depth_max_m: 0.41, risk: "medium",
    buildings_flooded: 1234, people_low: 3000, people_medium: 3100, people_high: 3300, arrival_h_min: 3.36, walk_min: 16,
    shelter_id: "s1", shelter_reachable: true, no_route: null,
  };
  const names = new Map([["s1", "Moi School"], ["r1", "Ridge site"]]);
  expect(hexLines(base, names)).toEqual([
    "Medium risk (deepest water in this hexagon)",
    "Flooded: 10 % of the hexagon",
    "Depth: mean ~0.22 m, max ~0.41 m",
    "People in flooded buildings: 3,100 (range 3,000 to 3,300)",
    "Buildings flooded: 1,234",
    "Water could arrive in as little as ~3.3 h (screening estimate)", // arrival_h_min 3.36, rounded DOWN (F18.1)
    "Safe shelter reachable: ~16 min walk (Moi School)",
  ]);
  const reloc = hexLines({ ...base, walk_min: null, shelter_id: null, relocation_walk_min: 413, relocation_id: "r1", edge: true, arrival_h_min: 0 }, names);
  expect(reloc.slice(5)).toEqual([
    "Water could arrive within minutes (local rain or nearby stream)",
    "High ground reachable: ~413 min walk (Ridge site)",
    "At the edge of the study area: only the part inside it is counted",
  ]);
  const cut = { ...base, walk_min: null, shelter_id: null, shelter_reachable: false };
  expect(hexLines({ ...cut, no_route: "inside_flood" }, names).at(-1)).toBe("No dry way out: shelter in place or on an upper floor; emergency 1199");
  expect(hexLines({ ...cut, no_route: "cut_off_outside_flood" }, names).at(-1)).toBe("Cut off: no dry road or path from here reaches a safe place");
  expect(hexLines({ ...base, arrival_h_min: undefined }, names)).not.toContain("Water could arrive");
});

for (const area of areas()) {
  test(`${area.id}: Hexagons on -> all drawn under routes and shelters, popups line for line, kept across a basemap switch; off -> none`, async ({ page, baseURL }) => {
    test.slow();
    const errors = await watch(page, baseURL!);
    await page.route("https://api.open-meteo.com/**", (r) => r.fulfill({ status: 503, body: "" }));
    // raster tiles answered (1x1) so the map reaches "idle" (the data-* hooks are read then); EOX too, so Satellite loads
    await page.route(
      (u) => ["tile.openstreetmap.org", "tiles.maps.eox.at"].includes(u.host),
      (r) => r.fulfill({ status: 200, contentType: "image/png", headers: { "access-control-allow-origin": "*" }, body: PNG_1X1 }),
    );
    const key = "250_elnino";
    const rows = readJson<HexRow[]>(`${area.id}/scenarios/${key}.h3.json`);
    const byH3 = new Map(rows.map((r) => [r.h3, r]));
    const shelters = readJson<{ id: string; name: string }[]>(`${area.id}/scenarios/${key}.shelters.json`);
    const names = new Map(shelters.map((s) => [s.id, s.name]));
    const origin = readJson<{ id: string }[]>(`${area.id}/origins.json`)[0];
    await openScenario(page, area, 250, "elnino");
    await page.locator("select#origin").selectOption(origin.id);
    const map = page.locator("[data-basemap]");
    await expect(map).toHaveAttribute("data-route-points", /^[1-9]/);
    const routePts = await map.getAttribute("data-route-points");
    const btn = page.getByRole("button", { name: "Hexagons", exact: true });
    await expect(map).toHaveAttribute("data-hex", "off");

    await btn.click();
    await expect(btn).toHaveAttribute("aria-pressed", "true");
    await expect(map).toHaveAttribute("data-hexes", String(rows.length));
    await expect(map).toHaveAttribute("data-layer-order", "flood-fill,hex-fill,route-alt,route-safe,shelters,reports");
    await expect(map).toHaveAttribute("data-shelters", String(shelters.length));
    await expect(map).toHaveAttribute("data-route-points", routePts!);
    await expect(page.locator("[data-hex-note]")).toContainText("H3 resolution 9");

    // the popups: tap hexagon centres of each kind until each kind has shown its popup; check whichever hexagon opened
    const kinds: [string, (r: HexRow) => boolean][] = [
      ["shelter", (r) => r.walk_min !== null],
      ["no_route", (r) => r.no_route !== null],
      ...(area.id === "nyando" ? ([["relocation", (r: HexRow) => (r.relocation_walk_min ?? null) !== null]] as [string, (r: HexRow) => boolean][]) : []),
    ];
    const checked: string[] = [];
    const bad: string[] = [];
    for (const [kind, has] of kinds) {
      const cands = rows.filter(has).sort((a, b) => b.flooded_share - a.flooded_share).slice(0, 12);
      for (const r of cands) {
        await page.locator(".maplibregl-popup-close-button").click({ timeout: 500 }).catch(() => {});
        const [lat, lon] = cellToLatLng(r.h3);
        if (!(await clickAt(page, lon, lat))) continue;
        const pop = page.locator(".maplibregl-popup [data-hex-popup]");
        try {
          await expect(pop).toHaveCount(1, { timeout: 2000 });
        } catch {
          continue; // a shelter, marker or a hexagon-free pixel took the click
        }
        const h3 = (await pop.getAttribute("data-hex-popup"))!;
        const row = byH3.get(h3);
        if (!row) {
          bad.push(`popup for ${h3}, not in the file`);
          break;
        }
        const lines = await pop.evaluate((el) => Array.from(el.children).map((c) => c.textContent ?? ""));
        const want = [...hexLines(row, names), "Scenario estimate, not a forecast"];
        if (JSON.stringify(lines) !== JSON.stringify(want)) bad.push(`${h3}: ${JSON.stringify(lines)} vs ${JSON.stringify(want)}`);
        if (has(row)) {
          checked.push(kind);
          break;
        }
      }
    }
    expect(bad).toEqual([]);
    expect(checked, "kinds of hexagon whose popup was checked").toEqual(kinds.map((k) => k[0]));

    // a basemap switch reloads the style: the hexagons come back
    await page.getByRole("radiogroup", { name: "Basemap" }).getByRole("radio", { name: "Satellite" }).click();
    await expect(map).toHaveAttribute("data-style", "eox-s2cloudless");
    await expect(map).toHaveAttribute("data-hexes", String(rows.length));
    await expect(map).toHaveAttribute("data-layer-order", "flood-fill,hex-fill,route-alt,route-safe,shelters,reports");

    await btn.click();
    await expect(map).toHaveAttribute("data-hex", "off");
    await expect(map).toHaveAttribute("data-hexes", "0");
    await expect(page.locator("[data-hex-note]")).toHaveCount(0);
    expect(errors.filter((e) => !e.includes("open-meteo")), errors.join("\n")).toEqual([]);
  });
}
