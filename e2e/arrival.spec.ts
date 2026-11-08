// M-21 + F18.1/F18.2 · arrival wording. A flood FEATURE's arrival_h is the MEDIAN of its cells' fast-bound hours
// (exposure E-20), so it reads "within <band> here (typical ~X h), sooner in places" (RULING F18.1), never "as little as". Only a true minimum
// (a hexagon's arrival_h_min) reads "as little as ~X h", rounded DOWN. Under 1 h -> "within minutes (local rain or
// nearby stream)"; never "0 h". The browser test uses the PUBLISHED E-20 values (no injected data).
import { expect, test } from "@playwright/test";
import { readdirSync } from "node:fs";
import { join } from "node:path";
import { arrivalBand, arrivalMinSentence, arrivalSentence, arrivalTick } from "../web/src/lib/arrival";
import type { HexRow } from "../web/src/lib/hex";
import type { FloodCollection } from "../web/src/lib/types";
import { areas, openScenario, readJson, watch } from "./helpers";
import { riskAt } from "../web/src/lib/geo";
import { clickAt, panTo, pixelOf, settledView, wetPoints } from "./map-helpers";

const PNG_1X1 = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "base64");
/** Points inside ONE feature, 3 px from its edge at this zoom, on a lattice over its bbox (thin Nairobi features have
 * no wet ring centroid at the opening view); the centroid candidates first. */
function latticeWet(one: FloodCollection, zoom: number, max = 40): [number, number][] {
  const d = (3 * 360) / (512 * 2 ** zoom);
  const pts = one.features.flatMap((f) => (f.geometry.type === "Polygon" ? f.geometry.coordinates : f.geometry.coordinates.flat())).flat();
  const [w, e] = [Math.min(...pts.map((p) => p[0])), Math.max(...pts.map((p) => p[0]))];
  const [so, no] = [Math.min(...pts.map((p) => p[1])), Math.max(...pts.map((p) => p[1]))];
  const out: [number, number][] = [];
  for (let i = 1; i < 150 && out.length < max; i++)
    for (let j = 1; j < 150 && out.length < max; j++) {
      const lon = w + ((e - w) * i) / 150;
      const lat = so + ((no - so) * j) / 150;
      if ([[0, 0], [d, 0], [-d, 0], [0, d], [0, -d]].every(([dx, dy]) => riskAt(one, lon + dx, lat + dy))) out.push([lon, lat]);
    }
  return out;
}
const shownHours = (s: string) => Number(/~([0-9.]+) h/.exec(s)?.[1] ?? NaN);

test("the wording: median vs minimum, minutes under 1 h, never '0 h', never NaN; the minimum never overstated", () => {
  const MIN = "Water could arrive within minutes (local rain or nearby stream)";
  const MED_MIN = "Water could arrive within minutes here (local rain or nearby stream; screening estimate)";
  expect(arrivalSentence(0)).toBe(MED_MIN);
  expect(arrivalSentence(0.1)).toBe(MED_MIN);
  expect(arrivalSentence(0.99)).toBe(MED_MIN);
  expect(arrivalSentence(1)).toBe("Water could arrive within 1-3 h here (typical ~1 h), sooner in places (screening estimate)");
  expect(arrivalSentence(2.46)).toBe("Water could arrive within 1-3 h here (typical ~2.5 h), sooner in places (screening estimate)");
  expect(arrivalSentence(3)).toBe("Water could arrive within 3-6 h here (typical ~3 h), sooner in places (screening estimate)");
  expect(arrivalSentence(6)).toBe("Water could arrive within 3-6 h here (typical ~6 h), sooner in places (screening estimate)");
  expect(arrivalSentence(6.1)).toBe("Water could arrive in more than 6 h here (typical ~6.1 h), sooner in places (screening estimate)");
  expect(arrivalSentence(12.6)).toBe("Water could arrive in more than 6 h here (typical ~13 h), sooner in places (screening estimate)");
  // exposure's classify_arrival_band edges: <1 | 1<=h<3 | 3<=h<=6 | >6
  expect([0.99, 1, 2.99, 3, 6, 6.01].map(arrivalBand)).toEqual(["minutes", "1-3 h", "1-3 h", "3-6 h", "3-6 h", "more than 6 h"]);
  expect(arrivalSentence(null)).toBe("No arrival estimate for this area");
  expect(arrivalMinSentence(0.5)).toBe(MIN);
  expect(arrivalMinSentence(1.06)).toBe("Water could arrive in as little as ~1 h (screening estimate)");
  expect(arrivalMinSentence(2.46)).toBe("Water could arrive in as little as ~2.4 h (screening estimate)");
  expect(arrivalMinSentence(9.99)).toBe("Water could arrive in as little as ~9.9 h (screening estimate)");
  expect(arrivalMinSentence(12.9)).toBe("Water could arrive in as little as ~12 h (screening estimate)");
  expect([arrivalTick(0), arrivalTick(0.5), arrivalTick(1.04), arrivalTick(9.96), arrivalTick(NaN), arrivalTick(Infinity)]).toEqual([
    "minutes", "minutes", "~1 h", "~10 h", "", "",
  ]);
  const bad: string[] = [];
  for (let k = 0; k <= 8000; k++) {
    const h = k / 200; // 0 .. 40 h in 0.005 h steps
    const [med, min, tick] = [arrivalSentence(h), arrivalMinSentence(h), arrivalTick(h)];
    for (const t of [med, min, tick]) if (/(^|[^0-9.])0 h|~0(\.0)? h|NaN/.test(t)) bad.push(`${h}: ${t}`);
    if (/as little as/.test(med)) bad.push(`${h}: a median said "as little as"`);
    if (h >= 1 && !(shownHours(min) <= h)) bad.push(`${h}: minimum shown as ${shownHours(min)} h, later than ${h} h`);
  }
  expect(bad).toEqual([]);
});

test("F18.1 on the PUBLISHED E-20 values: no feature says 'as little as'; every hexagon's shown minimum <= its arrival_h_min", () => {
  const bad: string[] = [];
  const n = { features: 0, featuresHours: 0, hexes: 0, hexesHours: 0 };
  for (const area of areas()) {
    const files = readdirSync(join(__dirname, "..", "web", "public", "data", area.id, "scenarios"));
    for (const f of files.filter((x) => x.endsWith(".geojson"))) {
      for (const ft of readJson<FloodCollection>(`${area.id}/scenarios/${f}`).features) {
        const h = ft.properties.arrival_h;
        if (h === null || h === undefined) continue;
        n.features++;
        const s = arrivalSentence(h);
        if (/as little as/.test(s)) bad.push(`${area.id}/${f}: ${s}`);
        if (!s.includes(arrivalBand(h) === "more than 6 h" ? "in more than 6 h here" : `within ${arrivalBand(h)} here`)) bad.push(`${area.id}/${f} ${h}: band missing: ${s}`);
        if (h >= 1) {
          n.featuresHours++;
          if (!/sooner in places/.test(s) || Math.abs(shownHours(s) - h) > 0.051 * (h < 10 ? 1 : 10)) bad.push(`${area.id}/${f} ${h}: ${s}`);
        }
      }
    }
    for (const f of files.filter((x) => x.endsWith(".h3.json"))) {
      for (const r of readJson<HexRow[]>(`${area.id}/scenarios/${f}`)) {
        const h = r.arrival_h_min;
        if (h === null || h === undefined) continue;
        n.hexes++;
        if (h >= 1) {
          n.hexesHours++;
          if (!(shownHours(arrivalMinSentence(h)) <= h)) bad.push(`${area.id}/${f} ${r.h3} ${h}: ${arrivalMinSentence(h)}`);
        }
      }
    }
  }
  expect(bad).toEqual([]);
  expect(n.featuresHours, "published features with arrival_h >= 1 h").toBeGreaterThan(50);
  expect(n.hexesHours, "published hexagons with arrival_h_min >= 1 h").toBeGreaterThan(1000);
});

for (const area of areas()) {
  test(`${area.id}: popup and legend on the published arrival values: band + 'typical ~X h, sooner in places', the caveat, no "0 h"`, async ({ page, baseURL }) => {
    test.slow();
    const errors = await watch(page, baseURL!);
    await page.route("https://api.open-meteo.com/**", (r) => r.fulfill({ status: 503, body: "" }));
    await page.route(
      (u) => u.host === "tile.openstreetmap.org",
      (r) => r.fulfill({ status: 200, contentType: "image/png", headers: { "access-control-allow-origin": "*" }, body: PNG_1X1 }),
    );
    const flood = readJson<FloodCollection>(`${area.id}/scenarios/250_elnino.geojson`);
    const arr = flood.features.map((f) => f.properties.arrival_h as number);
    expect(arr.every((h) => typeof h === "number"), "E-20 published an arrival_h on every feature").toBe(true);
    await openScenario(page, area, 250, "elnino");
    await page.getByRole("button", { name: "Show arrival time" }).click();
    const legend = page.locator("[data-arrival-legend]");
    const max = Math.max(...arr);
    await expect(legend).toHaveText([arrivalTick(0), arrivalTick(max / 2), arrivalTick(max)].join(""));
    await expect(page.getByText("Typical arrival time (sooner in places)", { exact: true })).toBeVisible();
    await expect(page.locator("[data-arrival-caveat]")).toHaveText("screening estimate"); // F18.2
    await expect(page.locator("[data-arrival-caveat]")).toBeVisible();
    await expect(page.locator("body")).not.toContainText(/(^|[^0-9.])0 h\b/);

    // the popups: one feature under 1 h and one at >= 1 h. Nairobi's >= 1 h features are thin: none has a point 3 px
    // inside it at the opening view, so for a kind with no popup there, zoom in (mouse wheel) over its feature with the
    // most interior at 3 zoom levels in, and try again.
    const checked: string[] = [];
    const tryKind = async (kind: string, want: (h: number) => boolean, zoom: number, first: [number, number][] = []) => {
      // only points on screen (60 px in from the edges, as pixelOf requires); near the equator degrees ~ square
      const v = await settledView(page);
      const box = (await page.locator(".maplibregl-map").boundingBox())!;
      const dpp = 360 / (512 * 2 ** v.zoom);
      const onScreen = ([lon, lat]: [number, number]) => Math.abs(lon - v.lon) < (box.width / 2 - 70) * dpp && Math.abs(lat - v.lat) < (box.height / 2 - 70) * dpp;
      const ks = flood.features.map((_, k) => k).filter((k) => want(arr[k])).sort((a, b) => arr[b] - arr[a]);
      let clicks = 0; // each click waits for the camera and up to 2 s for a popup: cap them
      for (const k of ks) {
        const one = { ...flood, features: [flood.features[k]] };
        const pts = [...first, ...(await wetPoints(page, one, zoom)), ...latticeWet(one, zoom, 40)].filter(onScreen).slice(0, 8);
        first = [];
        for (const [lon, lat] of pts) {
          if (++clicks > 16) return false;
          await page.locator(".maplibregl-popup-close-button").click({ timeout: 500 }).catch(() => {});
          if (!(await clickAt(page, lon, lat))) continue;
          const pop = page.locator(".maplibregl-popup [data-arrival]");
          try {
            await expect(pop).toHaveCount(1, { timeout: 2000 });
          } catch {
            continue;
          }
          const text = (await pop.textContent()) ?? "";
          // the topmost feature at that pixel answers (features of one depth band overlap the next): its sentence must be
          // exactly that of a published feature, and that feature must be of the kind sought
          const owners = flood.features.map((_, j) => j).filter((j) => arrivalSentence(arr[j]) === text);
          expect(owners.length, `"${text}" belongs to no published feature`).toBeGreaterThan(0);
          expect(text).not.toContain("as little as");
          if (owners.some((j) => want(arr[j]))) return true;
        }
      }
      return false;
    };
    for (const [kind, want] of [["minutes", (h: number) => h < 1], ["hours", (h: number) => h >= 1]] as const) {
      const z0 = (await settledView(page)).zoom;
      if (await tryKind(kind, want, z0)) {
        checked.push(kind);
        continue;
      }
      const best = flood.features
        .map((_, k) => k)
        .filter((k) => want(arr[k]))
        .map((k) => latticeWet({ ...flood, features: [flood.features[k]] }, z0 + 3, 1))
        .find((pts) => pts.length);
      if (!best) continue;
      const [lon, lat] = best[0];
      await page.locator(".maplibregl-popup-close-button").click({ timeout: 500 }).catch(() => {});
      for (let i = 0; i < 10; i++) {
        if (!(await panTo(page, lon, lat))) break;
        const p = (await pixelOf(page, lon, lat))!;
        if ((await settledView(page)).zoom >= z0 + 3) break;
        await page.mouse.move(p.x, p.y);
        await page.mouse.wheel(0, -300);
      }
      if (await tryKind(kind, want, (await settledView(page)).zoom, [[lon, lat]])) checked.push(kind);
    }
    expect(checked, "popups checked").toEqual(["minutes", "hours"]);
    expect(errors.filter((e) => !e.includes("open-meteo")), errors.join("\n")).toEqual([]);
  });
}
