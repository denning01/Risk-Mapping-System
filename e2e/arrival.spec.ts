// M-21 · arrival wording. arrival_h is the FAST bound (M-20 ruling). Under 1 h -> "within minutes (local rain or nearby
// stream)"; else "as little as ~X h (screening estimate)"; never "0 h". The published scenarios carry arrival_h null
// today (E-20 fills them), so the browser test serves 250_elnino (the widest floods: clickable in both areas) with arrival values set per feature (page.route).
import { expect, test } from "@playwright/test";
import { arrivalSentence, arrivalTick } from "../web/src/lib/arrival";
import type { FloodCollection } from "../web/src/lib/types";
import { areas, openScenario, readJson, watch } from "./helpers";
import { clickAt, wetPoints } from "./map-helpers";

test("the wording: minutes under 1 h, '~X h' above, never '0 h', never NaN", () => {
  expect(arrivalSentence(0)).toBe("Water could arrive within minutes (local rain or nearby stream)");
  expect(arrivalSentence(0.99)).toBe("Water could arrive within minutes (local rain or nearby stream)");
  expect(arrivalSentence(1)).toBe("Water could arrive in as little as ~1 h (screening estimate)");
  expect(arrivalSentence(2.46)).toBe("Water could arrive in as little as ~2.5 h (screening estimate)");
  expect(arrivalSentence(12.6)).toBe("Water could arrive in as little as ~13 h (screening estimate)");
  expect(arrivalSentence(null)).toBe("No arrival estimate for this area");
  expect([arrivalTick(0), arrivalTick(0.5), arrivalTick(1.04), arrivalTick(9.96)]).toEqual(["minutes", "minutes", "~1 h", "~10 h"]);
  const bad: string[] = [];
  for (let k = 0; k <= 6000; k++) {
    const h = k / 200; // 0 .. 30 h in 0.005 h steps
    for (const t of [arrivalSentence(h), arrivalTick(h)]) if (/(^|[^0-9.])0 h|~0(\.0)? h|NaN/.test(t)) bad.push(`${h}: ${t}`);
  }
  expect(bad).toEqual([]);
});

for (const area of areas()) {
  test(`${area.id}: popup and legend use the arrival wording (minutes / ~X h), no "0 h"`, async ({ page, baseURL }) => {
    const errors = await watch(page, baseURL!);
    await page.route("https://api.open-meteo.com/**", (r) => r.fulfill({ status: 503, body: "" }));
    const flood = readJson<FloodCollection>(`${area.id}/scenarios/250_elnino.geojson`);
    // 1. at the opening view, which features have points that stay inside them 3 px around (safe to click)?
    await openScenario(page, area, 250, "elnino");
    const clickable: { k: number; pts: [number, number][] }[] = [];
    for (let k = 0; k < flood.features.length; k++) {
      const pts = await wetPoints(page, { ...flood, features: [flood.features[k]] });
      if (pts.length) clickable.push({ k, pts });
    }
    expect(clickable.length, "features with clickable interior points").toBeGreaterThanOrEqual(2);
    // 2. arrival 0 h on the first of them, 2.46 h on the second, 12.6 h elsewhere (the legend's maximum)
    const arr = flood.features.map((_, k) => (k === clickable[0].k ? 0 : k === clickable[1].k ? 2.46 : 12.6));
    const withArr: FloodCollection = { ...flood, features: flood.features.map((f, k) => ({ ...f, properties: { ...f.properties, arrival_h: arr[k] } })) };
    await page.route(`**/data/${area.id}/scenarios/250_elnino.geojson`, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(withArr) }));
    await openScenario(page, area, 250, "elnino");
    await page.getByRole("button", { name: "Show arrival time" }).click();
    const legend = page.locator("[data-arrival-legend]");
    const max = Math.max(...arr);
    await expect(legend).toHaveText([arrivalTick(0), arrivalTick(max / 2), arrivalTick(max)].join(""));
    await expect(legend).toContainText("minutes");
    await expect(page.getByText("Water could arrive in as little as", { exact: true })).toBeVisible();
    await expect(page.locator("body")).not.toContainText(/(^|[^0-9.])0 h\b/);

    // 3. the popups
    const checked: number[] = [];
    for (const c of clickable.slice(0, 2)) {
      for (const [lon, lat] of c.pts) {
        await page.locator(".maplibregl-popup-close-button").click({ timeout: 500 }).catch(() => {});
        if (!(await clickAt(page, lon, lat))) continue;
        const pop = page.locator(".maplibregl-popup [data-arrival]");
        try {
          await expect(pop).toHaveCount(1, { timeout: 2000 });
        } catch {
          continue; // a shelter or marker took the click
        }
        await expect(pop).toHaveText(arrivalSentence(arr[c.k]));
        checked.push(arr[c.k]);
        break;
      }
    }
    expect(checked, "popups checked for 0 h and 2.46 h").toEqual([0, 2.46]);
    expect(errors.filter((e) => !e.includes("open-meteo")), errors.join("\n")).toEqual([]);
  });
}
