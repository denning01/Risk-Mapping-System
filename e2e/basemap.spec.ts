// M-15 · Normal / Terrain / Satellite switcher. Tile hosts are mocked (a 1x1 PNG), so the test needs no network and
// checks our behaviour, not the providers'. The map canvas is opaque to the DOM, so FloodMap exposes what it has drawn
// as data-basemap / data-overlays / data-flood-features on the map container; expected values come from the files.
import { expect, test, type Page } from "@playwright/test";
import { areas, openScenario, readJson, watch, type Route } from "./helpers";

const PNG_1X1 = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "base64");
const TILE_HOSTS = ["tile.openstreetmap.org", "tile.opentopomap.org", "tiles.maps.eox.at"];

/** Serve tiles for the raster hosts (OpenFreeMap stays blocked by watch(), so Normal is the raster fallback here). */
async function mockTiles(page: Page, failHost?: string) {
  const asked: string[] = [];
  await page.route(
    (u) => TILE_HOSTS.some((h) => u.host === h || u.host.endsWith(`.${h}`)),
    (r) => {
      const u = new URL(r.request().url());
      asked.push(u.host);
      if (failHost && u.host.endsWith(failHost)) return r.abort("connectionrefused");
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

  test(`${area.id}: Normal -> Terrain -> Satellite -> Normal keeps the flood, route, shelters, markers and scenario`, async ({ page, baseURL }) => {
    const errors = await watch(page, baseURL!);
    const asked = await mockTiles(page);
    await openScenario(page, area, rain, "normal");
    await page.locator("select#origin").selectOption(route.origin_id);
    const map = page.locator("[data-basemap]");
    const drawnAs = async (b: string) => {
      await expect(map).toHaveAttribute("data-basemap", b);
      await expect(map).toHaveAttribute("data-overlays", OVERLAYS);
      await expect(map).toHaveAttribute("data-flood-features", String(flood.features.length));
      await expect(page.locator(".origin-marker")).toHaveCount(origins.length);
      await expect(page.locator(".origin-marker.active")).toHaveCount(1);
      await expect(page.getByText(`Scenario: ${rain} mm in 24 h. Not a forecast.`)).toBeVisible();
      await expect(page.getByText(route.destination_name).first()).toBeVisible();
    };
    await drawnAs("normal");
    const group = page.getByRole("radiogroup", { name: "Basemap" });
    for (const [label, b] of [["Terrain", "terrain"], ["Satellite", "satellite"], ["Normal", "normal"]] as const) {
      await group.getByRole("radio", { name: label }).click();
      await expect(group.getByRole("radio", { name: label })).toHaveAttribute("aria-checked", "true");
      await drawnAs(b);
      if (b === "terrain") await expect(page.locator(".maplibregl-ctrl-attrib")).toContainText("OpenTopoMap (CC-BY-SA)");
      if (b === "satellite") {
        await expect(page.locator(".maplibregl-ctrl-attrib")).toContainText(
          "EOxCloudless https://cloudless.eox.at by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2025)",
        );
        await expect(page.locator(".maplibregl-ctrl-attrib")).toContainText("CC BY-NC-SA 4.0");
      }
    }
    expect(asked.some((h) => h.endsWith("tile.opentopomap.org"))).toBe(true);
    expect(asked).toContain("tiles.maps.eox.at");
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test(`${area.id}: Satellite tiles failing fall back to Normal with a note, overlays kept`, async ({ page, baseURL }) => {
    const errors = await watch(page, baseURL!);
    await mockTiles(page, "tiles.maps.eox.at");
    await openScenario(page, area, rain, "normal");
    const map = page.locator("[data-basemap]");
    await expect(map).toHaveAttribute("data-basemap", "normal");
    await page.getByRole("radiogroup", { name: "Basemap" }).getByRole("radio", { name: "Satellite" }).click();
    await expect(page.getByText("Satellite tiles unavailable: showing the Normal map")).toBeVisible();
    await expect(page.getByRole("radiogroup", { name: "Basemap" }).getByRole("radio", { name: "Normal" })).toHaveAttribute("aria-checked", "true");
    await expect(map).toHaveAttribute("data-basemap", "normal");
    await expect(map).toHaveAttribute("data-overlays", OVERLAYS);
    await expect(map).toHaveAttribute("data-flood-features", String(flood.features.length));
    expect(errors, errors.join("\n")).toEqual([]);
  });
}
