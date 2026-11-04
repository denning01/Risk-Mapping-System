"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type Map as MLMap, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FeatureCollection } from "geojson";
import type { Area, Origin, Route, Scenario } from "@/lib/types";
import { RISK_COLORS } from "@/lib/types";

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

export default function FloodMap(props: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);
  const propsRef = useRef(props);
  const [styleReady, setStyleReady] = useState(0);
  const [basemapNote, setBasemapNote] = useState<string | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);

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
      if (usedFallback || map.isStyleLoaded()) return;
      usedFallback = true;
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
      // style fetch failure before first load -> raster fallback
      if (!map.isStyleLoaded()) switchToFallback();
      console.warn("[map]", err?.message);
    });

    map.on("style.load", () => {
      window.clearTimeout(timer);
      addLayers(map);
      setStyleReady((n) => n + 1);
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
      const p = f.properties as { name: string; type: string; safe: boolean | string; capacity: number | string | null };
      const safe = p.safe === true || p.safe === "true";
      new maplibregl.Popup({ maxWidth: "240px" })
        .setLngLat(e.lngLat)
        .setHTML(
          `<div style="font:13px system-ui"><b>${p.name}</b><br/>${p.type.replace("_", " ")}${p.capacity && p.capacity !== "null" ? ` · capacity ${p.capacity}` : ""}<br/><b style="color:${safe ? "#15803d" : "#6b7280"}">${safe ? "Safe in this scenario" : "Flooded in this scenario"}</b></div>`,
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
    const sc = props.scenario;
    setData(map, "flood", sc ? (sc.flood as FeatureCollection) : EMPTY);
    setData(map, "shelters", {
      type: "FeatureCollection",
      features: (sc?.shelters ?? []).map((s) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [s.lon, s.lat] },
        properties: { ...s },
      })),
    });
  }, [props.scenario, styleReady]);

  // --- route ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReady) return;
    const r = props.route;
    const line = (g: { coordinates: number[][] } | undefined): FeatureCollection =>
      g ? { type: "FeatureCollection", features: [{ type: "Feature", geometry: { type: "LineString", coordinates: g.coordinates }, properties: {} }] } : EMPTY;
    const showBaseline = r?.baseline && r.baseline.minutes !== r.safe.minutes;
    setData(map, "route-baseline", line(showBaseline ? r!.baseline!.geometry : undefined));
    setData(map, "route-safe", line(r?.safe.geometry));
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
    setData(map, "reports", {
      type: "FeatureCollection",
      features: props.reports.map((r) => ({ type: "Feature", geometry: { type: "Point", coordinates: [r.lon, r.lat] }, properties: { id: r.id } })),
    });
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
      <div ref={containerRef} className={`h-full w-full ${props.reportMode ? "report-mode" : ""}`} />
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
