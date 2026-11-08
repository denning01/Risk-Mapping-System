"use client";

import { useEffect, useState } from "react";
import { OPEN_METEO_ATTRIBUTION, OPEN_METEO_LICENCE_URL, TIMEZONE, fetchWeather, todayLine, type PointWeather } from "@/lib/weather";
import { Badge, Card } from "./ui";

export interface WeatherPoint {
  label: string;
  lon: number;
  lat: number;
}

type State = { key: string; status: "loading" } | { key: string; status: "ok"; data: PointWeather } | { key: string; status: "error" };

const keyOf = (p: WeatherPoint) => `${p.lon.toFixed(4)},${p.lat.toFixed(4)}`;

function useWeather(p: WeatherPoint | null): State | null {
  const [state, setState] = useState<State | null>(null);
  const key = p ? keyOf(p) : null;
  useEffect(() => {
    if (!p || !key) return;
    let alive = true;
    fetchWeather(p.lon, p.lat).then(
      (data) => alive && setState({ key, status: "ok", data }),
      () => alive && setState({ key, status: "error" }),
    );
    return () => {
      alive = false;
    };
    // p's coordinates are captured by key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  // never show the previous point's weather for the new point
  return state && state.key === key ? state : key ? { key, status: "loading" } : null;
}

const dayLabel = (date: string) =>
  new Date(`${date}T12:00:00Z`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
const timeLabel = (d: Date) => d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: TIMEZONE });
const fmtMm = (x: number | null) => (x === null ? "n/a" : `${x} mm`);
const fmtPct = (x: number | null) => (x === null ? "n/a" : `${x}%`);

function Hourly({ w }: { w: PointWeather }) {
  const top = Math.max(1, ...w.hourly.map((h) => h.mm ?? 0));
  return (
    <div>
      <div className="flex h-12 items-end gap-px" role="list" aria-label="Rain by hour today">
        {w.hourly.map((h) => (
          <div
            key={h.time}
            role="listitem"
            aria-label={`${String(h.hour).padStart(2, "0")}:00 ${fmtMm(h.mm)}, ${fmtPct(h.probability)}`}
            title={`${String(h.hour).padStart(2, "0")}:00 · ${fmtMm(h.mm)} · ${fmtPct(h.probability)}`}
            className="flex-1 rounded-t bg-sky-500"
            style={{ height: `${Math.max(2, ((h.mm ?? 0) / top) * 100)}%`, opacity: h.mm ? 1 : 0.25 }}
          />
        ))}
      </div>
      <div className="flex justify-between text-[10px] text-zinc-500">
        <span>00</span>
        <span>06</span>
        <span>12</span>
        <span>18</span>
        <span>23</span>
      </div>
    </div>
  );
}

function Daily({ w }: { w: PointWeather }) {
  return (
    <table className="mt-2 w-full text-xs" aria-label="Next 7 days">
      <thead>
        <tr className="text-left text-[10px] text-zinc-500">
          <th className="font-medium">Day</th>
          <th className="text-right font-medium">Rain</th>
          <th className="text-right font-medium">Chance</th>
        </tr>
      </thead>
      <tbody>
        {w.daily.map((d) => (
          <tr key={d.date} className="border-t border-zinc-100">
            <td className="py-0.5">{dayLabel(d.date)}</td>
            <td className="py-0.5 text-right tabular-nums">{fmtMm(d.mm)}</td>
            <td className="py-0.5 text-right tabular-nums">{fmtPct(d.probability)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PointBlock({ title, point, full }: { title: string; point: WeatherPoint; full: boolean }) {
  const s = useWeather(point);
  return (
    <div className="space-y-1" data-weather-point={title}>
      <div className="text-xs font-semibold text-zinc-800">
        {title}: {point.label}
      </div>
      {!s || s.status === "loading" ? (
        <p className="text-xs text-zinc-500">Fetching the Open-Meteo forecast…</p>
      ) : s.status === "error" ? (
        <p className="rounded-lg bg-zinc-100 p-2 text-xs text-zinc-700">
          Live weather unavailable (offline, or Open-Meteo did not answer). The flood scenarios and routes still work.
        </p>
      ) : (
        <>
          <p className="text-sm text-zinc-900">{todayLine(s.data)}</p>
          {full && <Hourly w={s.data} />}
          {full ? (
            <Daily w={s.data} />
          ) : (
            s.data.wettest && (
              <p className="text-xs text-zinc-700">
                Wettest of the next 7 days: {dayLabel(s.data.wettest.date)}, {fmtMm(s.data.wettest.mm)}.
              </p>
            )
          )}
          <p className="text-[10px] text-zinc-500">
            Open-Meteo forecast, fetched {timeLabel(s.data.fetchedAt)} EAT, for the model cell at {s.data.cell.lat.toFixed(3)},{" "}
            {s.data.cell.lon.toFixed(3)}.
          </p>
        </>
      )}
    </div>
  );
}

/** "My weather": Open-Meteo's live forecast at the chosen start point, and at the destination once a route exists. */
export function WeatherPanel({ here, destination }: { here: WeatherPoint | null; destination: WeatherPoint | null }) {
  return (
    <Card title="My weather" right={<Badge tone="blue">Open-Meteo forecast</Badge>}>
      {here ? (
        <div className="space-y-3">
          <PointBlock title="Where you are" point={here} full />
          {destination && (
            <div className="border-t border-zinc-100 pt-2">
              <PointBlock title="Where you are going" point={destination} full={false} />
            </div>
          )}
        </div>
      ) : (
        <p className="text-xs text-zinc-600">Choose a starting point to see the live rain forecast there.</p>
      )}
      <p className="mt-2 text-[10px] text-zinc-500">
        Not our forecast: live data from Open-Meteo. The flood map shows scenarios, not forecasts.{" "}
        <a href={OPEN_METEO_LICENCE_URL} target="_blank" rel="noreferrer" className="underline">
          {OPEN_METEO_ATTRIBUTION}
        </a>{" "}
        (CC BY 4.0).
      </p>
    </Card>
  );
}
