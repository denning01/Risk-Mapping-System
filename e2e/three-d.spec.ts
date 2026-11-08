// M-17 · 3D view toggle. Every external host is mocked: a minimal OpenFreeMap vector style (no building layer, so the
// app adds its own building extrusions), empty vector tiles, 1x1 raster tiles, and the terrain DEM served as a FLAT
// terrarium tile at 1600 m (fixtures/make_terrarium.py) so the decode can be checked: the map reports 1600 m at its
// centre with the x1.5 exaggeration divided out. FloodMap exposes data-3d / data-terrain / data-elevation / data-pitch /
// data-layers-3d, read back from the map on "idle".
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { THREE_D_NOTE, TERRAIN_X, WATER_X } from "../web/src/lib/threeD";
import { areas, openScenario, readJson, watch } from "./helpers";

const PNG_1X1 = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "base64");
const DEM_1600 = readFileSync(join(__dirname, "fixtures", "terrarium-1600.png"));
const CORS = { "access-control-allow-origin": "*" };
const VECTOR_STYLE = {
  version: 8,
  sources: { openmaptiles: { type: "vector", tiles: ["https://tiles.openfreemap.org/planet/x/{z}/{x}/{y}.pbf"] } },
  layers: [
    { id: "background", type: "background", paint: { "background-color": "#eef" } },
    { id: "water", type: "fill", source: "openmaptiles", "source-layer": "water", paint: { "fill-color": "#9cf" } },
  ],
};

async function mockHosts(page: Page) {
  const dem: string[] = [];
  await page.route("https://tiles.openfreemap.org/styles/liberty", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify(VECTOR_STYLE) }),
  );
  await page.route("https://tiles.openfreemap.org/planet", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      headers: CORS,
      body: JSON.stringify({ tilejson: "3.0.0", tiles: ["https://tiles.openfreemap.org/planet/x/{z}/{x}/{y}.pbf"], minzoom: 0, maxzoom: 14 }),
    }),
  );
  await page.route("https://tiles.openfreemap.org/planet/x/**", (r) =>
    r.fulfill({ status: 200, contentType: "application/x-protobuf", headers: CORS, body: Buffer.alloc(0) }),
  );
  await page.route(
    (u) => ["tile.openstreetmap.org", "tile.opentopomap.org", "tiles.maps.eox.at"].some((h) => u.host === h || u.host.endsWith(`.${h}`)),
    (r) => r.fulfill({ status: 200, contentType: "image/png", headers: CORS, body: PNG_1X1 }),
  );
  await page.route("https://elevation-tiles-prod.s3.amazonaws.com/terrarium/**", (r) => {
    dem.push(r.request().url());
    return r.fulfill({ status: 200, contentType: "image/png", headers: CORS, body: DEM_1600 });
  });
  return dem;
}

const LABEL = { normal: "Normal", terrain: "Terrain", satellite: "Satellite" } as const;
const STYLE = { normal: "vector", terrain: "opentopomap", satellite: "eox-s2cloudless" } as const;

for (const area of areas()) {
  test(`${area.id}: 3D on -> terrain (heights stated), water by depth, buildings; kept across basemaps; off -> flat 2D`, async ({ page, baseURL }) => {
    // headless Chromium draws WebGL on the CPU (SwiftShader): terrain + extrusions take tens of seconds to reach idle
    // there. On the laptop GPU (headed Chrome, Apple M1 Max) the first 3D idle took 5.9-6.6 s (ROUND 20).
    test.setTimeout(480_000);
    const SLOW = { timeout: 120_000 };
    const errors = await watch(page, baseURL!);
    await page.route("https://api.open-meteo.com/**", (r) => r.fulfill({ status: 503, body: "" }));
    const dem = await mockHosts(page);
    const flood = readJson<{ features: unknown[] }>(`${area.id}/scenarios/250_elnino.geojson`);
    await openScenario(page, area, 250, "elnino");
    const map = page.locator("[data-basemap]");
    const btn = page.getByRole("button", { name: "3D", exact: true });

    // 2D is the default
    await expect(map).toHaveAttribute("data-style", "vector");
    await expect(map).toHaveAttribute("data-3d", "off");
    await expect(map).toHaveAttribute("data-terrain", "off");
    await expect(map).toHaveAttribute("data-pitch", "0");
    await expect(btn).toHaveAttribute("aria-pressed", "false");
    await expect(page.locator("[data-3d-note]")).toHaveCount(0);

    await btn.click();
    await expect(btn).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("[data-3d-note]")).toHaveText(THREE_D_NOTE);
    expect(THREE_D_NOTE).toContain(`terrain heights x${TERRAIN_X}`);
    expect(THREE_D_NOTE).toContain(`water depth x${WATER_X}`);

    const expect3D = async (b: keyof typeof LABEL) => {
      await expect(map).toHaveAttribute("data-style", STYLE[b], SLOW);
      await expect(map).toHaveAttribute("data-3d", "on");
      await expect(map).toHaveAttribute("data-terrain", `terrain-dem x${TERRAIN_X}`, SLOW);
      await expect(map).toHaveAttribute("data-pitch", "60", SLOW);
      await expect(map).toHaveAttribute("data-elevation", "1600", SLOW); // the flat 1600 m tile, decoded, exaggeration divided out
      await expect(map).toHaveAttribute("data-layers-3d", "flood-3d,buildings-3d");
      await expect(map).toHaveAttribute("data-overlays", /flood-fill/);
      await expect(map).toHaveAttribute("data-flood-features", String(flood.features.length));
      await expect(page.locator("[data-3d-note]")).toHaveText(THREE_D_NOTE);
      await expect(page.locator(".maplibregl-ctrl-attrib-inner")).toContainText("Terrain Tiles (AWS Open Data): SRTM and GMTED2010");
    };
    await expect3D("normal");
    expect(dem.length, "terrain tiles asked for").toBeGreaterThan(0);
    for (const b of ["terrain", "satellite", "normal"] as const) {
      await page.getByRole("radiogroup", { name: "Basemap" }).getByRole("radio", { name: LABEL[b] }).click();
      await expect3D(b);
    }

    await btn.click();
    await expect(btn).toHaveAttribute("aria-pressed", "false");
    await expect(map).toHaveAttribute("data-3d", "off");
    await expect(map).toHaveAttribute("data-terrain", "off", SLOW);
    await expect(map).toHaveAttribute("data-pitch", "0", SLOW);
    await expect(map).toHaveAttribute("data-layers-3d", "");
    await expect(map).not.toHaveAttribute("data-elevation");
    await expect(page.locator("[data-3d-note]")).toHaveCount(0);
    await expect(map).toHaveAttribute("data-flood-features", String(flood.features.length));
    expect(errors.filter((e) => !e.includes("open-meteo")), errors.join("\n")).toEqual([]);
  });
}
