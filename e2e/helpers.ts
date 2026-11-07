// E-14 helpers. Expected values are ALWAYS read from web/public/data (the files the app serves), never hard-coded.
import { expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

export const DATA = join(__dirname, "..", "web", "public", "data");
export const readJson = <T = any>(rel: string): T => JSON.parse(readFileSync(join(DATA, rel), "utf8")) as T;

export const RAINS = [50, 100, 150, 200, 250] as const; // web/src/lib/schema.ts:9 RAIN_VALUES
export const ENSOS = ["normal", "elnino"] as const;

export type Area = { id: string; name: string; type: "urban" | "rural" };
export type Origin = { id: string; name: string };
export type Route = {
  origin_id: string;
  kind: "commute" | "to_shelter" | "relocation";
  destination_name: string;
  baseline: { minutes: number } | null;
  safe: { minutes: number; geometry: { type: string; coordinates: number[][] } };
};

export const areas = (): Area[] => readJson("areas.json");
export const scenarios = () => areas().flatMap((a) => RAINS.flatMap((rain) => ENSOS.map((enso) => ({ area: a, rain, enso }))));

/**
 * The no-route case (origin in flood, operator ruling (a): no route drawn). Stated, not derived, so a data change that
 * adds or removes one is caught by the "routes.json covers every origin" test instead of silently passing.
 */
export const NO_ROUTE = (areaId: string, rain: number, originId: string) => areaId === "nairobi" && originId === "nbi-o4" && rain >= 150;

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const near = (num: string, label: string) => new RegExp(`(^|\\s)${esc(num)}\\s*${esc(label)}`);
const IT = { useInnerText: true };
const fmt = (n: number) => n.toLocaleString("en-US"); // ui.tsx AnimatedNumber / panels.tsx Range line

/** Console errors and uncaught page errors from OUR origin. External hosts (basemap tiles/fonts) are blocked. */
export async function watch(page: Page, baseURL: string) {
  const errors: string[] = [];
  const own = new URL(baseURL).host;
  await page.route(
    (u) => u.host !== own,
    (r) => r.abort("blockedbyclient"),
  );
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const at = m.location().url;
    // a blocked external request logs "Failed to load resource" with the external URL as its location
    if (at && !at.includes(own)) return;
    errors.push(`console.error: ${m.text()} @ ${at}`);
  });
  return errors;
}

/** Go to the app and set area / rain / El Niño through the UI, then wait for the scenario line to confirm it. */
export async function openScenario(page: Page, area: Area, rain: number, enso: string) {
  await page.goto("/");
  await page.getByRole("tablist", { name: "Area" }).getByRole("tab", { name: area.name }).click();
  await expect(page.getByRole("tablist", { name: "Area" }).getByRole("tab", { name: area.name })).toHaveAttribute("aria-selected", "true");
  await page.getByLabel("Rainfall in mm per 24 hours").fill(String(RAINS.indexOf(rain as (typeof RAINS)[number])));
  const nino = page.getByRole("checkbox", { name: /El Niño season/ });
  if ((enso === "elnino") !== (await nino.isChecked())) await nino.click();
  await expect(page.getByText(`Scenario: ${rain} mm in 24 h${enso === "elnino" ? " + El Niño" : ""}. Not a forecast.`)).toBeVisible();
}

export const card = (page: Page, title: string | RegExp) =>
  page.locator("section").filter({ has: page.getByRole("heading", { name: title, exact: typeof title === "string" }) });

export async function expectExposure(page: Page, rel: string) {
  const e = readJson(rel);
  const c = card(page, "People and buildings at risk");
  // AnimatedNumber tweens for 600 ms; toContainText polls until it settles on the file's value
  // innerText, not textContent: textContent joins block elements with no break ("for 20266,602buildings"), so a
  // number could match across two fields. Each number must start a line or follow whitespace.
  await expect(c).toContainText(near(fmt(e.population.medium), "people"), IT);
  await expect(c).toContainText(`Range ${fmt(e.population.low)} to ${fmt(e.population.high)} (low / high growth), projected for ${e.year}`, IT);
  await expect(c).toContainText(near(fmt(e.buildings), "buildings at risk"), IT);
  await expect(c).toContainText(near(e.flooded_area_km2.toFixed(1), "km² flooded"), IT);
  // the app's schema takes any string (schema.ts:61) and badges anything but "mock" as Model; the contract
  // (DATA_CONTRACT.md:56) allows only "mock" | "model", so the suite holds the file to the contract
  expect(["mock", "model"], `${rel} source`).toContain(e.source);
  await expect(c.getByText(e.source === "mock" ? "Mock" : "Model", { exact: true })).toBeVisible();
  return e;
}

/** The side-panel route card for one origin, per panels.tsx SafePlacesPanel. */
export function routeLines(r: Route): string[] {
  if (r.kind === "commute") {
    const extra = r.baseline ? r.safe.minutes - r.baseline.minutes : 0;
    return extra > 0
      ? [`Commute to ${r.destination_name}`, `Safe route: ${r.safe.minutes} min`, `+${extra} min`, `Usual route: ${r.baseline!.minutes} min (flooded)`]
      : [`Commute to ${r.destination_name}`, `Usual route is clear: ${r.safe.minutes} min.`];
  }
  return [`${r.kind === "relocation" ? "Relocate to high ground: " : "Go to: "}${r.destination_name}`, `About ${r.safe.minutes} min on foot`];
}

export const safeCardTitle = (a: Area) => (a.type === "rural" ? "Safe places and relocation" : "Find my nearest safe place");
