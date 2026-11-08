"use client";

import { arrivalTick } from "@/lib/arrival";
import { useState } from "react";
import type { Area, CropRule, Enso, Exposure, Forecast, Meta, Origin, Population, Rain, Risk, Route, Scenario, Shelter } from "@/lib/types";
import { RISK_COLORS, SHELTER_TYPE_LABELS } from "@/lib/types";
import { RAIN_VALUES } from "@/lib/schema";
import { alertText, adviceFallback, type Lang } from "@/lib/alertTemplates";
import { AnimatedNumber, Badge, Card, RiskBadge, Skeleton } from "./ui";

// ---------------------------------------------------------------------------
// Scenario controls
// ---------------------------------------------------------------------------
export function ScenarioControls(props: {
  rain: Rain;
  enso: Enso;
  animating: boolean;
  onRain: (r: Rain) => void;
  onEnso: (e: Enso) => void;
  onAnimate: () => void;
}) {
  const idx = RAIN_VALUES.indexOf(props.rain);
  return (
    <Card title="Rainfall scenario">
      <div className="flex items-baseline justify-between">
        <span className="text-2xl font-bold tabular-nums text-zinc-900">
          {props.rain} <span className="text-sm font-medium text-zinc-500">mm in 24 h</span>
        </span>
        <button
          onClick={props.onAnimate}
          className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${props.animating ? "bg-red-600 text-white" : "bg-blue-600 text-white hover:bg-blue-700"}`}
        >
          {props.animating ? "■ Stop" : "▶ Animate"}
        </button>
      </div>
      <input
        type="range"
        min={0}
        max={RAIN_VALUES.length - 1}
        step={1}
        value={idx}
        onChange={(e) => props.onRain(RAIN_VALUES[Number(e.target.value)])}
        className="mt-2 w-full accent-blue-600"
        aria-label="Rainfall in mm per 24 hours"
      />
      <div className="flex justify-between text-[10px] text-zinc-500">
        {RAIN_VALUES.map((r) => (
          <span key={r}>{r}</span>
        ))}
      </div>
      <label className="mt-3 flex cursor-pointer items-center justify-between rounded-lg bg-zinc-50 px-3 py-2">
        <span className="text-sm font-medium text-zinc-800">
          El Niño season
          <span className="block text-[11px] font-normal text-zinc-500">Wetter soil before the storm: more runoff</span>
        </span>
        <input
          type="checkbox"
          className="h-5 w-9 cursor-pointer appearance-none rounded-full bg-zinc-300 transition-colors before:block before:h-4 before:w-4 before:translate-x-0.5 before:rounded-full before:bg-white before:transition-transform checked:bg-blue-600 checked:before:translate-x-[18px]"
          checked={props.enso === "elnino"}
          onChange={(e) => props.onEnso(e.target.checked ? "elnino" : "normal")}
        />
      </label>
      <p className="mt-2 rounded-md bg-amber-50 px-2 py-1 text-[11px] font-medium text-amber-800">
        Scenario: {props.rain} mm in 24 h{props.enso === "elnino" ? " + El Niño" : ""}. Not a forecast.
      </p>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Legend (floats on the map)
// ---------------------------------------------------------------------------
export function Legend({ arrival, maxArrival }: { arrival: boolean; maxArrival: number }) {
  return (
    <div className="pointer-events-auto rounded-lg bg-white/95 p-1.5 text-[10px] shadow-md sm:p-2 sm:text-[11px]">
      {arrival ? (
        <>
          <div className="mb-1 font-semibold text-zinc-700">Typical arrival time (sooner in places)</div>
          <div className="h-2 w-32 rounded" style={{ background: "linear-gradient(90deg,#7c3aed,#2563eb,#06b6d4,#a5f3fc)" }} />
          <div className="flex w-32 justify-between text-zinc-500" data-arrival-legend>
            <span>{arrivalTick(0)}</span>
            <span>{arrivalTick(maxArrival / 2)}</span>
            <span>{arrivalTick(maxArrival)}</span>
          </div>
          <div className="text-zinc-400" data-arrival-caveat>screening estimate</div>
        </>
      ) : (
        <>
          <div className="mb-1 font-semibold text-zinc-700">Flood risk (water depth)</div>
          {(
            [
              ["high", "High · over 1 m"],
              ["medium", "Medium · 0.3–1 m"],
              ["low", "Low · under 0.3 m"],
            ] as [Risk, string][]
          ).map(([r, label]) => (
            <div key={r} className="flex items-center gap-1.5">
              <span className="inline-block h-3 w-3 rounded-sm" style={{ background: RISK_COLORS[r], opacity: 0.8 }} />
              {label}
            </div>
          ))}
        </>
      )}
      <div className="mt-1 hidden items-center gap-1.5 sm:flex">
        <span className="inline-block h-3 w-3 rounded-full border-2 border-white bg-green-600 shadow" /> Safe place
      </div>
      <div className="hidden items-center gap-1.5 sm:flex">
        <span className="inline-block h-3 w-3 rounded-full border-2 border-white bg-zinc-400 shadow" /> Flooded place
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exposure
// ---------------------------------------------------------------------------
/**
 * Growth rate is per census unit, and an area can span several counties
 * (Nyando covers six). Showing `units[0].r` made one county's rate look like
 * everyone's, so show the spread when the units disagree.
 */
function PopulationCaption({ population }: { population: Population }) {
  const rates = population.units.map((u) => u.r * 100);
  const lo = Math.min(...rates);
  const hi = Math.max(...rates);
  const growth = hi - lo < 0.005 ? `${lo.toFixed(2)}%/yr` : `${lo.toFixed(2)}–${hi.toFixed(2)}%/yr`;
  return (
    <p className="mt-2 text-[11px] text-zinc-500">
      Census base: {population.units.map((u) => u.unit).join(", ")} (KNBS 2009/2019), growth {growth}
      {population.units.length > 1 ? " across units" : ""}
      {population.placeholder ? " (placeholder figures)" : ""}.
    </p>
  );
}

export function ExposurePanel({ exposure, population, highlight }: { exposure: Exposure | null; population: Population | null; highlight?: boolean }) {
  if (!exposure) {
    return (
      <Card title="People and buildings at risk">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="mt-2 h-4 w-56" />
      </Card>
    );
  }
  const p = exposure.population;
  return (
    <Card
      title="People and buildings at risk"
      highlight={highlight}
      right={exposure.source === "mock" ? <Badge tone="amber">Mock</Badge> : <Badge tone="green">Model</Badge>}
    >
      <div className="text-3xl font-extrabold tabular-nums text-red-600">
        <AnimatedNumber value={p.medium} />
        <span className="ml-1 text-sm font-medium text-zinc-500">people</span>
      </div>
      <div className="text-xs text-zinc-600">
        Range {p.low.toLocaleString("en-US")} to {p.high.toLocaleString("en-US")} (low / high growth), projected for {exposure.year}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <div className="rounded-lg bg-zinc-50 p-2">
          <div className="text-lg font-bold tabular-nums text-zinc-900">
            <AnimatedNumber value={exposure.buildings} />
          </div>
          <div className="text-[11px] text-zinc-500">buildings at risk</div>
        </div>
        <div className="rounded-lg bg-zinc-50 p-2">
          <div className="text-lg font-bold tabular-nums text-zinc-900">{exposure.flooded_area_km2.toFixed(1)}</div>
          <div className="text-[11px] text-zinc-500">km² flooded</div>
        </div>
      </div>
      {population && population.units.length > 0 && <PopulationCaption population={population} />}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Roads cut
// ---------------------------------------------------------------------------
export function RoadsPanel({ exposure, highlight }: { exposure: Exposure | null; highlight?: boolean }) {
  return (
    <Card title="Roads likely to be cut" highlight={highlight}>
      {!exposure ? (
        <Skeleton className="h-4 w-48" />
      ) : exposure.roads_cut.length === 0 ? (
        <p className="text-sm text-green-700">No main roads cut in this scenario.</p>
      ) : (
        <ul className="space-y-1">
          {exposure.roads_cut.map((r) => (
            <li key={r} className="flex items-center gap-2 text-sm text-zinc-800">
              <span className="h-2 w-2 rounded-full bg-red-600" />
              {r}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Safe places & routes
// ---------------------------------------------------------------------------
export function SafePlacesPanel(props: {
  area: Area;
  origins: Origin[];
  selectedOrigin: string | null;
  onOrigin: (id: string) => void;
  route: Route | null;
  shelters: Shelter[];
  highlight?: boolean;
  /** M-14: route from a tapped / located point */
  tap?: {
    /** the route is still being computed (the road graph loading) */
    pending: boolean;
    /** why there is no route: shown in the 1199 card instead of the preset text */
    noRouteWhy: string | null;
    /** a problem that is not a flood refusal (graph unavailable, too far from any path): no 1199 card */
    note: string | null;
    /** RULING R20: the answers for a free tap (nearest safe shelter, nearest high ground, each with a safer way) */
    options?: { id: string; label: string; active: boolean }[];
  } | null;
  onTapOption?: (id: string) => void;
  onLocate?: () => void;
  locateNote?: string | null;
}) {
  const { route, tap } = props;
  const shelter = route?.shelter_id ? props.shelters.find((s) => s.id === route.shelter_id) : undefined;
  const isRural = props.area.type === "rural";
  const extra = route?.baseline ? route.safe.minutes - route.baseline.minutes : 0;
  const safeCount = props.shelters.filter((s) => s.safe).length;
  return (
    <Card
      title={isRural ? "Safe places and relocation" : "Find my nearest safe place"}
      highlight={props.highlight}
      right={<Badge tone="green">{safeCount}/{props.shelters.length} safe</Badge>}
    >
      <label className="text-[11px] font-medium text-zinc-500" htmlFor="origin">
        Start from (or click the map)
      </label>
      <select
        id="origin"
        value={props.selectedOrigin ?? ""}
        onChange={(e) => props.onOrigin(e.target.value)}
        className="mt-0.5 w-full rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm"
      >
        <option value="" disabled>
          Choose a location…
        </option>
        {props.origins.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
      </select>
      {props.onLocate && (
        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-zinc-500">
          <button onClick={props.onLocate} className="rounded-md border border-blue-600 px-2 py-0.5 font-semibold text-blue-700 hover:bg-blue-50">
            Use my location
          </button>
          <span>or tap the map to route from any point.</span>
        </div>
      )}
      {props.locateNote && <p className="mt-1 text-xs text-amber-800">{props.locateNote}</p>}
      {tap?.pending && <p className="mt-3 text-sm text-zinc-600">Finding the safest route on foot from this point…</p>}
      {tap?.note && <p className="mt-3 rounded-lg bg-amber-50 p-2 text-sm text-amber-900">{tap.note}</p>}

      {props.selectedOrigin && !route && !tap?.pending && !tap?.note && (
        <div className="mt-3 rounded-lg border border-red-300 bg-red-50 p-2 text-sm">
          <div className="font-semibold text-red-800">No safe route on foot.</div>
          <p className="mt-1 text-red-900">
            Move to an upper floor or high ground and call for help: Kenya Red Cross toll-free{" "}
            <a href="tel:1199" className="font-bold underline">
              1199
            </a>
            .
          </p>
          <p className="mt-1 text-[11px] text-red-700">
            {tap?.noRouteWhy ?? "This starting point is inside the flood extent in this scenario, so no route leaves it on dry ground."}
          </p>
        </div>
      )}

      {route && (
        <div className="mt-3 space-y-2 text-sm">
          {route.kind === "commute" ? (
            <>
              <div className="font-semibold text-zinc-900">Commute to {route.destination_name}</div>
              {extra > 0 ? (
                <div className="rounded-lg bg-blue-50 p-2">
                  <div className="flex items-center gap-2">
                    <span className="h-1 w-6 rounded bg-blue-600" /> Safe route: <b>{route.safe.minutes} min</b>
                    <Badge tone="red">+{extra} min</Badge>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-zinc-500">
                    <span className="h-0 w-6 border-t-2 border-dashed border-zinc-500" /> Usual route: {route.baseline?.minutes} min (flooded)
                  </div>
                </div>
              ) : (
                <div className="rounded-lg bg-green-50 p-2 text-green-800">Usual route is clear: {route.safe.minutes} min.</div>
              )}
            </>
          ) : (
            <>
              <div className="font-semibold text-zinc-900">
                {route.kind === "relocation" ? "Relocate to high ground: " : "Go to: "}
                {route.destination_name}
              </div>
              <div className="rounded-lg bg-blue-50 p-2">
                <span className="mr-1 inline-block h-1 w-6 rounded bg-blue-600 align-middle" /> About <b>{route.safe.minutes} min</b> on foot
                {shelter && route.kind === "to_shelter" ? <span className="text-zinc-500"> · {SHELTER_TYPE_LABELS[shelter.type] ?? shelter.type}</span> : null}
                {shelter?.capacity ? <span className="text-zinc-500"> · capacity {shelter.capacity}</span> : null}
              </div>
              {tap && tap.options && tap.options.length > 0 && (
                <div className="space-y-1" role="radiogroup" aria-label="Safe place options">
                  {tap.options.map((o) => (
                    <button
                      key={o.id}
                      role="radio"
                      aria-checked={o.active}
                      data-option={o.id}
                      onClick={() => props.onTapOption?.(o.id)}
                      className={`w-full rounded-md border px-2 py-1 text-left text-xs ${o.active ? "border-blue-600 bg-blue-50 font-semibold text-blue-900" : "border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50"}`}
                    >
                      {o.label}
                    </button>
                  ))}
                </div>
              )}
              {tap && (
                <p className="text-[11px] text-zinc-500">
                  Computed in your browser on the mapped roads and paths for this scenario: flooded paths are never used. The fastest safe route is
                  shown first; where it passes close to water, a safer way (paths next to water cost 3×) is offered with its extra minutes.
                  Screening-level, not a forecast.
                </p>
              )}
            </>
          )}
          {route.avoided.length > 0 && (
            <div className="text-xs text-zinc-700">
              <span className="font-semibold text-red-700">Avoid:</span> {route.avoided.join(", ")}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Farmer advisory
// ---------------------------------------------------------------------------
export function AdvisoryPanel(props: { crops: CropRule[]; enso: Enso; highlight?: boolean; aiEnabled: boolean; scenarioRain: Rain }) {
  const cropNames = [...new Set(props.crops.map((c) => c.crop))];
  const [crop, setCrop] = useState(cropNames[0] ?? "maize");
  const [season, setSeason] = useState<CropRule["season"]>("short_rains");
  const [lang, setLang] = useState<Lang>("en");
  const [ai, setAi] = useState<{ text: string; generated: boolean; enso: Enso; rain: Rain } | null>(null);
  const [loading, setLoading] = useState(false);
  const rule = props.crops.find((c) => c.crop === crop && c.season === season && c.enso === props.enso);
  // The generated text is grounded in the rule *and* the rainfall, so it stops
  // being valid as soon as either changes from outside this panel. Derived
  // rather than reset in an effect, so no stale text is ever painted.
  const advice = ai && ai.enso === props.enso && ai.rain === props.scenarioRain ? ai : null;

  async function generate() {
    if (!rule) return;
    setLoading(true);
    setAi(null);
    try {
      const res = await fetch("/api/advice-text", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ rule, lang, rain: props.scenarioRain }),
      });
      const json = (await res.json()) as { text: string; generated: boolean };
      setAi({ ...json, enso: props.enso, rain: props.scenarioRain });
    } catch {
      setAi({
        text: adviceFallback(lang, rule.crop, rule.risk, rule.actions),
        generated: false,
        enso: props.enso,
        rain: props.scenarioRain,
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card title="Farmer advisory" highlight={props.highlight}>
      <div className="grid grid-cols-2 gap-2">
        <select value={crop} onChange={(e) => { setCrop(e.target.value); setAi(null); }} className="rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm capitalize" aria-label="Crop">
          {cropNames.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select value={season} onChange={(e) => { setSeason(e.target.value as CropRule["season"]); setAi(null); }} className="rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm" aria-label="Season">
          <option value="short_rains">Short rains (Oct–Dec)</option>
          <option value="long_rains">Long rains (Mar–May)</option>
        </select>
      </div>
      <p className="mt-1 text-[11px] text-zinc-500">ENSO state follows the El Niño toggle: {props.enso === "elnino" ? "El Niño" : "normal"}.</p>
      {rule ? (
        <div className="mt-2">
          <RiskBadge risk={rule.risk} />
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-zinc-800">
            {rule.actions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-zinc-500">Sources: {rule.sources.join("; ")}</p>
          {props.aiEnabled && (
            <div className="mt-2 border-t border-zinc-100 pt-2">
              <div className="flex items-center gap-2">
                <select value={lang} onChange={(e) => setLang(e.target.value as Lang)} className="rounded border border-zinc-300 px-1 py-1 text-xs" aria-label="Language">
                  <option value="en">English</option>
                  <option value="sw">Kiswahili</option>
                </select>
                <button onClick={generate} disabled={loading} className="rounded-lg bg-zinc-900 px-3 py-1 text-xs font-semibold text-white disabled:opacity-50">
                  {loading ? "Writing…" : "Plain-language advice"}
                </button>
              </div>
              {advice && (
                <div className="mt-2 rounded-lg bg-zinc-50 p-2 text-sm">
                  {advice.text}
                  <div className="mt-1">{advice.generated ? <Badge tone="blue">AI-generated</Badge> : <Badge>Template</Badge>}</div>
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <p className="mt-2 text-sm text-zinc-500">No advice for this combination yet.</p>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Alert preview (phone frame)
// ---------------------------------------------------------------------------
export function AlertPreview(props: {
  area: Area;
  scenario: Scenario;
  rain: Rain;
  enso: Enso;
  origin: Origin | null;
  route: Route | null;
  riskHere: Risk | null;
  smsEnabled: boolean;
}) {
  const [lang, setLang] = useState<Lang>("en");
  const [phone, setPhone] = useState("+2547");
  const [status, setStatus] = useState<string | null>(null);
  const risk: Risk = props.riskHere ?? "low";
  const areaName = props.area.name.split(" (")[0];
  const shelter = props.route?.kind !== "commute" ? props.route?.destination_name : undefined;
  const text = alertText(lang, {
    areaName,
    rain: props.rain,
    elnino: props.enso === "elnino",
    risk,
    place: props.origin?.name ?? areaName,
    shelter,
    minutes: shelter ? props.route?.safe.minutes : undefined,
    noRoute: !!props.origin && !props.route,
    avoid: props.route?.avoided ?? props.scenario.exposure.roads_cut.slice(0, 2),
  });

  async function send() {
    setStatus("Sending…");
    try {
      const res = await fetch("/api/send-test-sms", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ to: phone, message: text }),
      });
      const json = (await res.json()) as { ok: boolean; error?: string };
      setStatus(json.ok ? "Sent to the Africa's Talking sandbox simulator." : `Failed: ${json.error}`);
    } catch {
      setStatus("Failed to reach the server.");
    }
  }

  return (
    <Card title="Alert preview (SMS)" right={<Badge tone="amber">Mock</Badge>}>
      <div className="mb-2 flex gap-1">
        {(["en", "sw"] as Lang[]).map((l) => (
          <button
            key={l}
            onClick={() => setLang(l)}
            className={`rounded-md px-2 py-0.5 text-xs font-semibold ${lang === l ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-700"}`}
          >
            {l === "en" ? "English" : "Kiswahili"}
          </button>
        ))}
      </div>
      <div className="mx-auto w-56 rounded-[2rem] border-[6px] border-zinc-900 bg-zinc-100 p-3 shadow-inner">
        <div className="mx-auto mb-2 h-1 w-12 rounded bg-zinc-400" />
        <div className="text-[10px] font-semibold text-zinc-500">FLOOD-EWS</div>
        <div className="mt-1 rounded-2xl rounded-tl-sm bg-white p-2 text-[12px] leading-snug text-zinc-900 shadow-sm">{text}</div>
      </div>
      <p className="mt-2 text-[11px] text-zinc-500">Built from fixed templates. Swahili text needs review by a native speaker.</p>
      {props.smsEnabled && (
        <div className="mt-2 flex gap-2">
          <input value={phone} onChange={(e) => setPhone(e.target.value)} className="min-w-0 flex-1 rounded-lg border border-zinc-300 px-2 py-1 text-sm" aria-label="Sandbox phone number" />
          <button onClick={send} className="rounded-lg bg-green-600 px-3 py-1 text-xs font-semibold text-white">
            Send test
          </button>
        </div>
      )}
      {status && <p className="mt-1 text-xs text-zinc-600">{status}</p>}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Limitations text (About modal)
// ---------------------------------------------------------------------------
export function LimitationsContent({ meta }: { meta?: Meta | null }) {
  return (
    <div className="space-y-3 text-sm text-zinc-700">
      <p>
        This is an <b>impact-based flood early warning</b> prototype for Nairobi (urban) and Nyando, Kisumu (rural). It turns a rainfall scenario into
        where water goes, who is exposed, where to move and which road to take. It complements official warnings from KMD, ICPAC and the county
        governments; it does not replace them.
      </p>
      <h3 className="font-semibold text-zinc-900">Honest limitations</h3>
      <ul className="list-disc space-y-1 pl-5">
        <li>Free elevation data (about 30 m) is not accurate to the last metre. The model uses HAND (height above nearest drainage), which tolerates elevation error, and the output is a <b>screening-level</b> risk map.</li>
        <li>
          Flood extent is a <b>screening-level approximation</b> (terrain + rainfall-runoff, not a hydraulic model), calibrated against Sentinel-1 satellite
          observations of the Nov 2023 Nyando flood. Nairobi uses Nyando&rsquo;s calibration. HEC-RAS or LISFLOOD-FP would be the next step.
        </li>
        <li>Nyando terrain is GLO-30, a surface model: on buildings it sits about 1&ndash;2 m above bare earth, so flood depth there may be understated. Nairobi uses bare-earth FABDEM.</li>
        <li>Nairobi&rsquo;s flood model is not calibrated locally (satellite radar cannot see urban floods reliably); it uses Nyando&rsquo;s calibration.</li>
        <li>Population after 2019 is a projection with low / medium / high scenarios. Informal settlements are likely undercounted.</li>
        <li>The rainfall slider is a <b>scenario tool, not a forecast</b>. Any forecast shown in the app is an official outlook from ICPAC or Open-Meteo / GloFAS, not ours.</li>
        <li>Crop advice is rule-based from published guidance and needs validation by local extension officers.</li>
        <li>Anything labelled <b>Mock</b> uses placeholder data for demonstration.</li>
      </ul>
      {meta?.notes && (
        <>
          <h3 className="font-semibold text-zinc-900">Status of this dataset</h3>
          <p className="whitespace-pre-line text-xs">{meta.notes}</p>
          {meta.generated_at && <p className="text-[11px] text-zinc-500">Generated {formatAsOf(meta.generated_at)}.</p>}
        </>
      )}
      <h3 className="font-semibold text-zinc-900">Data sources</h3>
      {meta?.sources?.length ? (
        <ul className="list-disc space-y-0.5 pl-5 text-xs">
          {meta.sources.map((src) => (
            <li key={src}>{src}</li>
          ))}
        </ul>
      ) : null}
      <p className="text-xs">
        OpenStreetMap (Geofabrik extract of 2026-11-04), <b>FABDEM V1-2 (CC BY-NC-SA 4.0, &copy; University of Bristol / Fathom) for Nairobi</b>; Copernicus
        GLO-30 for Nyando; CHIRPS, ESA WorldCover, WorldPop, Google Open Buildings v3, Sentinel-1, JRC Global Surface Water, KNBS census, NOAA ONI, FAO
        EcoCrop, KALRO. Basemap &copy; OpenStreetMap contributors, OpenFreeMap.
      </p>
      <p className="rounded-md bg-amber-50 px-2 py-1 text-[11px] text-amber-900">
        FABDEM V1-2 is licensed <b>CC BY-NC-SA 4.0</b>: non-commercial, share-alike. The Nairobi flood layers are derived from it and inherit that licence.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Forecast banner (official outlooks only, never our own forecast)
// ---------------------------------------------------------------------------
export function ForecastBanner({ forecast, onUseScenario }: { forecast: Forecast | null; onUseScenario: (rain: Rain, enso: Enso) => void }) {
  if (!forecast) return null;
  const { icpac, short_range: shortRange, suggested_scenario: suggested } = forecast;
  const asOf = formatAsOf(forecast.as_of);
  const pct = icpac?.above_normal_pct;
  const pctLabel = Array.isArray(pct) ? `${pct[0]}\u2013${pct[1]}%` : typeof pct === "number" ? `${pct}%` : null;
  return (
    <div className="rounded-xl border border-sky-300 bg-sky-50 p-2.5">
      <div className="flex items-center gap-2">
        <Badge tone="blue">Official outlook</Badge>
        <span className="text-[10px] text-sky-800">Forecast snapshot as of {asOf}</span>
      </div>
      {icpac && (
        <p className="mt-1.5 text-sm font-semibold text-sky-950">
          ICPAC outlook {icpac.season}: wetter than normal{pctLabel ? ` (${pctLabel} chance of above-normal rain)` : ""}
        </p>
      )}
      {shortRange && (
        <p className="mt-0.5 text-[11px] text-sky-900">
          Next 16 days ({shortRange.source}): wettest day {shortRange.wettest_day_mm ?? "n/a"} mm
          {shortRange.river_discharge_m3s !== null && shortRange.river_discharge_m3s !== undefined ? ` · river ${shortRange.river_discharge_m3s} m³/s` : ""}
        </p>
      )}
      {suggested ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button
            onClick={() => onUseScenario(suggested.rain, suggested.enso)}
            className="rounded-lg bg-sky-700 px-3 py-1 text-xs font-semibold text-white hover:bg-sky-800"
          >
            Show the matching scenario ({suggested.rain} mm{suggested.enso === "elnino" ? " + El Niño" : ""})
          </button>
          <span className="text-[10px] text-sky-800">{suggested.rule}</span>
        </div>
      ) : (
        <p className="mt-1 text-[11px] font-medium text-sky-900">No flood scenario expected in the next 16 days.</p>
      )}
      <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-sky-700 underline">
        {icpac?.url && (
          <a href={icpac.url} target="_blank" rel="noreferrer">
            {icpac.statement}
          </a>
        )}
        {shortRange?.url && (
          <a href={shortRange.url} target="_blank" rel="noreferrer">
            {shortRange.source}
          </a>
        )}
      </div>
    </div>
  );
}

function formatAsOf(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
