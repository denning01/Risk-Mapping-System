// M-14 · route from a tapped point / the device's location, in the browser.
// The expected route for a point comes from web/src/lib/routing.ts run here in Node on the committed graph.json; that
// client is held to the Python reference client_route() edge for edge in route-client.spec.ts. Whether a point is wet
// comes from the scenario's flood GeoJSON (geo.ts riskAt, Person B's existing function).
// The map canvas is opaque: FloodMap exposes the camera (data-view "lon,lat,zoom") so a lon/lat becomes a pixel, and the
// point it received (data-tap), so the test routes from exactly the point the app used.
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { riskAt } from "../web/src/lib/geo";
import type { FloodCollection } from "../web/src/lib/types";
import { checkGraph, clientRoute, prepareGraph, relocationTargets, snapStart, type GraphJson, type PreparedGraph, type RouteResult } from "../web/src/lib/routing";
import { areas, card, openScenario, readJson, safeCardTitle, watch, type Area } from "./helpers";
import { fixture } from "./weather-fixture";

const IT = { useInnerText: true };
const ORACLE: { area: string; key: string; tap: string; lon: number; lat: number; error?: string }[] = JSON.parse(
  readFileSync(join(__dirname, "fixtures", "route-oracle.json"), "utf8"),
);
const LABEL: Record<string, string> = {
  school: "School",
  church: "Church",
  place_of_worship: "Place of worship",
  hospital: "Hospital",
  community_hall: "Community hall",
  police: "Police station",
};
const graphs = new Map<string, PreparedGraph>();
const graph = (a: string) => {
  if (!graphs.has(a)) graphs.set(a, prepareGraph(checkGraph(readJson<GraphJson>(`${a}/graph.json`))));
  return graphs.get(a)!;
};
type Expect = RouteResult | { ok: false; reason: "wet" | "far" | "no_relocation" };
const RURAL = new Set(areas().filter((a) => a.type === "rural").map((a) => a.id));
/** The outcome the app must show, in the app's order: wet -> (rural without relocation targets) -> far -> the client. */
function expected(area: string, rain: number, enso: string, lon: number, lat: number): Expect {
  const flood = readJson<FloodCollection>(`${area}/scenarios/${rain}_${enso}.geojson`);
  if (riskAt(flood, lon, lat)) return { ok: false, reason: "wet" };
  const P = graph(area);
  // operator ruling: a rural user is never routed to OSM shelters alone; graph.json v2 has no relocation targets
  if (RURAL.has(area) && relocationTargets(P.g) === 0) return { ok: false, reason: "no_relocation" };
  if (snapStart(P, lon, lat).m > 500) return { ok: false, reason: "far" };
  return clientRoute(P, `${rain}_${enso}`, lon, lat);
}

async function mockOpenMeteo(page: Page) {
  const asked: string[] = [];
  await page.route("https://api.open-meteo.com/**", (r) => {
    const u = new URL(r.request().url());
    asked.push(`${u.searchParams.get("longitude")},${u.searchParams.get("latitude")}`);
    const body = JSON.stringify(fixture(Number(u.searchParams.get("longitude")), Number(u.searchParams.get("latitude"))));
    return r.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body });
  });
  return asked;
}

/** The settled camera (data-view stops changing). */
async function settledView(page: Page) {
  const map = page.locator(".maplibregl-map");
  let last = "";
  await expect
    .poll(
      async () => {
        const v = (await map.getAttribute("data-view")) ?? "";
        const same = v !== "" && v === last;
        last = v;
        return same;
      },
      { intervals: [400], timeout: 15000 },
    )
    .toBe(true);
  const [lon, lat, zoom] = last.split(",").map(Number);
  return { lon, lat, zoom };
}

/** Web Mercator (MapLibre, 512 px tiles, no pitch or bearing): lon/lat -> pixel in the map container. */
async function pixelOf(page: Page, lon: number, lat: number) {
  const v = await settledView(page);
  const box = (await page.locator(".maplibregl-map").boundingBox())!;
  const world = 512 * 2 ** v.zoom;
  const mx = (x: number) => ((x + 180) / 360) * world;
  const my = (y: number) => ((1 - Math.log(Math.tan(Math.PI / 4 + (y * Math.PI) / 360)) / Math.PI) / 2) * world;
  const px = box.width / 2 + mx(lon) - mx(v.lon);
  const py = box.height / 2 + my(lat) - my(v.lat);
  const inside = px > 60 && px < box.width - 60 && py > 60 && py < box.height - 60;
  return inside ? { x: box.x + px, y: box.y + py } : null;
}

/** Tap the map at lon/lat; returns the point the app received, or null when the tap hit a marker or shelter. */
async function tapAt(page: Page, lon: number, lat: number): Promise<[number, number] | null> {
  const map = page.locator(".maplibregl-map");
  const before = await map.getAttribute("data-tap");
  const p = await pixelOf(page, lon, lat);
  if (!p) return null;
  await page.mouse.click(p.x, p.y);
  let now: string | null = null;
  try {
    await expect
      .poll(async () => ((now = await map.getAttribute("data-tap")) !== null && now !== before), { timeout: 2000 })
      .toBe(true);
  } catch {
    return null;
  }
  const got = now!.split(",").map(Number) as [number, number];
  // the click landed where it was aimed (within ~2 px at this zoom)
  const v = await settledView(page);
  const degPerPx = 360 / (512 * 2 ** v.zoom);
  expect(Math.abs(got[0] - lon)).toBeLessThan(3 * degPerPx);
  expect(Math.abs(got[1] - lat)).toBeLessThan(3 * degPerPx);
  return got;
}

async function expectRouteCard(page: Page, area: Area, r: Expect, start: string) {
  const c = card(page, safeCardTitle(area));
  if (r.ok && r.shelter.kind === "relocation") {
    await expect(c).toContainText(`Relocate to high ground: ${r.shelter.name}`, IT);
    await expect(c).toContainText(`About ${r.minutes} min on foot`, IT);
    await expect(c).toContainText("Computed in your browser on the mapped roads and paths for this scenario", IT);
  } else if (r.ok) {
    await expect(c).toContainText(`Go to: ${r.shelter.name}`, IT);
    await expect(c).toContainText(`About ${r.minutes} min on foot · ${LABEL[r.shelter.type] ?? r.shelter.type}`, IT);
    await expect(c).toContainText("Computed in your browser on the mapped roads and paths for this scenario", IT);
    await expect(c).not.toContainText("No safe route on foot");
  } else if (r.reason === "no_relocation") {
    await expect(c).toContainText(`Routing from any point in ${area.name} is not ready yet: it needs the ranked relocation sites`, IT);
    await expect(c).not.toContainText("No safe route on foot");
    await expect(c).not.toContainText("Computed in your browser");
    await expect(page.locator(".maplibregl-map")).not.toHaveAttribute("data-route-points", /^[1-9]/);
  } else if (r.reason === "far") {
    await expect(c).toContainText("more than 500 m from any mapped road or path", IT);
  } else {
    await expect(c).toContainText("No safe route on foot.", IT);
    await expect(c.getByRole("link", { name: "1199" })).toHaveAttribute("href", "tel:1199");
    const why = r.reason === "wet" ? "inside the flood extent" : r.reason === "cut_off" ? "nearest path to this point is flooded" : "No safe place can be reached";
    await expect(c).toContainText(why, IT);
  }
  await expect(page.locator("select#origin")).toHaveValue("tap");
  await expect(page.locator("select#origin option:checked")).toHaveText(start);
}

for (const area of areas()) {
  test(`${area.id}: tap a dry point -> the client's route (Nyando: the not-ready note until relocation targets), weather; a new scenario re-routes`, async ({ page, baseURL }) => {
    const errors = await watch(page, baseURL!);
    const asked = await mockOpenMeteo(page);
    await openScenario(page, area, 50, "normal");
    // dry, routable oracle taps in this scenario; the first one the map takes (a shelter or marker may sit on a pixel)
    const dryOk = (lon: number, lat: number) => {
      const e = expected(area.id, 50, "normal", lon, lat);
      return e.ok || e.reason === "no_relocation";
    };
    const cands = ORACLE.filter((o) => o.area === area.id && o.key === "50_normal" && o.tap.startsWith("r") && !o.error).filter((o) => dryOk(o.lon, o.lat));
    expect(cands.length).toBeGreaterThan(2);
    let got: [number, number] | null = null;
    for (const o of cands) if ((got = await tapAt(page, o.lon, o.lat))) break;
    expect(got, "no candidate tap reached the map").not.toBeNull();
    const [lon, lat] = got!;
    const r = expected(area.id, 50, "normal", lon, lat);
    expect(dryOk(lon, lat), "the tap actually received is dry and near a path too").toBe(true);
    if (!RURAL.has(area.id)) expect(r.ok, "an urban dry tap routes").toBe(true);
    await expectRouteCard(page, area, r, "Tapped point");
    await expect(page.locator(".tap-marker")).toHaveCount(1);
    await expect(page.locator(".origin-marker.active:not(.tap-marker)")).toHaveCount(0);
    // weather: here = the tapped point; going = the destination (M-13), only when there is one
    const w = card(page, "My weather");
    await expect(w.locator('[data-weather-point="Where you are"]')).toContainText("Where you are: Tapped point", IT);
    if (r.ok) {
      await expect(w.locator('[data-weather-point="Where you are going"]')).toContainText(`Where you are going: ${r.shelter.name}`, IT);
      await expect.poll(() => asked).toContainEqual(`${r.shelter.lon.toFixed(4)},${r.shelter.lat.toFixed(4)}`);
    } else await expect(w.locator('[data-weather-point="Where you are going"]')).toHaveCount(0);
    await expect.poll(() => asked).toContainEqual(`${lon.toFixed(4)},${lat.toFixed(4)}`);

    // the same point under the heaviest scenario: recomputed for it (a route, or the stated refusal)
    await page.getByLabel("Rainfall in mm per 24 hours").fill("4");
    await page.getByRole("checkbox", { name: /El Niño season/ }).click();
    await expect(page.getByText("Scenario: 250 mm in 24 h + El Niño. Not a forecast.")).toBeVisible();
    await expectRouteCard(page, area, expected(area.id, 250, "elnino", lon, lat), "Tapped point");

    // a preset still shows its published route and clears the tapped point
    const routes = readJson<{ origin_id: string; destination_name: string }[]>(`${area.id}/scenarios/250_elnino.routes.json`);
    await page.locator("select#origin").selectOption(routes[0].origin_id);
    await expect(page.locator(".tap-marker")).toHaveCount(0);
    await expect(card(page, safeCardTitle(area))).toContainText(routes[0].destination_name);
    await expect(card(page, safeCardTitle(area))).not.toContainText("Computed in your browser");
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test(`${area.id}: tap a wet point -> no route, the 1199 message`, async ({ page, baseURL }) => {
    const errors = await watch(page, baseURL!);
    await mockOpenMeteo(page);
    await openScenario(page, area, 250, "elnino");
    const flood = readJson<FloodCollection>(`${area.id}/scenarios/250_elnino.geojson`);
    // interior points of flood polygons that stay wet 3 px around (a click lands within a pixel or two)
    const v = await settledView(page);
    const d = (3 * 360) / (512 * 2 ** v.zoom);
    const wetAround = (lon: number, lat: number) =>
      [[0, 0], [d, 0], [-d, 0], [0, d], [0, -d]].every(([dx, dy]) => riskAt(flood, lon + dx, lat + dy));
    const wet: [number, number][] = [];
    // every polygon of every feature (each risk class is one MultiPolygon), largest rings first
    const rings = flood.features
      .flatMap((f) => (f.geometry.type === "Polygon" ? [f.geometry.coordinates[0]] : f.geometry.coordinates.map((q) => q[0])))
      .sort((a, b) => b.length - a.length);
    for (const ring of rings) {
      const lon = ring.reduce((a, p) => a + p[0], 0) / ring.length;
      const lat = ring.reduce((a, p) => a + p[1], 0) / ring.length;
      if (wetAround(lon, lat)) wet.push([lon, lat]);
      if (wet.length >= 40) break;
    }
    expect(wet.length).toBeGreaterThan(0);
    let got: [number, number] | null = null;
    for (const [lon, lat] of wet) {
      got = await tapAt(page, lon, lat);
      if (got && riskAt(flood, got[0], got[1])) break; // the point the app received is wet too
      got = null;
    }
    expect(got, "no wet tap reached the map").not.toBeNull();
    await expectRouteCard(page, area, { ok: false, reason: "wet" }, "Tapped point");
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test(`${area.id}: "Use my location" at a preset origin -> the client's outcome there (urban: the published route)`, async ({ page, baseURL, context }) => {
    const errors = await watch(page, baseURL!);
    await mockOpenMeteo(page);
    const routes = readJson<{ origin_id: string; kind: string; shelter_id: string; destination_name: string; safe: { minutes: number } }[]>(
      `${area.id}/scenarios/100_normal.routes.json`,
    );
    const row = routes.find((x) => x.kind === "to_shelter")!;
    const o = readJson<{ id: string; lon: number; lat: number }[]>(`${area.id}/origins.json`).find((x) => x.id === row.origin_id)!;
    await context.grantPermissions(["geolocation"]);
    await context.setGeolocation({ longitude: o.lon, latitude: o.lat });
    await openScenario(page, area, 100, "normal");
    await page.getByRole("button", { name: "Use my location" }).click();
    const r = expected(area.id, 100, "normal", o.lon, o.lat);
    await expectRouteCard(page, area, r, "My location");
    if (!RURAL.has(area.id)) {
      // urban: the same route the pipeline published for this preset
      const c = card(page, safeCardTitle(area));
      await expect(c).toContainText(`Go to: ${row.destination_name}`, IT);
      await expect(c).toContainText(`About ${row.safe.minutes} min on foot`, IT);
    }
    await expect(page.locator(".maplibregl-map")).toHaveAttribute("data-tap", `${o.lon},${o.lat}`);
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test(`${area.id}: "Use my location" denied, or outside the area -> a clear note, no route`, async ({ page, baseURL, context }) => {
    const errors = await watch(page, baseURL!);
    await mockOpenMeteo(page);
    await openScenario(page, area, 100, "normal");
    const c = card(page, safeCardTitle(area));
    await page.getByRole("button", { name: "Use my location" }).click(); // no permission granted
    await expect(c).toContainText("Location permission denied. Tap the map to choose a starting point instead.");
    await expect(page.locator(".tap-marker")).toHaveCount(0);
    await context.grantPermissions(["geolocation"]);
    await context.setGeolocation({ longitude: 32.58, latitude: 0.35 }); // Kampala: outside both areas
    await page.getByRole("button", { name: "Use my location" }).click();
    await expect(c).toContainText(`Your location (0.3500, 32.5800) is outside ${area.name}. Tap the map instead.`);
    await expect(page.locator(".tap-marker")).toHaveCount(0);
    expect(errors, errors.join("\n")).toEqual([]);
  });
}

// CONSTRAINT (human's order, tasks/model.md): no shelter feature is removed or hidden. The shelters layer (with Nyando's
// high_ground relocation sites), its popups and the published nearest-shelter routes stay; a tap routes to the nearest
// safe shelter by default. Tiles are served as a 1x1 PNG so the map reaches "idle" and reports what it holds.
const PNG_1X1 = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "base64");
for (const area of areas()) {
  test(`${area.id}: shelters, relocation sites, shelter popups and the nearest-shelter route all stay with tap routing`, async ({ page, baseURL }) => {
    const errors = await watch(page, baseURL!);
    await mockOpenMeteo(page);
    await page.route(
      (u) => u.host.endsWith("tile.openstreetmap.org"),
      (r) => r.fulfill({ status: 200, contentType: "image/png", headers: { "access-control-allow-origin": "*" }, body: PNG_1X1 }),
    );
    const rain = 150;
    const shelters = readJson<{ id: string; name: string; type: string; lon: number; lat: number }[]>(`${area.id}/scenarios/${rain}_normal.shelters.json`);
    const routes = readJson<{ origin_id: string; kind: string; safe: { geometry: { coordinates: number[][] } } }[]>(
      `${area.id}/scenarios/${rain}_normal.routes.json`,
    );
    const highGround = shelters.filter((s) => s.type === "high_ground").length;
    if (area.type === "rural") expect(highGround, "Nyando's relocation sites are in shelters.json").toBeGreaterThan(0);
    await openScenario(page, area, rain, "normal");
    const map = page.locator(".maplibregl-map");
    const holdsAllShelters = async () => {
      await expect(map).toHaveAttribute("data-shelters", String(shelters.length));
      await expect(map).toHaveAttribute("data-high-ground", String(highGround));
      await expect(map).toHaveAttribute("data-overlays", /(^|,)shelters(,|$)/);
    };
    await holdsAllShelters();

    // a preset: its published route draws (relocation for Nyando's settler, a shelter route otherwise)
    for (const kind of area.type === "rural" ? ["relocation", "to_shelter"] : ["to_shelter"]) {
      const row = routes.find((r) => r.kind === kind)!;
      await page.locator("select#origin").selectOption(row.origin_id);
      await expect(map).toHaveAttribute("data-route-points", String(row.safe.geometry.coordinates.length));
      await holdsAllShelters();
    }

    // a tap: the nearest safe place is the default destination, and its route draws. Rural (Nyando) until graph.json
    // carries relocation targets: the not-ready note and NO route (never to OSM shelters alone), shelters still drawn.
    const usable = (lon: number, lat: number) => {
      const e = expected(area.id, rain, "normal", lon, lat);
      return e.ok || e.reason === "no_relocation";
    };
    const cands = ORACLE.filter((o) => o.area === area.id && o.key === `${rain}_normal` && o.tap.startsWith("r") && !o.error);
    let got: [number, number] | null = null;
    for (const o of cands) if (usable(o.lon, o.lat) && (got = await tapAt(page, o.lon, o.lat))) break;
    expect(got).not.toBeNull();
    const r = expected(area.id, rain, "normal", got![0], got![1]);
    if (!RURAL.has(area.id)) expect(r.ok).toBe(true);
    await expectRouteCard(page, area, r, "Tapped point");
    await expect(map).toHaveAttribute("data-route-points", String(r.ok ? r.coords.length : 0));
    await holdsAllShelters();

    // shelter popups still answer, and a tap on a shelter is a query, not a new start point
    const before = await map.getAttribute("data-tap");
    let popped = false;
    for (const s of shelters) {
      const p = await pixelOf(page, s.lon, s.lat);
      if (!p) continue;
      await page.mouse.click(p.x, p.y);
      const pop = page.locator(".maplibregl-popup");
      if (await pop.filter({ hasText: s.name }).count()) {
        popped = true;
        break;
      }
      await page.keyboard.press("Escape");
    }
    expect(popped, "a shelter popup opened").toBe(true);
    await expect(map).toHaveAttribute("data-tap", before!);
    expect(errors, errors.join("\n")).toEqual([]);
  });
}
