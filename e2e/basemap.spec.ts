// M-15 · Normal / Terrain / Satellite switcher. Tile hosts are mocked (a 1x1 PNG), so the tests need no network and
// check our behaviour, not the providers'. The canvas is opaque to the DOM, so FloodMap exposes what is drawn on the
// map container: data-style / data-basemap = the style that actually LOADED (identified from its sources, not the
// switcher's choice), data-overlays, data-flood-features (read back from the flood source on map idle).
//
// F14.2: production has a WORKING OpenFreeMap vector style. Most tests here serve a minimal vector style in its place
// (its real source attribution, fetched from tiles.openfreemap.org/planet on 2026-11-08), so the startup fallback is
// NOT already used up, as it is in every suite that blocks OpenFreeMap.
import { expect, test, type Page } from "@playwright/test";
import { areas, openScenario, readJson, watch, type Route } from "./helpers";

const PNG_1X1 = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "base64");
const TILE_HOSTS = ["tile.openstreetmap.org", "tile.opentopomap.org", "tiles.maps.eox.at"];
const OFM_ATTRIBUTION =
  '<a href="https://openfreemap.org" target="_blank">OpenFreeMap</a> <a href="https://www.openmaptiles.org/" target="_blank">&copy; OpenMapTiles</a> Data from <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>';
const VECTOR_STYLE = {
  version: 8,
  sources: { openmaptiles: { type: "vector", tiles: ["https://tiles.openfreemap.org/planet/x/{z}/{x}/{y}.pbf"], attribution: OFM_ATTRIBUTION } },
  // a layer on the vector source, so the source loads and its credit shows (MapLibre credits only used sources);
  // its tiles are served empty (a valid, empty vector tile)
  layers: [
    { id: "background", type: "background", paint: { "background-color": "#eef" } },
    { id: "water", type: "fill", source: "openmaptiles", "source-layer": "water", paint: { "fill-color": "#9cf" } },
  ],
};

/** The full credit text each basemap must show (F14.3), as rendered in the attribution control. */
const CREDIT = {
  vector: "OpenFreeMap © OpenMapTiles Data from OpenStreetMap",
  "osm-raster": "© OpenStreetMap contributors",
  opentopomap: "Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)",
  "eox-s2cloudless":
    "EOxCloudless https://cloudless.eox.at by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2025), CC BY-NC-SA 4.0",
} as const;
type StyleId = keyof typeof CREDIT;
const BASEMAP_OF: Record<StyleId, string> = { vector: "normal", "osm-raster": "normal", opentopomap: "terrain", "eox-s2cloudless": "satellite" };
const HOST_OF: Record<string, string> = { terrain: "tile.opentopomap.org", satellite: "tiles.maps.eox.at" };
const LABEL: Record<string, string> = { normal: "Normal", terrain: "Terrain", satellite: "Satellite" };

/**
 * vector: serve the minimal OpenFreeMap style (else OpenFreeMap stays blocked by watch() -> startup raster fallback).
 * fail: a tile host whose tiles fail: "one" = only the first request, "all" = every request.
 */
async function mockMap(page: Page, opts: { vector: boolean; fail?: { host: string; mode: "one" | "all" } }) {
  const asked: string[] = [];
  let failed = 0;
  if (opts.vector) {
    await page.route("https://tiles.openfreemap.org/planet/x/**", (r) =>
      r.fulfill({ status: 200, contentType: "application/x-protobuf", headers: { "access-control-allow-origin": "*" }, body: Buffer.alloc(0) }),
    );
    await page.route("https://tiles.openfreemap.org/styles/liberty", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(VECTOR_STYLE) }),
    );
  }
  await page.route(
    (u) => TILE_HOSTS.some((h) => u.host === h || u.host.endsWith(`.${h}`)),
    (r) => {
      const host = new URL(r.request().url()).host;
      asked.push(host);
      const f = opts.fail;
      if (f && host.endsWith(f.host) && (f.mode === "all" || failed++ === 0)) return r.abort("connectionrefused");
      return r.fulfill({ status: 200, contentType: "image/png", headers: { "access-control-allow-origin": "*" }, body: PNG_1X1 });
    },
  );
  return asked;
}

const OVERLAYS = "flood-fill,route-safe,shelters";

for (const area of areas()) {
  const rain = 150;
  const flood = readJson<{ features: unknown[] }>(`${area.id}/scenarios/${rain}_normal.geojson`);
  const routes = readJson<Route[]>(`${area.id}/scenarios/${rain}_normal.routes.json`);
  const origins = readJson<{ id: string }[]>(`${area.id}/origins.json`);
  const route = routes[0];

  /** The switcher, the loaded style, the credit, the overlays, markers and scenario all agree. */
  const expectDrawn = async (page: Page, style: StyleId) => {
    const basemap = BASEMAP_OF[style];
    const map = page.locator("[data-basemap]");
    await expect(page.getByRole("radiogroup", { name: "Basemap" }).getByRole("radio", { name: LABEL[basemap] })).toHaveAttribute("aria-checked", "true");
    await expect(map).toHaveAttribute("data-style", style);
    await expect(map).toHaveAttribute("data-basemap", basemap);
    await expect(page.locator(".maplibregl-ctrl-attrib-inner")).toHaveText(CREDIT[style]);
    await expect(map).toHaveAttribute("data-overlays", OVERLAYS);
    await expect(map).toHaveAttribute("data-flood-features", String(flood.features.length));
    await expect(page.locator(".origin-marker")).toHaveCount(origins.length);
    await expect(page.getByText(`Scenario: ${rain} mm in 24 h. Not a forecast.`)).toBeVisible();
  };
  const choose = (page: Page, b: string) => page.getByRole("radiogroup", { name: "Basemap" }).getByRole("radio", { name: LABEL[b] }).click();

  test(`${area.id}: with a working vector Normal, Normal -> Terrain -> Satellite -> Normal keeps everything drawn`, async ({ page, baseURL }) => {
    const errors = await watch(page, baseURL!);
    const asked = await mockMap(page, { vector: true });
    await openScenario(page, area, rain, "normal");
    await page.locator("select#origin").selectOption(route.origin_id);
    await expect(page.locator(".origin-marker.active")).toHaveCount(1);
    await expectDrawn(page, "vector");
    for (const [b, style] of [["terrain", "opentopomap"], ["satellite", "eox-s2cloudless"], ["normal", "vector"]] as const) {
      await choose(page, b);
      await expectDrawn(page, style);
      await expect(page.locator(".origin-marker.active")).toHaveCount(1);
      await expect(page.getByText(route.destination_name).first()).toBeVisible();
    }
    await expect(page.getByText(/tiles unavailable|Using fallback basemap/)).toHaveCount(0);
    expect(asked.some((h) => h.endsWith("tile.opentopomap.org"))).toBe(true);
    expect(asked).toContain("tiles.maps.eox.at");
    expect(errors, errors.join("\n")).toEqual([]);
  });

  for (const b of ["terrain", "satellite"] as const) {
    const style: StyleId = b === "terrain" ? "opentopomap" : "eox-s2cloudless";

    test(`${area.id}: one bad ${b} tile is not a failure (vector Normal working)`, async ({ page, baseURL }) => {
      const errors = await watch(page, baseURL!);
      const asked = await mockMap(page, { vector: true, fail: { host: HOST_OF[b], mode: "one" } });
      await openScenario(page, area, rain, "normal");
      await expectDrawn(page, "vector");
      await choose(page, b);
      await expectDrawn(page, style);
      await expect.poll(() => asked.filter((h) => h.endsWith(HOST_OF[b])).length).toBeGreaterThan(3); // the failure has happened
      await page.waitForTimeout(1000);
      await expectDrawn(page, style); // still the chosen basemap, no fallback
      await expect(page.getByText(/tiles unavailable|Using fallback basemap/)).toHaveCount(0);
      expect(errors, errors.join("\n")).toEqual([]);
    });

    test(`${area.id}: all ${b} tiles failing -> the vector Normal with a note (vector Normal working)`, async ({ page, baseURL }) => {
      const errors = await watch(page, baseURL!);
      await mockMap(page, { vector: true, fail: { host: HOST_OF[b], mode: "all" } });
      await openScenario(page, area, rain, "normal");
      await expectDrawn(page, "vector");
      await choose(page, b);
      await expect(page.getByText(`${LABEL[b]} tiles unavailable: showing the Normal map`)).toBeVisible();
      await expectDrawn(page, "vector"); // the VECTOR Normal, not the startup raster fallback
      await expect(page.getByText("Using fallback basemap")).toHaveCount(0);
      expect(errors, errors.join("\n")).toEqual([]);
    });
  }

  test(`${area.id}: OpenFreeMap down at startup -> raster Normal with its note; switching still works`, async ({ page, baseURL }) => {
    const errors = await watch(page, baseURL!);
    await mockMap(page, { vector: false });
    await openScenario(page, area, rain, "normal");
    await expectDrawn(page, "osm-raster");
    await expect(page.getByText("Using fallback basemap")).toBeVisible();
    await choose(page, "satellite");
    await expectDrawn(page, "eox-s2cloudless");
    await choose(page, "normal");
    await expectDrawn(page, "osm-raster"); // back to the raster: the vector style already failed this session
    expect(errors, errors.join("\n")).toEqual([]);
  });
}
