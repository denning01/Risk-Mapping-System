/**
 * M-13 · Live Open-Meteo forecast for one point, fetched in the browser (no key).
 * This is Open-Meteo's forecast, never ours: the flood map shows scenarios, not forecasts.
 * Data licence: CC BY 4.0, "Weather data by Open-Meteo.com" (open-meteo.com/en/licence).
 *
 * No path aliases here: e2e/weather-parse.spec.ts imports this file directly.
 */
import { z } from "zod";

export const OPEN_METEO_HOST = "api.open-meteo.com";
export const OPEN_METEO_ATTRIBUTION = "Weather data by Open-Meteo.com";
export const OPEN_METEO_LICENCE_URL = "https://open-meteo.com/en/licence";
export const TIMEZONE = "Africa/Nairobi"; // both areas are in Kenya (EAT, UTC+3)
export const FETCH_TIMEOUT_MS = 8000;

export function weatherUrl(lon: number, lat: number): string {
  const q = new URLSearchParams({
    latitude: lat.toFixed(4),
    longitude: lon.toFixed(4),
    hourly: "precipitation,precipitation_probability",
    daily: "precipitation_sum,precipitation_probability_max",
    timezone: TIMEZONE,
    forecast_days: "7",
  });
  return `https://${OPEN_METEO_HOST}/v1/forecast?${q.toString()}`;
}

const num = z.number().nullable();
const OpenMeteoSchema = z.object({
  latitude: z.number(),
  longitude: z.number(),
  hourly: z.object({ time: z.array(z.string()), precipitation: z.array(num), precipitation_probability: z.array(num) }),
  daily: z.object({ time: z.array(z.string()).min(1), precipitation_sum: z.array(num), precipitation_probability_max: z.array(num) }),
});

export interface HourRain {
  time: string; // local, "YYYY-MM-DDTHH:MM"
  hour: number;
  mm: number | null;
  probability: number | null;
}
export interface DayRain {
  date: string; // local, "YYYY-MM-DD"
  mm: number | null;
  probability: number | null;
}
export interface PointWeather {
  /** The Open-Meteo model grid cell the request snapped to (not exactly the requested point). */
  cell: { lon: number; lat: number };
  today: string;
  hourly: HourRain[]; // today's hours only
  daily: DayRain[]; // up to 7 days, today first
  todayTotalMm: number | null; // sum of today's hourly values; null if every hour is null
  todayMaxProbability: number | null;
  wettest: DayRain | null; // the day with the largest precipitation_sum (first one on ties)
  fetchedAt: Date;
}

const round1 = (x: number) => Math.round(x * 10) / 10;

/**
 * Parse an Open-Meteo /v1/forecast response. Throws on a malformed one. "Today" is the response's own first daily
 * date (Open-Meteo's local date in TIMEZONE), so the result does not depend on the viewer's clock or time zone.
 */
export function parseWeather(json: unknown, fetchedAt: Date): PointWeather {
  const r = OpenMeteoSchema.parse(json);
  const { hourly: h, daily: d } = r;
  if (h.precipitation.length !== h.time.length || h.precipitation_probability.length !== h.time.length)
    throw new Error("Open-Meteo hourly arrays differ in length");
  if (d.precipitation_sum.length !== d.time.length || d.precipitation_probability_max.length !== d.time.length)
    throw new Error("Open-Meteo daily arrays differ in length");
  const today = d.time[0];
  const hourly: HourRain[] = [];
  h.time.forEach((t, i) => {
    if (t.slice(0, 10) !== today) return;
    hourly.push({ time: t, hour: Number(t.slice(11, 13)), mm: h.precipitation[i], probability: h.precipitation_probability[i] });
  });
  const daily: DayRain[] = d.time.slice(0, 7).map((date, i) => ({ date, mm: d.precipitation_sum[i], probability: d.precipitation_probability_max[i] }));
  const mms = hourly.map((x) => x.mm).filter((x): x is number => x !== null);
  const probs = hourly.map((x) => x.probability).filter((x): x is number => x !== null);
  let wettest: DayRain | null = null;
  for (const day of daily) if (day.mm !== null && (wettest === null || day.mm > (wettest.mm ?? -1))) wettest = day;
  return {
    cell: { lon: r.longitude, lat: r.latitude },
    today,
    hourly,
    daily,
    todayTotalMm: mms.length ? round1(mms.reduce((a, b) => a + b, 0)) : null,
    todayMaxProbability: probs.length ? Math.max(...probs) : null,
    wettest,
    fetchedAt,
  };
}

/** One-line reading of today's forecast, worded as Open-Meteo's forecast, with no threshold of our own. */
export function todayLine(w: PointWeather): string {
  if (w.todayTotalMm === null) return "No rainfall figure for today in the forecast.";
  const p = w.todayMaxProbability === null ? "" : ` (chance of rain up to ${w.todayMaxProbability}%)`;
  return w.todayTotalMm > 0 ? `Rain expected today: ${w.todayTotalMm} mm${p}.` : `No rain forecast today${p}.`;
}

const cache = new Map<string, Promise<PointWeather>>();
const CACHE_MS = 10 * 60 * 1000;

/** Fetch with a timeout; cached per 4-decimal point for 10 minutes. A failed fetch is dropped from the cache. */
export function fetchWeather(lon: number, lat: number): Promise<PointWeather> {
  const url = weatherUrl(lon, lat);
  const hit = cache.get(url);
  if (hit) return hit;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  const p = fetch(url, { signal: ctrl.signal })
    .then((res) => {
      if (!res.ok) throw new Error(`Open-Meteo HTTP ${res.status}`);
      return res.json();
    })
    .then((j) => parseWeather(j, new Date()))
    .finally(() => clearTimeout(timer));
  cache.set(url, p);
  p.then(
    () => setTimeout(() => cache.delete(url), CACHE_MS),
    () => cache.delete(url),
  );
  return p;
}
