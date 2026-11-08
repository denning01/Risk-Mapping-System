"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { RAIN_VALUES } from "@/lib/schema";
import { loadAreas, loadCrops, loadForecast, loadMeta, loadOrigins, loadPopulation, loadScenario, preloadArea } from "@/lib/data";
import { riskAt, riskNear } from "@/lib/geo";
import { clientAnswers, loadGraph, relocationTargets, routeBetween, snapStart, type Answer, type RouteOk, type TargetKind, type TripResult } from "@/lib/routing";
import { floodNextTo } from "@/lib/tripAnalysis";
import type { Area, AreaId, CropRule, Enso, Forecast, Meta, Origin, Population, Rain, Route, Scenario } from "@/lib/types";
import {
  AdvisoryPanel,
  AlertPreview,
  ExposurePanel,
  ForecastBanner,
  Legend,
  LimitationsContent,
  RoadsPanel,
  SafePlacesPanel,
  ScenarioControls,
} from "./panels";
import { Badge, Card, Modal } from "./ui";
import { WeatherPanel, type WeatherPoint } from "./weather";
import { TripPanel, type TripDestOption, type TripView } from "./trip";
import type { Report } from "./FloodMap";

const FloodMap = dynamic(() => import("./FloodMap"), {
  ssr: false,
  loading: () => <div className="absolute inset-0 animate-pulse bg-sky-100" />,
});

const USER_TYPE_LABELS: Record<string, string> = {
  commuter: "Commuter",
  informal_settlement_resident: "Resident",
  trader: "Trader",
  settler: "Settler",
  farmer: "Farmer",
};

type PanelKey = "safe" | "roads" | "advisory";

/** M-14: a start point from a map tap or the device's location. */
type TapPoint = { lon: number; lat: number; source: "tap" | "gps" };
/** M-14: the outcome for one (area, scenario, point); "wet" = the point is inside the scenario's flood extent;
 * "far" = no mapped road or path within MAX_TAP_SNAP_M; "graph" = graph.json could not be loaded. */
type TapOutcome = {
  at: string;
  /** RULING R20: a free tap gets client_answers() with no user type: "shelter" and, where relocation targets exist, "relocation" */
  result: { ok: true; answers: Partial<Record<TargetKind, Answer>> } | { ok: false; reason: "wet" | "far" | "graph" | "no_relocation" | Exclude<Answer, { ok: true }>["reason"] };
};
/** which answer is drawn after a tap: the kind, and the fastest (primary) or the safer route */
type TapChoice = { kind: TargetKind; safer: boolean };
/** M-16: a trip destination; "map" = tapped on the map */
type TripDest = { id: string; name: string; lon: number; lat: number; targetId?: string };
type TripOutcome = { at: string; result: TripResult | { ok: false; reason: "wet_start" | "wet_dest" | "graph" } };
/** CHOICE (M-14): a tap more than this far from the nearest walk node gets no route (the straight snap leg would be
 * unchecked for water over a long distance). Same bound as the shelters' max_dest_snap_m in graph.json. */
const MAX_TAP_SNAP_M = 500;
const NO_ROUTE_WHY: Record<string, string> = {
  wet: "This starting point is inside the flood extent in this scenario, so no route leaves it on dry ground.",
  cut_off: "The nearest path to this point is flooded in this scenario, so no route leaves it on dry ground.",
  unreachable: "No safe place can be reached on dry paths from this point in this scenario.",
  no_usable_shelter: "No safe place can be reached on dry paths from this point in this scenario.",
};
const EMPHASIS: Record<string, PanelKey> = {
  commuter: "safe",
  informal_settlement_resident: "safe",
  settler: "safe",
  farmer: "advisory",
  trader: "roads",
};

export default function FloodApp() {
  const [areas, setAreas] = useState<Area[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [crops, setCrops] = useState<CropRule[]>([]);
  const [areaId, setAreaId] = useState<AreaId>("nyando");
  const [rain, setRain] = useState<Rain>(150);
  const [enso, setEnso] = useState<Enso>("normal");
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [origins, setOrigins] = useState<Origin[]>([]);
  const [population, setPopulation] = useState<Population | null>(null);
  // Tagged with the area it belongs to, so switching area never paints Nyando's
  // outlook over Nairobi for the frame before the new file resolves.
  const [forecast, setForecast] = useState<{ area: AreaId; data: Forecast | null } | null>(null);
  const [originId, setOriginId] = useState<string | null>(null);
  const [userType, setUserType] = useState<string>("settler");
  const [animating, setAnimating] = useState(false);
  const [showArrival, setShowArrival] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"floods" | "drought">("floods");
  const [sheetOpen, setSheetOpen] = useState(true);
  const [reportMode, setReportMode] = useState(false);
  const [reports, setReports] = useState<Report[]>([]);
  const [features, setFeatures] = useState({ ai: false, sms: false });
  // M-14: route from a tapped / located point
  const [tap, setTap] = useState<TapPoint | null>(null);
  const [tapOutcome, setTapOutcome] = useState<TapOutcome | null>(null);
  const [locateNote, setLocateNote] = useState<string | null>(null);
  const [tapChoice, setTapChoice] = useState<TapChoice | null>(null);
  // M-16: from -> to
  const [tripDest, setTripDest] = useState<TripDest | null>(null);
  const [pickingDest, setPickingDest] = useState(false);
  const [tripChoice, setTripChoice] = useState(0);
  const [tripOutcome, setTripOutcome] = useState<TripOutcome | null>(null);
  /** which area/scenario `scenario` holds (it keeps the previous one while the next loads) */
  const [scenarioKey, setScenarioKey] = useState<string | null>(null);
  const preloaded = useRef(new Set<AreaId>());

  const area = areas.find((a) => a.id === areaId) ?? null;

  // --- static files ---
  useEffect(() => {
    Promise.all([loadAreas(), loadMeta(), loadCrops()])
      .then(([a, m, c]) => {
        setAreas(a);
        setMeta(m);
        setCrops(c);
      })
      .catch((e: Error) => setError(e.message));
    fetch("/api/config")
      .then((r) => r.json())
      .then((j: { ai: boolean; sms: boolean }) => setFeatures(j))
      .catch(() => {});
  }, []);

  // --- per-area files ---
  useEffect(() => {
    let alive = true;
    loadOrigins(areaId)
      .then((o) => alive && setOrigins(o))
      .catch((e: Error) => alive && setError(e.message));
    loadPopulation(areaId).then((p) => alive && setPopulation(p));
    loadForecast(areaId).then((f) => alive && setForecast({ area: areaId, data: f }));
    return () => {
      alive = false;
    };
  }, [areaId]);

  // --- scenario (keeps showing the previous one while loading, so the map is never blank) ---
  useEffect(() => {
    let alive = true;
    loadScenario(areaId, rain, enso)
      .then((s) => {
        if (!alive) return;
        setScenario(s);
        setScenarioKey(`${areaId}/${rain}_${enso}`);
        setError(null);
        // Warm the other 19 scenarios only once the visible one has arrived, so
        // 80 preload requests never queue ahead of it on a weak connection.
        if (!preloaded.current.has(areaId)) {
          preloaded.current.add(areaId);
          preloadArea(areaId);
        }
      })
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [areaId, rain, enso]);

  // --- animate: step 50 -> 250 mm ---
  useEffect(() => {
    if (!animating) return;
    let i = 0;
    const id = window.setInterval(() => {
      i += 1;
      if (i >= RAIN_VALUES.length) {
        setAnimating(false);
        return;
      }
      setRain(RAIN_VALUES[i]);
    }, 1500);
    return () => window.clearInterval(id);
  }, [animating]);

  const switchArea = useCallback(
    (id: AreaId) => {
      setAreaId(id);
      setOriginId(null);
      setTap(null);
      setLocateNote(null);
      setTripDest(null);
      setPickingDest(false);
      setReports([]);
      const a = areas.find((x) => x.id === id);
      if (a) setUserType(a.user_types[0]);
    },
    [areas],
  );

  const pickOrigin = useCallback(
    (id: string) => {
      if (id === "tap") return; // the tapped point's own entry in the list
      setOriginId(id);
      setTap(null);
      setLocateNote(null);
      setSheetOpen(true);
      const o = origins.find((x) => x.id === id);
      if (o) setUserType(o.user_type);
    },
    [origins],
  );

  const pickUserType = (t: string) => {
    setUserType(t);
    const o = origins.find((x) => x.user_type === t);
    if (o) {
      setOriginId(o.id);
      setTap(null);
    }
  };

  // --- M-14: route from a tapped / located point, in the browser, on graph.json for the scenario on screen ---
  const tapAt = tap && scenarioKey?.startsWith(`${areaId}/`) ? `${scenarioKey}@${tap.lon},${tap.lat}` : null;
  useEffect(() => {
    if (!tap || !tapAt || !scenario) return;
    let alive = true;
    const key = tapAt.split("/")[1].split("@")[0];
    loadGraph(areaId)
      .then((P) => {
        let result: TapOutcome["result"];
        if (riskAt(scenario.flood, tap.lon, tap.lat)) result = { ok: false, reason: "wet" };
        // a rural area's safe places are its relocation sites: never route there to OSM shelters alone (operator ruling)
        else if (area?.type === "rural" && relocationTargets(P.g) === 0) result = { ok: false, reason: "no_relocation" };
        else if (snapStart(P, tap.lon, tap.lat).m > MAX_TAP_SNAP_M) result = { ok: false, reason: "far" };
        else {
          const answers = clientAnswers(P, key, tap.lon, tap.lat);
          const ok = Object.values(answers).some((a) => a.ok);
          const first = Object.values(answers).find((a) => !a.ok);
          result = ok ? { ok: true, answers } : { ok: false, reason: first && !first.ok ? first.reason : "unreachable" };
        }
        if (alive) setTapOutcome({ at: tapAt, result });
      })
      .catch((e: Error) => {
        console.warn("[route]", e.message);
        if (alive) setTapOutcome({ at: tapAt, result: { ok: false, reason: "graph" } });
      });
    return () => {
      alive = false;
    };
  }, [tap, tapAt, scenario, areaId, area?.type]);
  const tapResult = tapOutcome && tapOutcome.at === tapAt ? tapOutcome.result : null;
  // the drawn answer: the user's choice, else the nearest safe shelter (the default), else high ground
  const tapRouteOk = useMemo<RouteOk | null>(() => {
    if (!tapResult?.ok) return null;
    const A = tapResult.answers;
    const pick = (c: TapChoice) => {
      const a = A[c.kind];
      return a?.ok ? (c.safer && a.safer ? a.safer : a.primary) : null;
    };
    return (tapChoice && pick(tapChoice)) || pick({ kind: "shelter", safer: false }) || pick({ kind: "relocation", safer: false });
  }, [tapResult, tapChoice]);
  const tapOptions = useMemo(() => {
    if (!tapResult?.ok) return [];
    const out: { id: string; label: string; active: boolean }[] = [];
    for (const kind of ["shelter", "relocation"] as const) {
      const a = tapResult.answers[kind];
      if (!a?.ok) continue;
      const what = kind === "shelter" ? "Nearest safe shelter" : "Nearest high ground";
      out.push({ id: `${kind}:primary`, label: `${what}: ${a.primary.shelter.name}, ${a.primary.minutes} min (fastest)`, active: tapRouteOk === a.primary });
      if (a.safer)
        out.push({
          id: `${kind}:safer`,
          label: `${what}, safer way${a.safer.shelter.id !== a.primary.shelter.id ? ` (${a.safer.shelter.name})` : ""}: ${a.safer.minutes} min, +${a.safer.extraMin} min, fewer paths next to water`,
          active: tapRouteOk === a.safer,
        });
    }
    return out;
  }, [tapResult, tapRouteOk]);
  const tapOrigin = useMemo<Origin | null>(
    () => (tap ? { id: "tap", name: tap.source === "gps" ? "My location" : "Tapped point", lon: tap.lon, lat: tap.lat, user_type: userType } : null),
    [tap, userType],
  );
  const tapPoint = useMemo(() => (tapOrigin ? { lon: tapOrigin.lon, lat: tapOrigin.lat, label: tapOrigin.name } : null), [tapOrigin]);
  const tapRoute = useMemo<Route | null>(() => {
    if (!tapRouteOk) return null;
    return {
      origin_id: "tap",
      kind: tapRouteOk.shelter.kind === "relocation" ? "relocation" : "to_shelter",
      shelter_id: tapRouteOk.shelter.id,
      destination_name: tapRouteOk.shelter.name,
      baseline: null,
      safe: { geometry: { type: "LineString", coordinates: tapRouteOk.coords }, minutes: tapRouteOk.minutes },
      avoided: [],
    };
  }, [tapRouteOk]);
  const tapPanel = tap
    ? {
        pending: !tapResult,
        noRouteWhy: tapResult && !tapResult.ok ? (NO_ROUTE_WHY[tapResult.reason] ?? null) : null,
        note:
          tapResult && !tapResult.ok && tapResult.reason === "far"
            ? `This point is more than ${MAX_TAP_SNAP_M} m from any mapped road or path. Tap closer to one.`
            : tapResult && !tapResult.ok && tapResult.reason === "no_relocation"
              ? `Routing from any point in ${area?.name ?? "this area"} is not ready yet: it needs the ranked relocation sites (high ground), which are coming. Choose a starting point from the list to see its relocation route.`
              : tapResult && !tapResult.ok && tapResult.reason === "graph"
              ? "The road network could not be loaded, so routes from a tapped point are unavailable. The preset starting points still work."
              : null,
        options: tapOptions.length > 1 ? tapOptions : [],
      }
    : null;

  const onTap = useCallback((lon: number, lat: number) => {
    const p = { lon: Math.round(lon * 1e6) / 1e6, lat: Math.round(lat * 1e6) / 1e6 };
    setSheetOpen(true);
    if (pickingDest) {
      // M-16: this tap sets the trip's destination, not a new start
      setTripDest({ id: "map", name: "Point on the map", ...p });
      setTripChoice(0);
      setPickingDest(false);
      return;
    }
    setTap({ ...p, source: "tap" });
    setTapChoice(null);
    setOriginId(null);
    setLocateNote(null);
  }, [pickingDest]); // FloodMap reads onTap through its props ref, so a new identity is fine
  const locate = useCallback(() => {
    if (!area) return;
    if (!("geolocation" in navigator)) {
      setLocateNote("This browser cannot share its location. Tap the map instead.");
      return;
    }
    setLocateNote("Finding your location…");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { longitude: lon, latitude: lat } = pos.coords;
        const [w, s, e, n] = area.bbox;
        if (lon < w || lon > e || lat < s || lat > n) {
          setLocateNote(`Your location (${lat.toFixed(4)}, ${lon.toFixed(4)}) is outside ${area.name}. Tap the map instead.`);
          return;
        }
        setLocateNote(null);
        setOriginId(null);
        setTapChoice(null);
        setTap({ lon: Math.round(lon * 1e6) / 1e6, lat: Math.round(lat * 1e6) / 1e6, source: "gps" });
      },
      (err) =>
        setLocateNote(
          err.code === err.PERMISSION_DENIED
            ? "Location permission denied. Tap the map to choose a starting point instead."
            : "Your location is unavailable right now. Tap the map instead.",
        ),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  }, [area]);

  const origin = tapOrigin ?? origins.find((o) => o.id === originId) ?? null;
  const publishedRoute = useMemo(() => scenario?.routes.find((r) => r.origin_id === originId) ?? null, [scenario, originId]);
  const route = tap ? tapRoute : publishedRoute;

  // --- M-16: from the current start (tap, location or preset) to a chosen destination ---
  const tripAt = origin && tripDest && scenarioKey?.startsWith(`${areaId}/`) ? `${scenarioKey}@${origin.lon},${origin.lat}>${tripDest.lon},${tripDest.lat}:${tripDest.targetId ?? ""}` : null;
  useEffect(() => {
    if (!origin || !tripDest || !tripAt || !scenario) return;
    let alive = true;
    const key = tripAt.split("/")[1].split("@")[0];
    loadGraph(areaId)
      .then((P) => {
        let result: TripOutcome["result"];
        if (riskAt(scenario.flood, origin.lon, origin.lat)) result = { ok: false, reason: "wet_start" };
        else if (!tripDest.targetId && riskAt(scenario.flood, tripDest.lon, tripDest.lat)) result = { ok: false, reason: "wet_dest" };
        else result = routeBetween(P, key, origin, tripDest);
        if (alive) setTripOutcome({ at: tripAt, result });
      })
      .catch((e: Error) => {
        console.warn("[trip]", e.message);
        if (alive) setTripOutcome({ at: tripAt, result: { ok: false, reason: "graph" } });
      });
    return () => {
      alive = false;
    };
  }, [origin, tripDest, tripAt, scenario, areaId]);
  const tripResult = tripOutcome && tripOutcome.at === tripAt ? tripOutcome.result : null;
  const tripView = useMemo<TripView>(() => {
    if (!tripDest) return { state: "idle" };
    if (!tripResult) return { state: tripAt ? "pending" : "idle" };
    if (!tripResult.ok) return { state: "refused", reason: tripResult.reason };
    return { state: "ok", alts: tripResult.alts.map((a) => ({ ...a, flood: scenario ? floodNextTo(scenario.flood, a.coords) : null })) };
  }, [tripDest, tripResult, tripAt, scenario]);
  const tripPick = tripView.state === "ok" ? Math.min(tripChoice, tripView.alts.length - 1) : 0;
  const tripRoute = useMemo<Route | null>(() => {
    if (tripView.state !== "ok" || !tripDest) return null;
    const a = tripView.alts[tripPick];
    return {
      origin_id: "trip",
      kind: "to_shelter",
      shelter_id: null,
      destination_name: tripDest.name,
      baseline: null,
      safe: { geometry: { type: "LineString", coordinates: a.coords }, minutes: a.minutes },
      avoided: [],
    };
  }, [tripView, tripPick, tripDest]);
  const tripAlts = useMemo(() => (tripView.state === "ok" ? tripView.alts.filter((_, i) => i !== tripPick).map((a) => a.coords) : []), [tripView, tripPick]);
  const tripOptions = useMemo<TripDestOption[]>(
    () => [
      ...origins.map((o) => ({ id: `o:${o.id}`, name: o.name, lon: o.lon, lat: o.lat, group: "Places" as const })),
      ...(scenario?.shelters ?? [])
        .filter((s) => s.safe)
        .map((s) => ({ id: `s:${s.id}`, name: s.name, lon: s.lon, lat: s.lat, targetId: s.id, group: "Safe places" as const })),
    ],
    [origins, scenario],
  );
  const riskHere = useMemo(
    () => (scenario && origin ? riskNear(scenario.flood, origin.lon, origin.lat, area?.type === "urban" ? 0.004 : 0.015) : null),
    [scenario, origin, area],
  );
  // M-13: live weather at the start point, and at the route's end once a route exists (the shelter's point, or the
  // route line's last vertex for a commute).
  const weatherHere = useMemo<WeatherPoint | null>(() => (origin ? { label: origin.name, lon: origin.lon, lat: origin.lat } : null), [origin]);
  const weatherDest = useMemo<WeatherPoint | null>(() => {
    if (tripDest && tripRoute) return { label: tripDest.name, lon: tripDest.lon, lat: tripDest.lat };
    if (!route) return null;
    const s = route.shelter_id ? scenario?.shelters.find((x) => x.id === route.shelter_id) : undefined;
    const end = route.safe.geometry.coordinates[route.safe.geometry.coordinates.length - 1];
    const [lon, lat] = s ? [s.lon, s.lat] : [end[0], end[1]];
    return { label: route.destination_name, lon, lat };
  }, [route, scenario, tripDest, tripRoute]);
  const hasArrival = !!scenario?.flood.features.some((f) => f.properties.arrival_h !== null);
  // looped, not Math.max(...spread): a real raster-derived scenario can hold
  // tens of thousands of features, which would overflow the argument limit
  const maxArrival = useMemo(() => {
    let m = 0;
    for (const f of scenario?.flood.features ?? []) {
      const h = f.properties.arrival_h;
      if (h !== null && h > m) m = h;
    }
    return m;
  }, [scenario]);
  const emphasis = EMPHASIS[userType] ?? "safe";

  const panels: Record<PanelKey, ReactNode> = {
    safe: area && scenario && (
      <SafePlacesPanel
        key="safe"
        area={area}
        origins={tapOrigin ? [tapOrigin, ...origins] : origins}
        selectedOrigin={tap ? "tap" : originId}
        onOrigin={pickOrigin}
        route={route}
        shelters={scenario.shelters}
        highlight={emphasis === "safe"}
        tap={tapPanel}
        onTapOption={(id) => {
          const [kind, v] = id.split(":") as [TargetKind, string];
          setTapChoice({ kind, safer: v === "safer" });
        }}
        onLocate={locate}
        locateNote={locateNote}
      />
    ),
    roads: <RoadsPanel key="roads" exposure={scenario?.exposure ?? null} highlight={emphasis === "roads"} />,
    advisory:
      area?.type === "rural" && crops.length ? (
        <AdvisoryPanel key="advisory" crops={crops} enso={enso} highlight={emphasis === "advisory"} aiEnabled={features.ai} scenarioRain={rain} />
      ) : null,
  };
  const order: PanelKey[] = [emphasis, ...(["safe", "advisory", "roads"] as PanelKey[]).filter((k) => k !== emphasis)];

  return (
    <div className="flex h-dvh flex-col bg-zinc-100 text-zinc-900">
      {/* Header */}
      <header className="z-20 flex items-center gap-2 border-b border-zinc-200 bg-white px-2 py-1.5 shadow-sm sm:px-3 sm:py-2">
        <div className="mr-auto flex min-w-0 items-center gap-2">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-blue-600 text-lg text-white" aria-hidden>
            ≋
          </span>
          <div className="leading-tight">
            <h1 className="hidden text-sm font-bold sm:block sm:text-base">Flood Early Warning</h1>
            <p className="hidden text-[11px] text-zinc-500 sm:block">Impact-based: where water goes, who is exposed, where to move</p>
          </div>
          {meta?.mock && <Badge tone="amber">MOCK DATA</Badge>}
        </div>
        <div className="flex rounded-lg bg-zinc-100 p-0.5" role="tablist" aria-label="Area">
          {areas.map((a) => (
            <button
              key={a.id}
              role="tab"
              aria-selected={a.id === areaId}
              onClick={() => switchArea(a.id)}
              className={`rounded-md px-3 py-1 text-xs font-semibold sm:text-sm ${a.id === areaId ? "bg-white text-blue-700 shadow" : "text-zinc-600"}`}
            >
              <span className="sm:hidden">{a.name.split(/[ ,(]/)[0]}</span>
              <span className="hidden sm:inline">{a.name}</span>
            </button>
          ))}
        </div>
        <button onClick={() => setAboutOpen(true)} className="rounded-lg border border-zinc-300 px-2 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-50">
          <span className="sm:hidden" aria-label="About and limitations">ⓘ</span>
          <span className="hidden sm:inline">About &amp; limits</span>
        </button>
      </header>

      <div className="relative flex min-h-0 flex-1 flex-col md:flex-row">
        {/* Map */}
        <div className="relative min-h-0 flex-1">
          <FloodMap
            area={area}
            scenario={scenario}
            origins={origins}
            selectedOrigin={originId}
            route={tripRoute ?? route}
            altRoutes={tripAlts}
            destPoint={tripDest ? { lon: tripDest.lon, lat: tripDest.lat, label: tripDest.name } : null}
            scenarioKey={scenarioKey}
            showArrival={showArrival && hasArrival}
            maxArrival={maxArrival}
            reportMode={reportMode}
            reports={reports}
            onPickOrigin={pickOrigin}
            tapPoint={tapPoint}
            onTap={onTap}
            onReport={(lon, lat) => {
              setReports((r) => [...r, { id: `${Date.now()}`, lon, lat }]);
              setReportMode(false);
            }}
          />
          <div className="pointer-events-none absolute right-2 top-2 flex flex-col items-end gap-2">
            <Legend arrival={showArrival && hasArrival} maxArrival={maxArrival} />
            {hasArrival && (
              <button
                onClick={() => setShowArrival((v) => !v)}
                className="pointer-events-auto rounded-lg bg-white/95 px-2 py-1 text-[11px] font-semibold text-zinc-700 shadow"
              >
                {showArrival ? "Show risk" : "Show arrival time"}
              </button>
            )}
            <button
              onClick={() => setReportMode((v) => !v)}
              className={`pointer-events-auto rounded-lg px-2 py-1 text-[11px] font-semibold shadow ${reportMode ? "bg-red-600 text-white" : "bg-white/95 text-zinc-700"}`}
            >
              {reportMode ? "Tap the blocked spot…" : "Report blocked road (mock)"}
            </button>
          </div>
          {error && (
            <div className="absolute left-1/2 top-2 z-10 max-w-[90%] -translate-x-1/2 rounded-lg bg-red-600 px-3 py-2 text-xs text-white shadow">
              {error}
            </div>
          )}
          {!scenario && !error && (
            <div className="absolute left-1/2 top-2 -translate-x-1/2 rounded-lg bg-white px-3 py-1 text-xs shadow">Loading scenario…</div>
          )}
        </div>

        {/* Side panel (desktop) / bottom sheet (mobile) */}
        <aside
          className={`z-10 flex flex-col border-t border-zinc-200 bg-zinc-50 shadow-[0_-4px_12px_rgba(0,0,0,0.08)] transition-[max-height] md:max-h-none md:w-[380px] md:border-l md:border-t-0 md:shadow-none ${
            sheetOpen ? "max-h-[48dvh]" : "max-h-10"
          }`}
        >
          <button
            className="flex w-full items-center justify-center gap-2 py-2 text-xs font-semibold text-zinc-600 md:hidden"
            onClick={() => setSheetOpen((v) => !v)}
            aria-expanded={sheetOpen}
          >
            <span className="h-1 w-10 rounded bg-zinc-300" />
            {sheetOpen ? "Hide panel" : "Show panel"}
          </button>
          <div className="flex gap-1 px-3 pt-1 md:pt-3">
            {(["floods", "drought"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`rounded-md px-3 py-1 text-xs font-semibold ${tab === t ? "bg-zinc-900 text-white" : "bg-zinc-200 text-zinc-700"}`}
              >
                {t === "floods" ? "Floods" : "Drought (roadmap)"}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
            {tab === "drought" ? (
              <Card title="Drought module" right={<Badge>Roadmap</Badge>}>
                <p className="text-sm text-zinc-700">
                  Planned: vegetation stress from NDVI anomalies, CHIRPS rainfall deficit (SPI), and seasonal outlooks from ICPAC, aligned with NDMA drought
                  bulletins. Not part of this demo.
                </p>
              </Card>
            ) : (
              <>
                {area && (
                  <div className="flex flex-wrap items-center gap-1">
                    <span className="mr-1 text-[11px] font-medium text-zinc-500">I am a:</span>
                    {area.user_types.map((t) => (
                      <button
                        key={t}
                        onClick={() => pickUserType(t)}
                        className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${userType === t ? "bg-blue-600 text-white" : "bg-white text-zinc-700 ring-1 ring-zinc-300"}`}
                      >
                        {USER_TYPE_LABELS[t] ?? t}
                      </button>
                    ))}
                  </div>
                )}
                <ForecastBanner
                  forecast={forecast?.area === areaId ? forecast.data : null}
                  onUseScenario={(r, e) => {
                    setAnimating(false);
                    setRain(r);
                    setEnso(e);
                  }}
                />
                <ScenarioControls
                  rain={rain}
                  enso={enso}
                  animating={animating}
                  onRain={(r) => {
                    setAnimating(false);
                    setRain(r);
                  }}
                  onEnso={setEnso}
                  onAnimate={() => {
                    if (!animating) setRain(RAIN_VALUES[0]);
                    setAnimating((v) => !v);
                  }}
                />
                <ExposurePanel exposure={scenario?.exposure ?? null} population={population} />
                {order.map((k) => panels[k])}
                {area && scenario && (
                  <TripPanel
                    startName={origin?.name ?? null}
                    options={tripOptions}
                    destId={tripDest?.id ?? null}
                    destName={tripDest?.name ?? null}
                    picking={pickingDest}
                    onDest={(id) => {
                      const o = tripOptions.find((x) => x.id === id);
                      if (o) {
                        setTripDest({ id: o.id, name: o.name, lon: o.lon, lat: o.lat, targetId: o.targetId });
                        setTripChoice(0);
                        setPickingDest(false);
                      }
                    }}
                    onPickOnMap={() => setPickingDest((v) => !v)}
                    onClear={() => {
                      setTripDest(null);
                      setPickingDest(false);
                    }}
                    view={tripView}
                    choice={tripPick}
                    onChoice={setTripChoice}
                  />
                )}
                <WeatherPanel here={weatherHere} destination={weatherDest} />
                {area && scenario && (
                  <AlertPreview
                    area={area}
                    scenario={scenario}
                    rain={rain}
                    enso={enso}
                    origin={origin}
                    route={route}
                    riskHere={riskHere}
                    smsEnabled={features.sms}
                  />
                )}
                {reports.length > 0 && (
                  <Card title="Community reports" right={<Badge tone="amber">Mock</Badge>}>
                    <p className="text-sm text-zinc-700">
                      {reports.length} blocked road report{reports.length > 1 ? "s" : ""} on the map (red dots). In the full system these would be verified and
                      re-route people automatically.
                    </p>
                    <button onClick={() => setReports([])} className="mt-2 text-xs font-semibold text-blue-700">
                      Clear reports
                    </button>
                  </Card>
                )}
              </>
            )}
            <p className="pb-2 text-center text-[10px] text-zinc-400">Screening-level model · Not a forecast · Complements KMD and ICPAC warnings</p>
          </div>
        </aside>
      </div>

      <Modal open={aboutOpen} onClose={() => setAboutOpen(false)} title="About this prototype">
        <LimitationsContent meta={meta} />
      </Modal>
    </div>
  );
}
