"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type Map as MLMap, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FeatureCollection } from "geojson";
import type { Area, Origin, Route, Scenario, Shelter } from "@/lib/types";
import { arrivalSentence } from "@/lib/arrival";
import { THREE_D_NOTE, TERRAIN_X, WATER_X } from "@/lib/threeD";
import { HEX_RES, hexFeatures, hexLines, type HexRow } from "@/lib/hex";
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
 *   M-18 (2026-11-08) re-checked on Esri's own pages: the item (arcgis.com/sharing/rest/content/items/
 *   10df2279f9684e4a9f6a7f08febac2a9) says "licensed under the Esri Master License Agreement"; the terms summary
 *   (esri.com/content/dam/arcgisonline/docs/tou_summary.pdf, 21 Apr 2025) says "Use with Esri software ... If you do
 *   not have Esri software, you must purchase an ArcGIS Online subscription"; the basemap service docs say "An ArcGIS
 *   Location Platform or ArcGIS Online account is required". Not clearly allowed keyless -> EOX stays.
 *   e2e/basemap-hosts.spec.ts fails if an Esri / ArcGIS tile host appears in web/src.
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

/**
 * M-17 · 3D view. Terrain from AWS Open Data "Terrain Tiles" (terrarium PNG, z0-15, keyless, CORS *). Licence:
 * registry.opendata.aws/terrain-tiles -> github.com/tilezen/joerd/blob/master/docs/attribution.md (SRTM and GMTED2010
 * public domain, ETOPO1 not under copyright; the tile headers name srtm/S02E036 for Nairobi, srtm/S01E034 + S02E034
 * for Nyando). Heights are exaggerated and the factors are printed on screen (THREE_D_NOTE).
 */
const DEM_SOURCE = "terrain-dem";
const DEM_TILES = ["https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png"];
const DEM_ATTRIBUTION =
  '<a href="https://registry.opendata.aws/terrain-tiles/">Terrain Tiles</a> (AWS Open Data): SRTM and GMTED2010 courtesy of the U.S. Geological Survey; ETOPO1 U.S. NOAA';
const THREE_D_PITCH = 60;
/** our building extrusions, added only when the style has none (Terrain / Satellite; Liberty has "building-3d") */
const BUILDINGS_SOURCE = "ofm-buildings";
const BUILDINGS_LAYER = "buildings-3d";

export const ARRIVAL_COLORS = ["#7c3aed", "#2563eb", "#06b6d4", "#a5f3fc"];

/** Fill layers drawn from the flood source; exactly one is visible at a time. */
const FLOOD_LAYERS = ["flood-fill", "flood-arrival"] as const;
/** Layers that answer a click with a popup. A tap on a shelter is only a query; a tap on the flood also starts a
 * route from there (M-14), which then reports "no safe route" (the start point is wet). */
const INTERACTIVE_LAYERS = [...FLOOD_LAYERS, "shelters", "hex-fill"];
/** M-19: layers whose order e2e checks (the hexagons must stay under the routes and shelters) */
const ORDER_LAYERS = ["flood-fill", "hex-fill", "route-alt", "route-safe", "shelters", "reports"];
export const HEX_NOTE = `Hexagons (H3 resolution ${HEX_RES}, about 0.12 km² each): colour = deepest water in the hexagon. Tap one for people, buildings and walking time.`;
const esc = (t: string) => t.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

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
  /** M-14: the start point the user tapped or located (null = a preset origin or none) */
  tapPoint: { lon: number; lat: number; label: string } | null;
  /** M-14: a tap on the map, outside a marker or shelter: route from this point */
  onTap: (lon: number, lat: number) => void;
  /** M-16: the other alternatives of a from -> to trip (the chosen one is `route`), drawn thin under it */
  altRoutes?: [number, number][][];
  /** M-16: the trip's destination */
  destPoint?: { lon: number; lat: number; label: string } | null;
  /** M-19: "area/rain_enso" of the scenario on screen, to fetch its .h3.json */
  scenarioKey?: string | null;
}

/** What is drawn on the map now, exposed as data-* attributes so e2e can check it (the canvas is opaque to the DOM). */
interface Drawn {
  /** the basemap of the style that actually LOADED, identified from its sources (styleIdentity), not the switcher */
  basemap: Basemap;
  /** which style that is: "vector" (OpenFreeMap), "osm-raster" (fallback), "opentopomap", "eox-s2cloudless" */
  style: string;
  overlays: string;
  floodFeatures: number;
  /** features in the shelters source, and how many of them are high_ground (Nyando's relocation sites) */
  shelters: number;
  highGround: number;
  /** vertices of the drawn safe route (0 = none) */
  routePoints: number;
  /** M-16: alternative route lines drawn besides the chosen one */
  altRoutes: number;
  /** M-17: "terrain-dem x1.5" when terrain is on, else "off" */
  terrain: string;
  /** M-17: true ground height (m, exaggeration divided out) at the map centre, or null without terrain */
  elevation: number | null;
  pitch: number;
  /** M-17: the 3D layers present: "flood-3d" and the building extrusion layer's id */
  layers3d: string;
  /** F20.1: the 3D layers' height expressions as the map holds them (JSON), so the stated factors are checkable */
  paint3d: string;
  /** M-19: hexagons in the hex source, and the drawing order of ORDER_LAYERS (bottom first) */
  hexes: number;
  layerOrder: string;
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
  /** F14.6: load the Normal map after startup; falls back to the raster if the vector style does not load */
  const setNormalRef = useRef<(() => void) | null>(null);
  const [drawn, setDrawn] = useState<Drawn | null>(null);
  /** M-14 test hook: the camera after each move ("lon,lat,zoom"), so e2e can turn a lon/lat into a pixel to tap */
  const [view, setView] = useState<string | null>(null);
  const tapMarkerRef = useRef<maplibregl.Marker | null>(null);
  const destMarkerRef = useRef<maplibregl.Marker | null>(null);
  /** M-17: 2D is the default */
  const [threeD, setThreeD] = useState(false);
  const threeDRef = useRef(false);
  /** M-19: the hexagon layer (off by default) and the rows last drawn, for a redraw after a basemap switch */
  const [showHex, setShowHex] = useState(false);
  const hexDataRef = useRef<FeatureCollection>(EMPTY);
  const [hexNote, setHexNote] = useState<string | null>(null);

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
    // F14.6: after startup, a setStyle(VECTOR_STYLE) whose style fails to fetch never fires style.load, so our layers
    // would never come back. Watch it until its style.load: a style-level error or 8 s without a load -> the raster.
    let vectorPending = false;
    let vectorTimer = 0;
    const failVector = () => {
      if (!vectorPending) return;
      vectorPending = false;
      window.clearTimeout(vectorTimer);
      vectorFailedRef.current = true;
      setBasemapNote("Using fallback basemap");
      map.setStyle(RASTER_STYLE, { diff: false });
    };
    setNormalRef.current = () => {
      if (vectorFailedRef.current) {
        map.setStyle(RASTER_STYLE, { diff: false });
        return;
      }
      vectorPending = true;
      window.clearTimeout(vectorTimer);
      vectorTimer = window.setTimeout(failVector, 8000);
      map.setStyle(VECTOR_STYLE, { diff: false });
    };
    map.on("error", (e) => {
      const err = e.error as (Error & { type?: string }) | undefined;
      if (err?.type === "webglcontextcreationerror" || /WebGL/i.test(err?.message ?? "")) {
        // swapping the style cannot fix a missing WebGL context
        setMapError(err?.message || "Failed to initialize WebGL");
        return;
      }
      // style fetch failure before the first load -> raster fallback (never after: F14.2)
      if (!firstLoadedRef.current) switchToFallback();
      const sourceId = (e as { sourceId?: string }).sourceId;
      // F14.6: the vector style itself failed after startup (an error with no source while it is pending)
      if (vectorPending && !sourceId) failVector();
      // M-15: the chosen Terrain / Satellite tiles keep failing -> back to Normal, with a note
      const cur = basemapRef.current;
      if (sourceId && sourceId === RASTER_SOURCES[cur] && ++tileErrorsRef.current >= TILE_ERRORS_BEFORE_FALLBACK) {
        tileErrorsRef.current = 0;
        basemapRef.current = "normal";
        setBasemap("normal");
        setBasemapNote(`${BASEMAP_LABELS[cur]} tiles unavailable: showing the Normal map`);
        setNormalRef.current?.();
      }
      console.warn("[map]", err?.message);
    });

    map.on("style.load", () => {
      firstLoadedRef.current = true;
      window.clearTimeout(timer);
      vectorPending = false;
      window.clearTimeout(vectorTimer);
      addLayers(map);
      // M-17: a basemap switch drops the terrain and the 3D layers; put them back if 3D is on
      apply3D(map, threeDRef.current, propsRef.current.showArrival);
      // M-15: redraw the current scenario, route and reports into the new style now, not on a later React pass, so a
      // basemap switch can never leave the overlays empty
      drawScenario(map, propsRef.current.scenario);
      drawRoute(map, propsRef.current.route);
      drawAlts(map, propsRef.current.altRoutes);
      drawReports(map, propsRef.current.reports);
      setData(map, "hex", hexDataRef.current);
      setStyleReady((n) => n + 1);
    });
    // what is drawn, read back from the map once it is idle (all sources loaded, frame rendered)
    map.on("idle", () => {
      const overlays = ["flood-fill", "route-safe", "shelters"].filter((l) => map.getLayer(l)).join(",");
      const src = map.getSource("flood") as GeoJSONSource | undefined;
      const id = styleIdentity(map);
      if (!src || !id) return;
      const read = (sid: string) =>
        (map.getSource(sid) as GeoJSONSource | undefined)?.getData().then((x) => x as FeatureCollection) ?? Promise.resolve(EMPTY);
      const order = (map.getStyle()?.layers ?? []).map((l) => l.id).filter((l) => ORDER_LAYERS.includes(l)).join(",");
      void Promise.all([src.getData(), read("shelters"), read("route-safe"), read("route-alt"), read("hex")]).then(([d, sh, rt, alt, hx]) => {
        const shelters = (sh.features ?? []) as { properties: { type?: string } | null }[];
        const line = rt.features?.[0]?.geometry;
        const terrain = map.getTerrain();
        const ex = terrain?.exaggeration ?? 1;
        const el = terrain ? map.queryTerrainElevation(map.getCenter()) : null;
        const next: Drawn = {
          ...id,
          overlays,
          floodFeatures: (d as FeatureCollection).features?.length ?? 0,
          shelters: shelters.length,
          highGround: shelters.filter((f) => f.properties?.type === "high_ground").length,
          routePoints: line?.type === "LineString" ? line.coordinates.length : 0,
          altRoutes: alt.features?.length ?? 0,
          terrain: terrain ? `${terrain.source} x${ex}` : "off",
          elevation: el === null ? null : Math.round(el / ex),
          pitch: Math.round(map.getPitch()),
          layers3d: ["flood-3d", BUILDINGS_LAYER, "building-3d"].filter((l) => map.getLayer(l)).join(","),
          paint3d: JSON.stringify(paint3d(map)),
          hexes: map.getLayoutProperty("hex-fill", "visibility") === "visible" ? (hx.features?.length ?? 0) : 0,
          layerOrder: order,
        };
        setDrawn((cur) => (cur && JSON.stringify(cur) === JSON.stringify(next) ? cur : next));
      });
    });

    const floodPopup = (e: maplibregl.MapLayerMouseEvent) => {
      if (propsRef.current.reportMode) return; // a tap is a report, not a query
      const f = e.features?.[0];
      if (!f) return;
      const p = f.properties as { risk: string; depth_m: number; arrival_h: number | null | string };
      // M-21: MapLibre hands properties back as numbers or strings; arrival_h is the FAST bound (M-20 ruling)
      const h = p.arrival_h === null || p.arrival_h === "null" ? null : Number(p.arrival_h);
      new maplibregl.Popup({ closeButton: true, maxWidth: "240px" })
        .setLngLat(e.lngLat)
        .setHTML(
          `<div style="font:13px system-ui"><b style="text-transform:capitalize">${p.risk} risk</b><br/>Depth: ~${p.depth_m} m<br/><span data-arrival>${arrivalSentence(h)}</span><br/><i style="color:#666">Scenario estimate, not a forecast</i></div>`,
        )
        .addTo(map);
    };
    // both fill layers share the popup: only one of them is visible at a time
    for (const layer of FLOOD_LAYERS) map.on("click", layer, floodPopup);
    // M-19: a hexagon's popup (the flood fill is hidden while hexagons show, so only one popup opens)
    map.on("click", "hex-fill", (e) => {
      if (propsRef.current.reportMode) return;
      const f = e.features?.[0];
      if (!f) return;
      const h3 = (f.properties as { h3: string }).h3;
      const row = (hexDataRef.current.features.find((x) => (x.properties as HexRow).h3 === h3)?.properties ?? null) as HexRow | null;
      if (!row) return;
      const names = new Map((propsRef.current.scenario?.shelters ?? []).map((s) => [s.id, s.name]));
      new maplibregl.Popup({ closeButton: true, maxWidth: "260px" })
        .setLngLat(e.lngLat)
        .setHTML(
          `<div data-hex-popup="${esc(h3)}" style="font:13px system-ui">${hexLines(row, names)
            .map((l, i) => (i === 0 ? `<b>${esc(l)}</b>` : `<div>${esc(l)}</div>`))
            .join("")}<i style="color:#666">Scenario estimate, not a forecast</i></div>`,
        )
        .addTo(map);
    });
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
      const { reportMode, onReport, onTap } = propsRef.current;
      if (reportMode) {
        onReport(e.lngLat.lng, e.lngLat.lat);
        return;
      }
      // a shelter tap is a query (its popup); anywhere else, the flood included, routes from the tapped point (M-14)
      if (map.getLayer("shelters") && map.queryRenderedFeatures(e.point, { layers: ["shelters"] }).length) return;
      onTap(e.lngLat.lng, e.lngLat.lat);
    });
    map.on("moveend", () => {
      const c = map.getCenter();
      setView(`${c.lng},${c.lat},${map.getZoom()}`);
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
      window.clearTimeout(vectorTimer);
      setNormalRef.current = null;
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
    if (b === "normal") setNormalRef.current?.();
    else map.setStyle(b === "satellite" ? SATELLITE_STYLE : TERRAIN_STYLE, { diff: false });
  };

  // --- M-17: 3D on / off. Terrain + extrusions, and the camera tilts; off restores the flat, north-up 2D map. ---
  const toggle3D = () => {
    const map = mapRef.current;
    if (!map) return;
    const on = !threeDRef.current;
    threeDRef.current = on;
    setThreeD(on);
    apply3D(map, on, propsRef.current.showArrival);
    map.easeTo(on ? { pitch: THREE_D_PITCH, duration: 800 } : { pitch: 0, bearing: 0, duration: 800 });
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
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReady) return;
    drawAlts(map, props.altRoutes);
  }, [props.altRoutes, styleReady]);

  // --- arrival layer toggle ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReady || !map.getLayer("flood-arrival")) return;
    // M-19: while the hexagons show, they replace both flood fills
    map.setLayoutProperty("flood-arrival", "visibility", props.showArrival && !showHex ? "visible" : "none");
    map.setLayoutProperty("flood-fill", "visibility", props.showArrival || showHex ? "none" : "visible");
    for (const l of ["hex-fill", "hex-line"]) map.setLayoutProperty(l, "visibility", showHex ? "visible" : "none");
    // M-17: the 3D water is coloured by risk; it steps aside while the arrival colours are shown
    if (map.getLayer("flood-3d")) map.setLayoutProperty("flood-3d", "visibility", props.showArrival ? "none" : "visible");
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
  }, [props.showArrival, props.maxArrival, styleReady, showHex]);

  // --- M-19: the scenario's hexagons, fetched when the layer is on ---
  const hexKey = showHex ? (props.scenarioKey ?? null) : null;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReady) return;
    if (!hexKey) {
      hexDataRef.current = EMPTY;
      setData(map, "hex", EMPTY);
      return;
    }
    let alive = true;
    const [area, key] = hexKey.split("/");
    fetch(`/data/${area}/scenarios/${key}.h3.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<HexRow[]>;
      })
      .then((rows) => {
        if (!alive) return;
        hexDataRef.current = hexFeatures(rows);
        setData(map, "hex", hexDataRef.current);
        setHexNote(null);
      })
      .catch((e: Error) => {
        if (!alive) return;
        hexDataRef.current = EMPTY;
        setData(map, "hex", EMPTY);
        setHexNote(`Hexagon layer unavailable for this scenario (${e.message})`);
      });
    return () => {
      alive = false;
    };
  }, [hexKey, styleReady]);

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

  // --- M-14: the tapped / located start point ---
  const tap = props.tapPoint;
  useEffect(() => {
    const map = mapRef.current;
    tapMarkerRef.current?.remove();
    tapMarkerRef.current = null;
    if (!map || !tap) return;
    const el = document.createElement("div");
    el.className = "origin-marker active tap-marker";
    el.innerHTML = `<span class="dot"></span><span class="label"></span>`;
    el.querySelector(".label")!.textContent = tap.label;
    tapMarkerRef.current = new maplibregl.Marker({ element: el, anchor: "left", offset: [-9, 0] }).setLngLat([tap.lon, tap.lat]).addTo(map);
  }, [tap]);

  // --- M-16: the trip's destination ---
  const dest = props.destPoint ?? null;
  useEffect(() => {
    const map = mapRef.current;
    destMarkerRef.current?.remove();
    destMarkerRef.current = null;
    if (!map || !dest) return;
    const el = document.createElement("div");
    el.className = "origin-marker active dest-marker";
    el.innerHTML = `<span class="dot" style="background:#7c3aed"></span><span class="label"></span>`;
    el.querySelector(".label")!.textContent = dest.label;
    destMarkerRef.current = new maplibregl.Marker({ element: el, anchor: "left", offset: [-9, 0] }).setLngLat([dest.lon, dest.lat]).addTo(map);
  }, [dest]);

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
        data-shelters={drawn?.shelters}
        data-high-ground={drawn?.highGround}
        data-route-points={drawn?.routePoints}
        data-view={view ?? undefined}
        data-tap={tap ? `${tap.lon},${tap.lat}` : undefined}
        data-dest={dest ? `${dest.lon},${dest.lat}` : undefined}
        data-alt-routes={drawn?.altRoutes}
        data-3d={threeD ? "on" : "off"}
        data-terrain={drawn?.terrain}
        data-elevation={drawn?.elevation ?? undefined}
        data-pitch={drawn?.pitch}
        data-layers-3d={drawn?.layers3d}
        data-paint-3d={drawn?.paint3d}
        data-hex={showHex ? "on" : "off"}
        data-hexes={drawn?.hexes}
        data-layer-order={drawn?.layerOrder}
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
          <button
            onClick={toggle3D}
            aria-pressed={threeD}
            title="Tilt the map and show terrain, buildings and water depth in 3D (drag with the right mouse button or two fingers to rotate)"
            className={`ml-0.5 rounded-md border-l border-zinc-200 px-2 py-0.5 text-[11px] font-semibold ${threeD ? "bg-zinc-900 text-white" : "text-zinc-700"}`}
          >
            3D
          </button>
          <button
            onClick={() => setShowHex((v) => !v)}
            aria-pressed={showHex}
            title="Show the flood as H3 hexagons: tap one for people, buildings and walking time"
            className={`ml-0.5 rounded-md border-l border-zinc-200 px-2 py-0.5 text-[11px] font-semibold ${showHex ? "bg-zinc-900 text-white" : "text-zinc-700"}`}
          >
            Hexagons
          </button>
        </div>
      )}
      {showHex && !mapError && (
        <div data-hex-note className={`absolute left-12 ${threeD ? "top-16" : "top-9"} max-w-[280px] rounded bg-white/95 px-2 py-0.5 text-[11px] font-medium text-zinc-700 shadow`}>
          {hexNote ?? HEX_NOTE}
        </div>
      )}
      {threeD && !mapError && (
        <div data-3d-note className="absolute left-12 top-9 rounded bg-white/95 px-2 py-0.5 text-[11px] font-medium text-zinc-700 shadow">
          {THREE_D_NOTE}
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

function drawAlts(map: MLMap, alts: [number, number][][] | undefined) {
  setData(map, "route-alt", {
    type: "FeatureCollection",
    features: (alts ?? []).map((c, i) => ({ type: "Feature", geometry: { type: "LineString", coordinates: c }, properties: { i } })),
  });
}

function drawReports(map: MLMap, reports: Report[]) {
  setData(map, "reports", {
    type: "FeatureCollection",
    features: reports.map((r) => ({ type: "Feature", geometry: { type: "Point", coordinates: [r.lon, r.lat] }, properties: { id: r.id } })),
  });
}

/** F20.1: the water and building extrusion heights as the map holds them (null where the layer is absent). */
function paint3d(map: MLMap) {
  const get = (l: string, prop: "fill-extrusion-height" | "fill-extrusion-base") => (map.getLayer(l) ? (map.getPaintProperty(l, prop) ?? null) : null);
  const b = map.getLayer(BUILDINGS_LAYER) ? BUILDINGS_LAYER : map.getLayer("building-3d") ? "building-3d" : null;
  return {
    water: get("flood-3d", "fill-extrusion-height"),
    buildingsLayer: b,
    buildings: b ? get(b, "fill-extrusion-height") : null,
    buildingsBase: b ? get(b, "fill-extrusion-base") : null,
  };
}

/** M-17: add or remove the terrain and the 3D layers. Idempotent; called on toggle and after every style load. */
function apply3D(map: MLMap, on: boolean, showArrival: boolean) {
  if (!on) {
    if (map.getTerrain()) map.setTerrain(null);
    for (const l of ["flood-3d", BUILDINGS_LAYER]) if (map.getLayer(l)) map.removeLayer(l);
    return;
  }
  if (!map.getSource(DEM_SOURCE)) {
    map.addSource(DEM_SOURCE, { type: "raster-dem", tiles: DEM_TILES, encoding: "terrarium", tileSize: 256, maxzoom: 15, attribution: DEM_ATTRIBUTION });
  }
  map.setTerrain({ source: DEM_SOURCE, exaggeration: TERRAIN_X });
  // buildings: Liberty (Normal) already extrudes them from z14; the raster basemaps get the same OpenFreeMap buildings
  const hasExtrusion = map.getStyle().layers.some((l) => l.type === "fill-extrusion" && "source-layer" in l && l["source-layer"] === "building");
  if (!hasExtrusion && !map.getLayer(BUILDINGS_LAYER)) {
    if (!map.getSource(BUILDINGS_SOURCE)) map.addSource(BUILDINGS_SOURCE, { type: "vector", url: "https://tiles.openfreemap.org/planet" });
    map.addLayer(
      {
        id: BUILDINGS_LAYER,
        type: "fill-extrusion",
        source: BUILDINGS_SOURCE,
        "source-layer": "building",
        minzoom: 14,
        filter: ["!", ["has", "hide_3d"]],
        paint: {
          "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0],
          "fill-extrusion-height": ["coalesce", ["get", "render_height"], 0],
          "fill-extrusion-color": "hsl(35,8%,85%)",
          "fill-extrusion-opacity": 0.8,
        },
      },
      "flood-fill",
    );
  }
  // the water: each flood polygon raised by its depth_m x WATER_X, under the routes and markers
  if (!map.getLayer("flood-3d")) {
    map.addLayer(
      {
        id: "flood-3d",
        type: "fill-extrusion",
        source: "flood",
        layout: { visibility: showArrival ? "none" : "visible" },
        paint: {
          "fill-extrusion-color": ["match", ["get", "risk"], "high", RISK_COLORS.high, "medium", RISK_COLORS.medium, RISK_COLORS.low],
          "fill-extrusion-height": ["*", ["coalesce", ["get", "depth_m"], 0], WATER_X],
          "fill-extrusion-base": 0,
          "fill-extrusion-opacity": 0.55,
        },
      },
      "route-baseline",
    );
  }
}

function addLayers(map: MLMap) {
  for (const id of ["flood", "hex", "shelters", "route-baseline", "route-alt", "route-safe", "reports"]) {
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
  // M-19: hexagons above the flood fills, below every route, shelter and report
  map.addLayer({
    id: "hex-fill",
    type: "fill",
    source: "hex",
    layout: { visibility: "none" },
    paint: {
      "fill-color": ["match", ["get", "risk"], "high", RISK_COLORS.high, "medium", RISK_COLORS.medium, RISK_COLORS.low],
      "fill-opacity": 0.6,
    },
  });
  map.addLayer({
    id: "hex-line",
    type: "line",
    source: "hex",
    layout: { visibility: "none" },
    paint: { "line-color": "#ffffff", "line-width": 0.6, "line-opacity": 0.8 },
  });
  map.addLayer({
    id: "route-baseline",
    type: "line",
    source: "route-baseline",
    layout: { "line-cap": "round" },
    paint: { "line-color": "#6b7280", "line-width": 4, "line-dasharray": [1.5, 1.5] },
  });
  map.addLayer({
    id: "route-alt",
    type: "line",
    source: "route-alt",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#64748b", "line-width": 4, "line-opacity": 0.75 },
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
