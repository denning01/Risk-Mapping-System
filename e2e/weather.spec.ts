// M-13 · "My weather" panel, with Open-Meteo mocked (page.route). Expected values come from the fixture and from
// web/public/data (origins, routes, shelters), never from the app.
import { expect, test, type Page } from "@playwright/test";
import { areas, card, expectExposure, openScenario, readJson, watch, type Origin, type Route } from "./helpers";
import { DAILY_MM, DAILY_PROB, fixture } from "./weather-fixture";

const IT = { useInnerText: true };
/** The caption for the model cell the fixture returns (lat/lon rounded to 2 dp), as weather.tsx prints it (3 dp). */
const cellCaption = (p: { lon: number; lat: number }) =>
  `for the model cell at ${(Math.round(p.lat * 100) / 100).toFixed(3)}, ${(Math.round(p.lon * 100) / 100).toFixed(3)}.`;
type Shelter = { id: string; lon: number; lat: number };
type OriginLL = Origin & { lon: number; lat: number };

/** Mock Open-Meteo; record every requested (lon, lat). Registered after watch(), so it wins over watch's abort. */
async function mockOpenMeteo(page: Page, mode: "ok" | "fail") {
  const asked: { lon: string; lat: string }[] = [];
  await page.route("https://api.open-meteo.com/**", (r) => {
    const u = new URL(r.request().url());
    asked.push({ lon: u.searchParams.get("longitude")!, lat: u.searchParams.get("latitude")! });
    if (mode === "fail") return r.abort("internetdisconnected");
    return r.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify(fixture(Number(u.searchParams.get("longitude")), Number(u.searchParams.get("latitude")))),
    });
  });
  return asked;
}

for (const area of areas()) {
  const rain = 50;
  const origins = readJson<OriginLL[]>(`${area.id}/origins.json`);
  const routes = readJson<(Route & { shelter_id: string | null })[]>(`${area.id}/scenarios/${rain}_normal.routes.json`);
  const shelters = readJson<Shelter[]>(`${area.id}/scenarios/${rain}_normal.shelters.json`);
  const route = routes.find((r) => r.shelter_id !== null) ?? routes[0];
  const o = origins.find((x) => x.id === route.origin_id)!;
  const sh = shelters.find((s) => s.id === route.shelter_id);
  const end = route.safe.geometry.coordinates.at(-1)!;
  const dest = sh ? { lon: sh.lon, lat: sh.lat } : { lon: end[0], lat: end[1] };

  test(`${area.id}: My weather shows Open-Meteo's forecast at the start point and the destination`, async ({ page, baseURL }) => {
    const errors = await watch(page, baseURL!);
    const asked = await mockOpenMeteo(page, "ok");
    await openScenario(page, area, rain, "normal");
    const w = card(page, "My weather");
    await expect(w).toContainText("Choose a starting point to see the live rain forecast there.");
    await page.locator("select#origin").selectOption(o.id);

    const here = w.locator('[data-weather-point="Where you are"]');
    await expect(here).toContainText(`Where you are: ${o.name}`, IT);
    await expect(here).toContainText("Rain expected today: 2.2 mm (chance of rain up to 85%).", IT);
    await expect(here.getByRole("listitem")).toHaveCount(24);
    await expect(here.getByRole("listitem").nth(15)).toHaveAttribute("aria-label", "15:00 1.2 mm, 85%");
    const rows = here.getByRole("table", { name: "Next 7 days" }).locator("tbody tr");
    await expect(rows).toHaveCount(7);
    for (let i = 0; i < 7; i++) await expect(rows.nth(i)).toContainText(`${DAILY_MM[i]} mm${DAILY_PROB[i]}%`);
    await expect(rows.nth(4)).toContainText("Thu 12 Nov");
    await expect(here).toContainText(/Open-Meteo forecast, fetched \d\d:\d\d EAT, for the model cell at /);
    // F13.2: the exact cell, lat first (requested at 4 dp, so round the 4-dp value the app sent)
    await expect(here).toContainText(cellCaption({ lon: Number(o.lon.toFixed(4)), lat: Number(o.lat.toFixed(4)) }));

    const going = w.locator('[data-weather-point="Where you are going"]');
    await expect(going).toContainText(`Where you are going: ${route.destination_name}`, IT);
    await expect(going).toContainText("Rain expected today: 2.2 mm", IT);
    await expect(going).toContainText("Wettest of the next 7 days: Thu 12 Nov, 12.4 mm.", IT);
    await expect(going).toContainText(cellCaption({ lon: Number(dest.lon.toFixed(4)), lat: Number(dest.lat.toFixed(4)) }));

    await expect(w).toContainText("Not our forecast: live data from Open-Meteo.");
    await expect(w.getByRole("link", { name: "Weather data by Open-Meteo.com" })).toHaveAttribute("href", "https://open-meteo.com/en/licence");
    // the requests went to the start point and to the destination, at 4 decimals
    expect(asked).toContainEqual({ lon: o.lon.toFixed(4), lat: o.lat.toFixed(4) });
    expect(asked).toContainEqual({ lon: dest.lon.toFixed(4), lat: dest.lat.toFixed(4) });
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test(`${area.id}: a failed Open-Meteo fetch shows a clear message and the app still works`, async ({ page, baseURL }) => {
    const errors = await watch(page, baseURL!);
    const asked = await mockOpenMeteo(page, "fail");
    await openScenario(page, area, rain, "normal");
    await page.locator("select#origin").selectOption(o.id);
    const w = card(page, "My weather");
    await expect(w.locator('[data-weather-point="Where you are"]')).toContainText(
      "Live weather unavailable (offline, or Open-Meteo did not answer). The flood scenarios and routes still work.",
    );
    await expect(w.locator('[data-weather-point="Where you are going"]')).toContainText("Live weather unavailable");
    expect(asked.length).toBeGreaterThanOrEqual(2);
    // the rest of the app is unaffected: the exposure counter matches the file, and the route card is shown
    await expectExposure(page, `${area.id}/scenarios/${rain}_normal.exposure.json`);
    await expect(page.getByText(route.destination_name).first()).toBeVisible();
    expect(errors, errors.join("\n")).toEqual([]);
  });
}
