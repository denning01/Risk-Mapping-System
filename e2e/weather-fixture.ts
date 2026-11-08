// M-13 · a synthetic Open-Meteo /v1/forecast response with the real response's shape (checked against a live
// response on 2026-11-08), and known values, so the expected numbers are computed here, not copied from the app.
export const TODAY = "2026-11-08";
export const DAYS = ["2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14"];
// today: rain 0.4 mm at 14:00, 1.2 mm at 15:00, 0.6 mm at 16:00 (total 2.2 mm); probability peaks at 85 % at 15:00;
// probability null at 23:00 (Open-Meteo can return nulls)
const todayMm = Array.from({ length: 24 }, (_, h) => ({ 14: 0.4, 15: 1.2, 16: 0.6 })[h] ?? 0);
const todayProb = Array.from({ length: 24 }, (_, h) => (h === 23 ? null : ({ 14: 60, 15: 85, 16: 70 })[h] ?? 10));
export const DAILY_MM = [2.2, 7.6, 5.3, 0, 12.4, 3.1, 0.2]; // wettest: 2026-11-12, 12.4 mm
export const DAILY_PROB = [85, 92, 91, 20, 95, 60, 30];

export function fixture(lon: number, lat: number) {
  const time: string[] = [];
  const precipitation: (number | null)[] = [];
  const precipitation_probability: (number | null)[] = [];
  DAYS.forEach((d, di) => {
    for (let h = 0; h < 24; h++) {
      time.push(`${d}T${String(h).padStart(2, "0")}:00`);
      precipitation.push(di === 0 ? todayMm[h] : 0.1);
      precipitation_probability.push(di === 0 ? todayProb[h] : 50);
    }
  });
  return {
    latitude: Math.round(lat * 100) / 100, // a model cell near, not at, the requested point
    longitude: Math.round(lon * 100) / 100,
    generationtime_ms: 0.07,
    utc_offset_seconds: 10800,
    timezone: "Africa/Nairobi",
    timezone_abbreviation: "GMT+3",
    elevation: 1200,
    hourly_units: { time: "iso8601", precipitation: "mm", precipitation_probability: "%" },
    hourly: { time, precipitation, precipitation_probability },
    daily_units: { time: "iso8601", precipitation_sum: "mm", precipitation_probability_max: "%" },
    daily: { time: DAYS, precipitation_sum: DAILY_MM, precipitation_probability_max: DAILY_PROB },
  };
}
