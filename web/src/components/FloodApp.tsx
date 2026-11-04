"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { RAIN_VALUES } from "@/lib/schema";
import { loadAreas, loadCrops, loadMeta, loadOrigins, loadPopulation, loadScenario, preloadArea } from "@/lib/data";
import { riskNear } from "@/lib/geo";
import type { Area, AreaId, CropRule, Enso, Meta, Origin, Population, Rain, Scenario } from "@/lib/types";
import { AdvisoryPanel, AlertPreview, ExposurePanel, Legend, LimitationsContent, RoadsPanel, SafePlacesPanel, ScenarioControls } from "./panels";
import { Badge, Card, Modal } from "./ui";
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
      setReports([]);
      const a = areas.find((x) => x.id === id);
      if (a) setUserType(a.user_types[0]);
    },
    [areas],
  );

  const pickOrigin = useCallback(
    (id: string) => {
      setOriginId(id);
      setSheetOpen(true);
      const o = origins.find((x) => x.id === id);
      if (o) setUserType(o.user_type);
    },
    [origins],
  );

  const pickUserType = (t: string) => {
    setUserType(t);
    const o = origins.find((x) => x.user_type === t);
    if (o) setOriginId(o.id);
  };

  const origin = origins.find((o) => o.id === originId) ?? null;
  const route = useMemo(() => scenario?.routes.find((r) => r.origin_id === originId) ?? null, [scenario, originId]);
  const riskHere = useMemo(
    () => (scenario && origin ? riskNear(scenario.flood, origin.lon, origin.lat, area?.type === "urban" ? 0.004 : 0.015) : null),
    [scenario, origin, area],
  );
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
        origins={origins}
        selectedOrigin={originId}
        onOrigin={pickOrigin}
        route={route}
        shelters={scenario.shelters}
        highlight={emphasis === "safe"}
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
            route={route}
            showArrival={showArrival && hasArrival}
            maxArrival={maxArrival}
            reportMode={reportMode}
            reports={reports}
            onPickOrigin={pickOrigin}
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
        <LimitationsContent />
      </Modal>
    </div>
  );
}
