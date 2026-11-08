// M-16 · FROM -> TO in the browser, both areas. The expected alternatives come from web/src/lib/routing.ts run here in
// Node on the committed graph.json (held to scipy and to the Python reference in route-trip-client.spec.ts); wet checks
// from the flood GeoJSON (geo.ts riskAt), in the app's order. SHELTER CONSTRAINT: the trip is an added option; clearing
// it brings back the preset's published nearest-safe-place route, and shelters / relocation sites stay drawn throughout.
import { expect, test, type Page } from "@playwright/test";
import { riskAt } from "../web/src/lib/geo";
import type { FloodCollection } from "../web/src/lib/types";
import { checkGraph, prepareGraph, routeBetween, type GraphJson, type PreparedGraph, type TripPoint } from "../web/src/lib/routing";
import { floodNextTo } from "../web/src/lib/tripAnalysis";
import { areas, card, openScenario, readJson, safeCardTitle, watch } from "./helpers";
import { fixture } from "./weather-fixture";
import { clickAt, tapAt, wetPoints } from "./map-helpers";

const IT = { useInnerText: true };
const graphs = new Map<string, PreparedGraph>();
const graph = (a: string) => {
  if (!graphs.has(a)) graphs.set(a, prepareGraph(checkGraph(readJson<GraphJson>(`${a}/graph.json`))));
  return graphs.get(a)!;
};
type O = { id: string; name: string; lon: number; lat: number };
type S = { id: string; name: string; lon: number; lat: number; safe: boolean; type: string };
const PNG_1X1 = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "base64");

async function quietNetwork(page: Page) {
  await page.route("https://api.open-meteo.com/**", (r) => {
    const u = new URL(r.request().url());
    return r.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify(fixture(Number(u.searchParams.get("longitude")), Number(u.searchParams.get("latitude")))),
    });
  });
  // basemap tiles as a 1x1 PNG so the map reaches "idle" and reports what it draws
  await page.route(
    (u) => u.host.endsWith("tile.openstreetmap.org"),
    (r) => r.fulfill({ status: 200, contentType: "image/png", headers: { "access-control-allow-origin": "*" }, body: PNG_1X1 }),
  );
}

/** The app's order for a trip: wet start -> wet destination (a named place, not a safe shelter) -> the client. */
function expectedTrip(area: string, key: string, from: TripPoint, to: TripPoint) {
  const flood = readJson<FloodCollection>(`${area}/scenarios/${key}.geojson`);
  if (riskAt(flood, from.lon, from.lat)) return { ok: false as const, reason: "wet_start" };
  if (!to.targetId && riskAt(flood, to.lon, to.lat)) return { ok: false as const, reason: "wet_dest" };
  return routeBetween(graph(area), key, from, to);
}

for (const area of areas()) {
  test(`${area.id}: from a preset to a safe place -> 3 alternatives drawn, analysis per route, weather at the destination; clear -> the nearest-safe-place route`, async ({ page, baseURL }) => {
    const errors = await watch(page, baseURL!);
    await quietNetwork(page);
    const rain = 100, enso = "normal", key = `${rain}_${enso}`;
    const origins = readJson<O[]>(`${area.id}/origins.json`);
    const shelters = readJson<S[]>(`${area.id}/scenarios/${key}.shelters.json`);
    const routes = readJson<{ origin_id: string; safe: { geometry: { coordinates: number[][] } } }[]>(`${area.id}/scenarios/${key}.routes.json`);
    // the first (preset, safe place) pair, in file order, with all three alternatives
    let pick: { o: O; s: S; alts: ReturnType<typeof routeBetween> & { ok: true } } | null = null;
    for (const row of routes) {
      const o = origins.find((x) => x.id === row.origin_id)!;
      for (const s of shelters.filter((x) => x.safe)) {
        const r = expectedTrip(area.id, key, o, { lon: s.lon, lat: s.lat, targetId: s.id });
        if (r.ok && r.alts.length === 3) {
          pick = { o, s, alts: r };
          break;
        }
      }
      if (pick) break;
    }
    expect(pick, "a preset and a safe place with three alternatives").not.toBeNull();
    const { o, s, alts } = pick!;
    const flood = readJson<FloodCollection>(`${area.id}/scenarios/${key}.geojson`);
    const map = page.locator(".maplibregl-map");
    await openScenario(page, area, rain, enso);
    const shelterCount = String(shelters.length);
    const highGround = String(shelters.filter((x) => x.type === "high_ground").length);
    await page.locator("select#origin").selectOption(o.id);
    const published = routes.find((r) => r.origin_id === o.id)!.safe.geometry.coordinates.length;
    await expect(map).toHaveAttribute("data-route-points", String(published));

    const t = card(page, "Plan a trip (from → to)");
    await expect(t).toContainText(`From: ${o.name}`, IT);
    await page.locator("select#trip-dest").selectOption(`s:${s.id}`);
    const radios = t.getByRole("radio");
    await expect(radios).toHaveCount(3);
    for (const [i, a] of alts.alts.entries()) {
      const r = t.locator(`[data-alt="${a.label}"]`);
      await expect(r).toContainText(`${a.minutes} min · ${(a.metres / 1000).toFixed(1)} km`, IT);
      await expect(r).toContainText(`${Math.round(a.nearM)} m on paths within 30 m of flood water`, IT);
      const fl = floodNextTo(flood, a.coords);
      await expect(r).toContainText(fl ? `up to ~${fl.depthMax} m deep` : "no mapped flood within 30 m", IT);
      if (a.extraMin > 0) await expect(r).toContainText(`+${a.extraMin} min`, IT);
      // choosing it draws it, the other two thin beside it
      await r.click();
      await expect(r).toHaveAttribute("aria-checked", "true");
      await expect(map).toHaveAttribute("data-route-points", String(a.coords.length));
      await expect(map).toHaveAttribute("data-alt-routes", "2");
      expect(i).toBeLessThan(3);
    }
    await expect(map).toHaveAttribute("data-dest", `${s.lon},${s.lat}`);
    await expect(page.locator(".dest-marker")).toHaveCount(1);
    const w = card(page, "My weather");
    await expect(w.locator('[data-weather-point="Where you are going"]')).toContainText(`Where you are going: ${s.name}`, IT);
    // shelters and relocation sites are all still drawn; the nearest-safe-place card is unchanged
    await expect(map).toHaveAttribute("data-shelters", shelterCount);
    await expect(map).toHaveAttribute("data-high-ground", highGround);
    await expect(card(page, safeCardTitle(area))).not.toContainText("Computed in your browser");

    await t.getByRole("button", { name: "Clear trip (back to nearest safe place)" }).click();
    await expect(map).toHaveAttribute("data-route-points", String(published));
    await expect(map).toHaveAttribute("data-alt-routes", "0");
    await expect(map).not.toHaveAttribute("data-dest", /./);
    await expect(page.locator(".dest-marker")).toHaveCount(0);
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test(`${area.id}: a trip to a flooded point -> no route; from a flooded tapped start -> the 1199 card`, async ({ page, baseURL }) => {
    const errors = await watch(page, baseURL!);
    await quietNetwork(page);
    const key = "250_elnino";
    const flood = readJson<FloodCollection>(`${area.id}/scenarios/${key}.geojson`);
    const origins = readJson<O[]>(`${area.id}/origins.json`);
    const dry = origins.find((o) => !riskAt(flood, o.lon, o.lat))!;
    await openScenario(page, area, 250, "elnino");
    const map = page.locator(".maplibregl-map");
    const t = card(page, "Plan a trip (from → to)");
    const wet = await wetPoints(page, flood);
    expect(wet.length).toBeGreaterThan(0);

    // (1) a dry preset start, the destination tapped inside the flood
    await page.locator("select#origin").selectOption(dry.id);
    let landed = false;
    for (const [lon, lat] of wet) {
      await t.getByRole("button", { name: "Pick destination on the map" }).click();
      if (!(await clickAt(page, lon, lat))) continue;
      await expect(map).toHaveAttribute("data-dest", /,/);
      const [dl, dt] = (await map.getAttribute("data-dest"))!.split(",").map(Number);
      if (!riskAt(flood, dl, dt)) continue; // the point the app took is not wet: try the next one
      landed = true;
      break;
    }
    expect(landed, "a wet destination reached the app").toBe(true);
    await expect(t.locator("[data-trip-refusal]")).toHaveAttribute("data-trip-refusal", "wet_dest");
    await expect(t).toContainText("This destination is inside the flood extent in this scenario", IT);
    await expect(t.getByRole("radio")).toHaveCount(0);
    await expect(map).toHaveAttribute("data-alt-routes", "0");

    // (2) the start tapped inside the flood, a safe place as the destination
    let started = false;
    for (const [lon, lat] of wet) {
      const got = await tapAt(page, lon, lat);
      if (got && riskAt(flood, got[0], got[1])) {
        started = true;
        break;
      }
    }
    expect(started, "a wet start reached the app").toBe(true);
    const safe = readJson<S[]>(`${area.id}/scenarios/${key}.shelters.json`).find((x) => x.safe)!;
    await page.locator("select#trip-dest").selectOption(`s:${safe.id}`);
    await expect(t.locator("[data-trip-refusal]")).toHaveAttribute("data-trip-refusal", "wet_start");
    await expect(t.getByRole("link", { name: "1199" })).toHaveAttribute("href", "tel:1199");
    await expect(map).toHaveAttribute("data-route-points", "0");
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test(`${area.id}: "Pick destination on the map" -> the tapped destination is routed, the start stays`, async ({ page, baseURL }) => {
    const errors = await watch(page, baseURL!);
    await quietNetwork(page);
    const key = "50_normal";
    const origins = readJson<O[]>(`${area.id}/origins.json`);
    await openScenario(page, area, 50, "normal");
    const o = origins[0];
    await page.locator("select#origin").selectOption(o.id);
    const t = card(page, "Plan a trip (from → to)");
    await t.getByRole("button", { name: "Pick destination on the map" }).click();
    await expect(t.getByRole("button", { name: "Tap the map for the destination…" })).toBeVisible();
    // tap the centre of the map (the opening view's centre); the app reports the point it took as data-dest
    const map = page.locator(".maplibregl-map");
    const box = (await map.boundingBox())!;
    await page.mouse.click(box.x + box.width * 0.55, box.y + box.height * 0.45);
    await expect(map).toHaveAttribute("data-dest", /,/);
    const [lon, lat] = (await map.getAttribute("data-dest"))!.split(",").map(Number);
    await expect(page.locator("select#origin")).toHaveValue(o.id); // the start did not move
    await expect(map).not.toHaveAttribute("data-tap", /./);
    const r = expectedTrip(area.id, key, o, { lon, lat });
    if (r.ok) {
      await expect(t.getByRole("radio")).toHaveCount(r.alts.length);
      await expect(map).toHaveAttribute("data-route-points", String(r.alts[0].coords.length));
      await expect(t.locator('[data-alt="fastest"]')).toContainText(`${r.alts[0].minutes} min`, IT);
    } else await expect(t.locator("[data-trip-refusal]")).toHaveAttribute("data-trip-refusal", r.reason);
    expect(errors, errors.join("\n")).toEqual([]);
  });
}
