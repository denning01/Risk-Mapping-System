"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type Map as MLMap, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FeatureCollection } from "geojson";
import type { Area, Origin, Route, Scenario, Shelter } from "@/lib/types";
import { RISK_COLORS, SHELTER_TYPE_LABELS } from "@/lib/types";

const VECTOR_STYLE = "https://tiles.openfreemap.org/styles/liberty";
const RASTER_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
      maxzoom: 19,
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

/**
 * M-15 basemaps. All keyless. Licences and attribution checked on each provider's own page (ROUND for M-15):
 * - Normal: OpenFreeMap Liberty (OSM data, ODbL; buildings drawn from z13, 3D extrusions from z14).
 * - Terrain: OpenTopoMap, CC-BY-SA, attribution as opentopomap.org/about asks.
 * - Satellite: EOxCloudless 2025 (Sentinel-2, about 10 m), CC BY-NC-SA 4.0 for non-commercial use, attribution as
 *   cloudless.eox.at/documentation/license requires. Esri World Imagery was not used: it is under the Esri Master
 *   License Agreement, not an open licence for keyless use outside ArcGIS.
 */
export type Basemap = "normal" | "terrain" | "satellite";
export const BASEMAP_LABELS: Record<Basemap, string> = { normal: "Normal", terrain: "Terrain", satellite: "Satellite" };
const rasterStyle = (id: string, tiles: string[], attribution: string, maxzoom: number): StyleSpecification => ({
  version: 8,
  sources: { [id]: { type: "raster", tiles, tileSize: 256, attribution, maxzoom } },
  layers: [{ id, type: "raster", source: id }],
});
const TERRAIN_STYLE = rasterStyle(
  "opentopomap",
  ["a", "b", "c"].map((s) => `https://${s}.tile.opentopomap.org/{z}/{x}/{y}.png`),
  'Map data: © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, SRTM | Map style: © <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)',
  17,
);
const SATELLITE_STYLE = rasterStyle(
  "eox-s2cloudless",
  ["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2025_3857/default/GoogleMapsCompatible/{z}/{y}/{x}.jpg"],
  '<a href="https://cloudless.eox.at">EOxCloudless</a> https://cloudless.eox.at by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2025), <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/">CC BY-NC-SA 4.0</a>',
  16,
);
/** Identify a loaded style from its sources (F14.3: report what loaded, not what was asked for). */
function styleIdentity(map: MLMap): { basemap: Basemap; style: string } | null {
  const src = map.getStyle()?.sources ?? {};
  if ("eox-s2cloudless" in src) return { basemap: "satellite", style: "eox-s2cloudless" };
  if ("opentopomap" in src) return { basemap: "terrain", style: "opentopomap" };
  if ("openmaptiles" in src) return { basemap: "normal", style: "vector" };
  if ("osm" in src) return { basemap: "normal", style: "osm-raster" };
  return null;
}
const RASTER_SOURCES: Partial<Record<Basemap, string>> = { terrain: "opentopomap", satellite: "eox-s2cloudless" };
/** Tile errors from the chosen raster basemap before it falls back to Normal (one bad tile is not a failure). */
const TILE_ERRORS_BEFORE_FALLBACK = 3;

export const ARRIVAL_COLORS = ["#7c3aed", "#2563eb", "#06b6d4", "#a5f3fc"];

/** Fill layers drawn from the flood source; exactly one is visible at a time. */
const FLOOD_LAYERS = ["flood-fill", "flood-arrival"] as const;
/** Layers that answer a click, so a tap on one never falls through to origin snapping. */
const INTERACTIVE_LAYERS = [...FLOOD_LAYERS, "shelters"];

const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

export interface Report {
  id: string;
  lon: number;
  lat: number;
}

interface Props {
  area: Area | null;
  scenario: Scenario | null;
  origins: Origin[];
  selectedOrigin: string | null;
  route: Route | null;
  showArrival: boolean;
  /** largest arrival_h in the current scenario, used to stretch the colour ramp */
  maxArrival: number;
  reportMode: boolean;
  reports: Report[];
  onPickOrigin: (id: string) => void;
  onReport: (lon: number, lat: number) => void;
}

/** What is drawn on the map now, exposed as data-* attributes so e2e can check it (the canvas is opaque to the DOM). */
interface Drawn {
  /** the basemap of the style that actually LOADED, identified from its sources (styleIdentity), not the switcher */
  basemap: Basemap;
  /** which style that is: "vector" (OpenFreeMap), "osm-raster" (fallback), "opentopomap", "eox-s2cloudless" */
  style: string;
  overlays: string;
  floodFeatures: number;
}

export default function FloodMap(props: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);
  const propsRef = useRef(props);
  const [styleReady, setStyleReady] = useState(0);
  const [basemapNote, setBasemapNote] = useState<string | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const [basemap, setBasemap] = useState<Basemap>("normal");
  const basemapRef = useRef<Basemap>("normal");
  const vectorFailedRef = useRef(false);
  const tileErrorsRef = useRef(0);
  /** set on the first style.load; after it, the startup fallback is off (F14.2) */
  const firstLoadedRef = useRef(false);
  const [drawn, setDrawn] = useState<Drawn | null>(null);

  useEffect(() => {
    propsRef.current = props;
  });

  // --- create the map once ---
  useEffect(() => {
    if (!containerRef.current) return;
    let map: MLMap;
    try {
      map = new maplibregl.Map({
        container: containerRef.current,
        style: VECTOR_STYLE,
        center: [36.85, -1.275],
        zoom: 11,
        maxZoom: 19,
        attributionControl: { compact: true },
      });
    } catch (err) {
      // No WebGL context: hardware acceleration off, a blocklisted driver, or a
      // locked-down browser. MapLibre draws everything through WebGL, so the
      // raster basemap is no help either. Fail soft and keep the rest of the
      // app alive, rather than throwing out of the effect and killing the tree.
      console.warn("[map] could not initialise:", err);
      // The map constructor *is* the external system this effect synchronises
      // with, and this is a one-time terminal failure, so there is nothing to
      // cascade. The lint rule cannot see that.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMapError(err instanceof Error ? err.message : "Failed to initialize WebGL");
      return;
    }
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");

    let usedFallback = false;
    const switchToFallback = () => {
      // F14.2: only for the FIRST style (OpenFreeMap failing at startup). After any style has loaded, isStyleLoaded()
      // is false whenever a switched-to style's tiles are still loading, so it cannot tell startup from a later switch.
      if (usedFallback || firstLoadedRef.current) return;
      usedFallback = true;
      vectorFailedRef.current = true;
      setBasemapNote("Using fallback basemap");
      map.setStyle(RASTER_STYLE);
    };
    const timer = window.setTimeout(switchToFallback, 8000);
    map.on("error", (e) => {
      const err = e.error as (Error & { type?: string }) | undefined;
      if (err?.type === "webglcontextcreationerror" || /WebGL/i.test(err?.message ?? "")) {
        // swapping the style cannot fix a missing WebGL context
        setMapError(err?.message || "Failed to initialize WebGL");
        return;
      }
      // style fetch failure before the first load -> raster fallback (never after: F14.2)
      if (!firstLoadedRef.current) switchToFallback();
      // M-15: the chosen Terrain / Satellite tiles keep failing -> back to Normal, with a note
      const cur = basemapRef.current;
      const sourceId = (e as { sourceId?: string }).sourceId;
      if (sourceId && sourceId === RASTER_SOURCES[cur] && ++tileErrorsRef.current >= TILE_ERRORS_BEFORE_FALLBACK) {
        tileErrorsRef.current = 0;
        basemapRef.current = "normal";
        setBasemap("normal");
        setBasemapNote(`${BASEMAP_LABELS[cur]} tiles unavailable: showing the Normal map`);
        map.setStyle(vectorFailedRef.current ? RASTER_STYLE : VECTOR_STYLE, { diff: false });
      }
      console.warn("[map]", err?.message);
    });

    map.on("style.load", () => {
      firstLoadedRef.current = true;
      window.clearTimeout(timer);
      addLayers(map);
      // M-15: redraw the current scenario, route and reports into the new style now, not on a later React pass, so a
      // basemap switch can never leave the overlays empty
      drawScenario(map, propsRef.current.scenario);
      drawRoute(map, propsRef.current.route);
      drawReports(map, propsRef.current.reports);
      setStyleReady((n) => n + 1);
    });
    // what is drawn, read back from the map once it is idle (all sources loaded, frame rendered)
    map.on("idle", () => {
      const overlays = ["flood-fill", "route-safe", "shelters"].filter((l) => map.getLayer(l)).join(",");
      const src = map.getSource("flood") as GeoJSONSource | undefined;
      const id = styleIdentity(map);
      if (!src || !id) return;
      void src.getData().then((d) => {
        const next = { ...id, overlays, floodFeatures: (d as FeatureCollection).features?.length ?? 0 };
        setDrawn((cur) =>
          cur && cur.basemap === next.basemap && cur.style === next.style && cur.overlays === next.overlays && cur.floodFeatures === next.floodFeatures
            ? cur
            : next,
        );
      });
    });

    const floodPopup = (e: maplibregl.MapLayerMouseEvent) => {
      if (propsRef.current.reportMode) return; // a tap is a report, not a query
      const f = e.features?.[0];
      if (!f) return;
      const p = f.properties as { risk: string; depth_m: number; arrival_h: number | null | string };
      const arrival = p.arrival_h === null || p.arrival_h === "null" ? "n/a" : `~${p.arrival_h} h`;
      new maplibregl.Popup({ closeButton: true, maxWidth: "240px" })
        .setLngLat(e.lngLat)
        .setHTML(
          `<div style="font:13px system-ui"><b style="text-transform:capitalize">${p.risk} risk</b><br/>Depth: ~${p.depth_m} m<br/>Water arrives: ${arrival}<br/><i style="color:#666">Scenario estimate, not a forecast</i></div>`,
        )
        .addTo(map);
    };
    // both fill layers share the popup: only one of them is visible at a time
    for (const layer of FLOOD_LAYERS) map.on("click", layer, floodPopup);
    map.on("click", "shelters", (e) => {
      if (propsRef.current.reportMode) return;
      const f = e.features?.[0];
      if (!f) return;
      const p = f.properties as { name: string; type: Shelter["type"]; safe: boolean | string; capacity: number | string | null };
      const safe = p.safe === true || p.safe === "true";
      const typeLabel = SHELTER_TYPE_LABELS[p.type] ?? p.type.replaceAll("_", " ");
      new maplibregl.Popup({ maxWidth: "240px" })
        .setLngLat(e.lngLat)
        .setHTML(
          `<div style="font:13px system-ui"><b>${p.name}</b><br/>${typeLabel}${p.capacity && p.capacity !== "null" ? ` · capacity ${p.capacity}` : ""}<br/><b style="color:${safe ? "#15803d" : "#6b7280"}">${safe ? "Safe in this scenario" : "Flooded in this scenario"}</b></div>`,
        )
        .addTo(map);
    });
    map.on("click", (e) => {
      const hits = map.queryRenderedFeatures(e.point, { layers: INTERACTIVE_LAYERS.filter((l) => map.getLayer(l)) });
      const { reportMode, origins, onPickOrigin, onReport } = propsRef.current;
      if (reportMode) {
        onReport(e.lngLat.lng, e.lngLat.lat);
        return;
      }
      if (hits.length) return;
      // snap to the nearest demo origin
      let best: { id: string; d: number } | null = null;
      for (const o of origins) {
        const d = (o.lon - e.lngLat.lng) ** 2 + (o.lat - e.lngLat.lat) ** 2;
        if (!best || d < best.d) best = { id: o.id, d };
      }
      if (best) onPickOrigin(best.id);
    });
    for (const layer of INTERACTIVE_LAYERS) {
      map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
    }

    // keep the canvas sized to its container (mobile bottom sheet opens/closes)
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      window.clearTimeout(timer);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // --- M-15: switch basemap. setStyle drops our sources and layers; style.load re-adds them and bumps styleReady, so
  // the data / route / arrival effects below run again and redraw the same scenario. Origin markers are DOM, unaffected.
  const chooseBasemap = (b: Basemap) => {
    const map = mapRef.current;
    if (!map || b === basemapRef.current) return;
    basemapRef.current = b;
    tileErrorsRef.current = 0;
    setBasemap(b);
    setBasemapNote(b === "normal" && vectorFailedRef.current ? "Using fallback basemap" : null);
    map.setStyle(b === "satellite" ? SATELLITE_STYLE : b === "terrain" ? TERRAIN_STYLE : vectorFailedRef.current ? RASTER_STYLE : VECTOR_STYLE, {
      diff: false,
    });
  };

  // --- fly to the area ---
  const areaId = props.area?.id;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !props.area) return;
    const [w, s, e, n] = props.area.bbox;
    map.resize();
    map.fitBounds(
      [
        [w, s],
        [e, n],
      ],
      { padding: 20, duration: 1500 },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [areaId]);

  // --- scenario data ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReady) return;
    drawScenario(map, props.scenario);
  }, [props.scenario, styleReady]);

  // --- route ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReady) return;
    drawRoute(map, props.route);
  }, [props.route, styleReady]);

  // --- arrival layer toggle ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReady || !map.getLayer("flood-arrival")) return;
    map.setLayoutProperty("flood-arrival", "visibility", props.showArrival ? "visible" : "none");
    map.setLayoutProperty("flood-fill", "visibility", props.showArrival ? "none" : "visible");
    const m = Math.max(props.maxArrival, 1);
    map.setPaintProperty("flood-arrival", "fill-color", [
      "interpolate",
      ["linear"],
      ["coalesce", ["get", "arrival_h"], 0],
      0, ARRIVAL_COLORS[0],
      m / 3, ARRIVAL_COLORS[1],
      (2 * m) / 3, ARRIVAL_COLORS[2],
      m, ARRIVAL_COLORS[3],
    ]);
  }, [props.showArrival, props.maxArrival, styleReady]);

  // --- user reports (mock) ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReady) return;
    drawReports(map, props.reports);
  }, [props.reports, styleReady]);

  // --- origin markers (DOM markers so labels need no font glyphs) ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = props.origins.map((o) => {
      const el = document.createElement("button");
      const active = o.id === props.selectedOrigin;
      el.className = `origin-marker${active ? " active" : ""}`;
      el.type = "button";
      el.title = `Start from ${o.name}`;
      el.innerHTML = `<span class="dot"></span><span class="label">${o.name}</span>`;
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        propsRef.current.onPickOrigin(o.id);
      });
      return new maplibregl.Marker({ element: el, anchor: "left", offset: [-7, 0] }).setLngLat([o.lon, o.lat]).addTo(map);
    });
  }, [props.origins, props.selectedOrigin]);

  return (
    <div className="absolute inset-0">
      {/* maplibre's CSS forces position:relative on the container, so size it with h-full/w-full */}
      <div
        ref={containerRef}
        className={`h-full w-full ${props.reportMode ? "report-mode" : ""}`}
        data-basemap={drawn?.basemap}
        data-style={drawn?.style}
        data-overlays={drawn?.overlays}
        data-flood-features={drawn?.floodFeatures}
      />
      {!mapError && (
        <div className="absolute left-12 top-2 flex rounded-lg bg-white/95 p-0.5 shadow" role="radiogroup" aria-label="Basemap">
          {(Object.keys(BASEMAP_LABELS) as Basemap[]).map((b) => (
            <button
              key={b}
              role="radio"
              aria-checked={basemap === b}
              onClick={() => chooseBasemap(b)}
              className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${basemap === b ? "bg-zinc-900 text-white" : "text-zinc-700"}`}
            >
              {BASEMAP_LABELS[b]}
            </button>
          ))}
        </div>
      )}
      {mapError && (
        <div className="absolute inset-0 grid place-items-center bg-zinc-100 p-4">
          <div className="max-w-sm rounded-xl border border-zinc-200 bg-white p-4 text-center shadow-sm">
            <h2 className="text-sm font-bold text-zinc-900">Map needs WebGL</h2>
            <p className="mt-1 text-xs text-zinc-600">
              This browser could not create a WebGL context, so the map cannot be drawn. Everything else on this page still works: the panel shows who is
              exposed, where to move and which roads are likely to be cut.
            </p>
            <p className="mt-2 text-[11px] text-zinc-500">Turn on hardware acceleration (or WebGL) in your browser settings, then reload.</p>
          </div>
        </div>
      )}
      {basemapNote && !mapError && (
        <div className="absolute bottom-2 left-2 rounded bg-white/90 px-2 py-1 text-[11px] text-zinc-600 shadow">{basemapNote}</div>
      )}
    </div>
  );
}

function setData(map: MLMap, id: string, data: FeatureCollection) {
  const src = map.getSource(id) as GeoJSONSource | undefined;
  src?.setData(data);
}

function drawScenario(map: MLMap, sc: Scenario | null) {
  setData(map, "flood", sc ? (sc.flood as FeatureCollection) : EMPTY);
  setData(map, "shelters", {
    type: "FeatureCollection",
    features: (sc?.shelters ?? []).map((s) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [s.lon, s.lat] },
      properties: { ...s },
    })),
  });
}

function drawRoute(map: MLMap, r: Route | null) {
  const line = (g: { coordinates: number[][] } | undefined): FeatureCollection =>
    g ? { type: "FeatureCollection", features: [{ type: "Feature", geometry: { type: "LineString", coordinates: g.coordinates }, properties: {} }] } : EMPTY;
  const showBaseline = r?.baseline && r.baseline.minutes !== r.safe.minutes;
  setData(map, "route-baseline", line(showBaseline ? r!.baseline!.geometry : undefined));
  setData(map, "route-safe", line(r?.safe.geometry));
}

function drawReports(map: MLMap, reports: Report[]) {
  setData(map, "reports", {
    type: "FeatureCollection",
    features: reports.map((r) => ({ type: "Feature", geometry: { type: "Point", coordinates: [r.lon, r.lat] }, properties: { id: r.id } })),
  });
}

function addLayers(map: MLMap) {
  for (const id of ["flood", "shelters", "route-baseline", "route-safe", "reports"]) {
    if (!map.getSource(id)) map.addSource(id, { type: "geojson", data: EMPTY });
  }
  map.addLayer({
    id: "flood-fill",
    type: "fill",
    source: "flood",
    paint: {
      "fill-color": ["match", ["get", "risk"], "high", RISK_COLORS.high, "medium", RISK_COLORS.medium, RISK_COLORS.low],
      "fill-opacity": 0.55,
      "fill-antialias": false, // avoids hairline seams between raster-like grid cells
    },
  });
  map.addLayer({
    id: "flood-arrival",
    type: "fill",
    source: "flood",
    layout: { visibility: "none" },
    paint: {
      "fill-color": [
        "interpolate",
        ["linear"],
        ["coalesce", ["get", "arrival_h"], 0],
        0, "#7c3aed",
        3, "#2563eb",
        8, "#06b6d4",
        16, "#a5f3fc",
      ],
      "fill-opacity": 0.6,
      "fill-antialias": false,
    },
  });
  map.addLayer({
    id: "route-baseline",
    type: "line",
    source: "route-baseline",
    layout: { "line-cap": "round" },
    paint: { "line-color": "#6b7280", "line-width": 4, "line-dasharray": [1.5, 1.5] },
  });
  map.addLayer({
    id: "route-safe-casing",
    type: "line",
    source: "route-safe",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#ffffff", "line-width": 8 },
  });
  map.addLayer({
    id: "route-safe",
    type: "line",
    source: "route-safe",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#2563eb", "line-width": 5 },
  });
  map.addLayer({
    id: "shelters",
    type: "circle",
    source: "shelters",
    paint: {
      "circle-radius": 8,
      "circle-color": ["case", ["get", "safe"], "#16a34a", "#9ca3af"],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2.5,
    },
  });
  map.addLayer({
    id: "reports",
    type: "circle",
    source: "reports",
    paint: { "circle-radius": 9, "circle-color": "#dc2626", "circle-stroke-color": "#fff", "circle-stroke-width": 3 },
  });
}
