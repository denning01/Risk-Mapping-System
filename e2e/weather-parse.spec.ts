// M-13 · unit tests of the Open-Meteo parsing (web/src/lib/weather.ts). No browser: Playwright runs them as plain
// tests. They live in e2e/ because web's own unit-test glob is web/scripts/*.test.ts (Person B's directory).
import { expect, test } from "@playwright/test";
import { parseWeather, todayLine, weatherUrl } from "../web/src/lib/weather";
import { DAILY_MM, DAYS, TODAY, fixture } from "./weather-fixture";

const AT = new Date("2026-11-08T09:30:00Z");

test("weatherUrl asks for hourly + daily rain, 7 days, Nairobi time, at 4 decimals", () => {
  const u = new URL(weatherUrl(36.858123, -1.26));
  expect(u.host).toBe("api.open-meteo.com");
  expect(Object.fromEntries(u.searchParams)).toEqual({
    latitude: "-1.2600",
    longitude: "36.8581",
    hourly: "precipitation,precipitation_probability",
    daily: "precipitation_sum,precipitation_probability_max",
    timezone: "Africa/Nairobi",
    forecast_days: "7",
  });
});

test("parseWeather keeps today's 24 hours, 7 days, sums today and finds the wettest day", () => {
  const w = parseWeather(fixture(36.858, -1.26), AT);
  expect(w.today).toBe(TODAY);
  expect(w.hourly).toHaveLength(24);
  expect(w.hourly.every((h) => h.time.startsWith(TODAY))).toBe(true);
  expect(w.hourly[15]).toEqual({ time: `${TODAY}T15:00`, hour: 15, mm: 1.2, probability: 85 });
  expect(w.hourly[23].probability).toBeNull();
  expect(w.todayTotalMm).toBe(2.2); // 0.4 + 1.2 + 0.6, rounded to 0.1 (float sum is 2.1999…)
  expect(w.todayMaxProbability).toBe(85); // the null hour is skipped, not read as 0
  expect(w.daily.map((d) => d.date)).toEqual(DAYS);
  expect(w.daily.map((d) => d.mm)).toEqual(DAILY_MM);
  expect(w.wettest).toEqual({ date: "2026-11-12", mm: 12.4, probability: 95 });
  expect(w.cell).toEqual({ lon: 36.86, lat: -1.26 });
  expect(w.fetchedAt).toBe(AT);
  expect(todayLine(w)).toBe("Rain expected today: 2.2 mm (chance of rain up to 85%).");
});

test("'today' is the response's first daily date, not the viewer's clock", () => {
  const f = fixture(35, -0.2);
  f.daily.time = DAYS.map((d) => d.replace("2026-11-0", "2026-12-0").replace("2026-11-1", "2026-12-1"));
  const w = parseWeather(f, AT); // hourly times are November, so no hour matches "today"
  expect(w.today).toBe("2026-12-08");
  expect(w.hourly).toEqual([]);
  expect(w.todayTotalMm).toBeNull();
  expect(todayLine(w)).toBe("No rainfall figure for today in the forecast.");
});

test("a dry day reads 'No rain forecast today', and nulls do not become zeros", () => {
  const f = fixture(35, -0.2);
  f.hourly.precipitation = f.hourly.precipitation.map(() => 0);
  f.hourly.precipitation_probability = f.hourly.precipitation_probability.map(() => null);
  f.daily.precipitation_sum = [null, 1, 2, 3, 4, 5, 6];
  const w = parseWeather(f, AT);
  expect(w.todayTotalMm).toBe(0);
  expect(w.todayMaxProbability).toBeNull();
  expect(todayLine(w)).toBe("No rain forecast today.");
  expect(w.daily[0].mm).toBeNull();
  expect(w.wettest?.date).toBe("2026-11-14");
});

test("parseWeather refuses a malformed response", () => {
  expect(() => parseWeather({ error: true, reason: "Parameter 'hourly' is invalid" }, AT)).toThrow();
  const short = fixture(35, -0.2);
  short.hourly.precipitation = short.hourly.precipitation.slice(1);
  expect(() => parseWeather(short, AT)).toThrow(/differ in length/);
  const bad = fixture(35, -0.2) as Record<string, any>;
  bad.daily.precipitation_sum[2] = "5.3";
  expect(() => parseWeather(bad, AT)).toThrow();
});
