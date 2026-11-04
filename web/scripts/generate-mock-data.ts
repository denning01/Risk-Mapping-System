/**
 * MOCK DATA GENERATOR
 * -------------------
 * Writes every file in the data contract (docs/DATA_CONTRACT.md) under public/data/
 * so the app can be built and demoed before Person A's real pipeline output exists.
 *
 * Nothing here is a real model. River lines, roads, shelters and origins use
 * APPROXIMATE, hand-entered coordinates that only need to look plausible on the map.
 * Every output is flagged mock (meta.json "mock": true, exposure "source": "mock").
 *
 * The fake "model" mimics the shape of the real one so the UI behaves realistically:
 *   - a grid of cells (like a raster) is classified by distance to the nearest river,
 *   - flood extent and depth grow with rainfall, El Niño raises both,
 *   - risk classes come from water depth: <0.3 m low, 0.3–1 m medium, >1 m high,
 *   - arrival time grows with distance downstream and away from the channel.
 *
 * Run: npm run mock:data
 */
import fs from "node:fs";
import path from "node:path";
import * as turf from "@turf/turf";
import type { Feature, LineString, MultiPolygon } from "geojson";
import { AREA_IDS, ENSO_VALUES, RAIN_VALUES } from "../src/lib/schema";
import type { Area, AreaId, CropRule, Enso, Exposure, Origin, Risk, Route, Shelter } from "../src/lib/types";

const OUT = path.join(__dirname, "..", "public", "data");
const YEAR = new Date().getFullYear();

type LL = [number, number];

interface AreaConfig {
  area: Area;
  rivers: { name: string; coords: LL[]; flowsFromStart: boolean }[];
  cellDeg: number;
  /** flood extent half-width in km = (a + b*rain) */
  width: { a: number; b: number };
  /** max water depth at the channel in m = (a + b*rain) */
  depth: { a: number; b: number };
  /** water speed along the channel (km/h) and across the floodplain (km/h) */
  speed: { along: number; across: number; lag_h: number };
  /** distance from a river (km) treated as a bridge crossing when checking routes */
  bridgeKm: number;
  /** population density model: base people/km² plus hotspots */
  density: { base: number; hotspots: { at: LL; peak: number; sigmaKm: number }[] };
  peoplePerBuilding: number;
  roads: { name: string; coords: LL[] }[];
  shelters: Omit<Shelter, "safe">[];
  origins: Origin[];
  /** routes: one plan per origin */
  plans: Record<string, RoutePlan>;
  /** wider floodplain downstream (Nyando) */
  downstreamWidening: number;
}

type RoutePlan =
  | { kind: "commute"; destination: string; candidates: LL[][] }
  | { kind: "to_shelter" | "relocation" };

// ---------------------------------------------------------------------------
// Area configs. ALL COORDINATES ARE APPROXIMATE (hand-entered for a mock demo).
// ---------------------------------------------------------------------------

const NAIROBI: AreaConfig = {
  area: {
    id: "nairobi",
    name: "Nairobi (urban)",
    type: "urban",
    bbox: [36.78, -1.33, 36.92, -1.22],
    center: [36.85, -1.275],
    zoom: 12.5,
    user_types: ["commuter", "informal_settlement_resident", "trader"],
  },
  rivers: [
    {
      name: "Nairobi River",
      flowsFromStart: true,
      coords: [
        [36.78, -1.27], [36.8, -1.275], [36.815, -1.28], [36.83, -1.278], [36.845, -1.27],
        [36.86, -1.262], [36.88, -1.258], [36.9, -1.255], [36.92, -1.25],
      ],
    },
    {
      name: "Mathare River",
      flowsFromStart: true,
      coords: [[36.8, -1.235], [36.83, -1.245], [36.855, -1.255], [36.87, -1.257], [36.88, -1.258]],
    },
    {
      name: "Ngong River",
      flowsFromStart: true,
      coords: [[36.78, -1.31], [36.8, -1.312], [36.83, -1.31], [36.86, -1.305], [36.89, -1.3], [36.92, -1.295]],
    },
  ],
  cellDeg: 0.00135, // ~150 m
  width: { a: 0.03, b: 0.0006 },
  depth: { a: 0.5, b: 0.009 },
  speed: { along: 6, across: 0.6, lag_h: 0.5 },
  bridgeKm: 0.1,
  density: {
    base: 5000,
    hotspots: [
      { at: [36.858, -1.26], peak: 25000, sigmaKm: 1.0 }, // Mathare
      { at: [36.787, -1.313], peak: 28000, sigmaKm: 1.2 }, // Kibera
      { at: [36.88, -1.31], peak: 22000, sigmaKm: 1.2 }, // Mukuru
    ],
  },
  peoplePerBuilding: 4.2,
  downstreamWidening: 0.3,
  roads: [
    { name: "Juja Road", coords: [[36.835, -1.272], [36.85, -1.264], [36.862, -1.2595], [36.876, -1.2545], [36.886, -1.242]] },
    { name: "Outer Ring Road", coords: [[36.887, -1.222], [36.889, -1.245], [36.891, -1.262], [36.894, -1.285], [36.896, -1.31]] },
    { name: "Lusaka Road", coords: [[36.835, -1.295], [36.842, -1.302], [36.85, -1.307], [36.855, -1.315]] },
    { name: "Kipande Road", coords: [[36.808, -1.27], [36.815, -1.276], [36.822, -1.281]] },
    { name: "Thika Road", coords: [[36.83, -1.268], [36.845, -1.25], [36.86, -1.235], [36.885, -1.222]] },
  ],
  shelters: [
    { id: "nbi-s1", name: "Primary school, Mathare North (mock)", type: "school", lon: 36.868, lat: -1.243, capacity: 800 },
    { id: "nbi-s2", name: "Church hall, Huruma (mock)", type: "church", lon: 36.873, lat: -1.268, capacity: 300 },
    { id: "nbi-s3", name: "Hospital, Ngara (mock)", type: "hospital", lon: 36.826, lat: -1.272, capacity: 150 },
    { id: "nbi-s4", name: "Community hall, Kariobangi (mock)", type: "community_hall", lon: 36.884, lat: -1.256, capacity: 400 },
    { id: "nbi-s5", name: "Secondary school, Kibera (mock)", type: "school", lon: 36.79, lat: -1.3, capacity: 900 },
    { id: "nbi-s6", name: "Church, South B (mock)", type: "church", lon: 36.84, lat: -1.318, capacity: 350 },
    { id: "nbi-s7", name: "High ground, City Park (mock)", type: "high_ground", lon: 36.817, lat: -1.262, capacity: null },
  ],
  origins: [
    { id: "nbi-o1", name: "Mathare", lon: 36.858, lat: -1.258, user_type: "informal_settlement_resident" },
    { id: "nbi-o2", name: "Kibera", lon: 36.787, lat: -1.31, user_type: "informal_settlement_resident" },
    { id: "nbi-o3", name: "Westlands (commute to Kasarani)", lon: 36.805, lat: -1.265, user_type: "commuter" },
    { id: "nbi-o4", name: "Eastleigh market", lon: 36.85, lat: -1.272, user_type: "trader" },
  ],
  plans: {
    "nbi-o1": { kind: "to_shelter" },
    "nbi-o2": { kind: "to_shelter" },
    "nbi-o4": { kind: "to_shelter" },
    "nbi-o3": {
      kind: "commute",
      destination: "Kasarani",
      candidates: [
        // baseline: along the Mathare valley (Juja Road side)
        [[36.805, -1.265], [36.822, -1.266], [36.835, -1.266], [36.85, -1.264], [36.862, -1.2595], [36.876, -1.2545], [36.886, -1.242], [36.895, -1.225]],
        // alternative: up Thika Road, crossing the river once on a bridge
        [[36.805, -1.265], [36.818, -1.268], [36.83, -1.268], [36.845, -1.25], [36.86, -1.235], [36.885, -1.222], [36.895, -1.225]],
        // alternative: northern bypass
        [[36.805, -1.265], [36.808, -1.245], [36.815, -1.228], [36.845, -1.222], [36.875, -1.221], [36.895, -1.225]],
      ],
    },
  },
};

const NYANDO: AreaConfig = {
  area: {
    id: "nyando",
    name: "Nyando, Kisumu (rural)",
    type: "rural",
    bbox: [34.85, -0.45, 35.3, 0.0],
    center: [35.05, -0.2],
    zoom: 11,
    user_types: ["settler", "farmer", "trader"],
  },
  rivers: [
    {
      // flows east -> west into Lake Victoria (Winam Gulf); listed upstream first
      name: "Nyando River",
      flowsFromStart: true,
      coords: [
        [35.3, -0.12], [35.2, -0.15], [35.1, -0.18], [35.02, -0.19], [34.96, -0.18],
        [34.919, -0.173], [34.89, -0.19], [34.86, -0.21],
      ],
    },
  ],
  cellDeg: 0.0045, // ~500 m
  width: { a: 0.15, b: 0.006 },
  depth: { a: 0.4, b: 0.008 },
  speed: { along: 3, across: 0.35, lag_h: 2 },
  bridgeKm: 0.3,
  density: {
    base: 280,
    hotspots: [
      { at: [34.919, -0.173], peak: 2500, sigmaKm: 1.5 }, // Ahero
      { at: [35.075, -0.16], peak: 1500, sigmaKm: 1.2 }, // Awasi
    ],
  },
  peoplePerBuilding: 4.8,
  downstreamWidening: 1.2,
  roads: [
    { name: "Kisumu–Nairobi highway (B1) near Ahero", coords: [[34.86, -0.13], [34.89, -0.15], [34.919, -0.168], [34.96, -0.168], [35.0, -0.165], [35.075, -0.155]] },
    { name: "Ahero–Katito road", coords: [[34.919, -0.175], [34.925, -0.22], [34.935, -0.27], [34.945, -0.31]] },
    { name: "Awasi–Chemelil road", coords: [[35.075, -0.16], [35.09, -0.11], [35.1, -0.06]] },
    { name: "Kano plains farm track", coords: [[34.95, -0.215], [34.98, -0.225], [35.02, -0.23], [35.05, -0.215]] },
  ],
  shelters: [
    { id: "nya-s1", name: "Health centre, Ahero (mock)", type: "hospital", lon: 34.921, lat: -0.178, capacity: 120 },
    { id: "nya-s2", name: "Primary school, Awasi (mock)", type: "school", lon: 35.078, lat: -0.152, capacity: 600 },
    { id: "nya-s3", name: "Church, Kano plains (mock)", type: "church", lon: 34.99, lat: -0.235, capacity: 250 },
    { id: "nya-s4", name: "Community hall, Kochieng (mock)", type: "community_hall", lon: 34.97, lat: -0.14, capacity: 300 },
    { id: "nya-s5", name: "High ground: northern ridge (mock)", type: "high_ground", lon: 34.93, lat: -0.05, capacity: null },
    { id: "nya-s6", name: "High ground: southern plateau (mock)", type: "high_ground", lon: 34.98, lat: -0.36, capacity: null },
    { id: "nya-s7", name: "High ground: eastern hills (mock)", type: "high_ground", lon: 35.2, lat: -0.05, capacity: null },
  ],
  origins: [
    { id: "nya-o1", name: "Ahero town", lon: 34.919, lat: -0.173, user_type: "settler" },
    { id: "nya-o2", name: "Awasi market", lon: 35.075, lat: -0.16, user_type: "trader" },
    { id: "nya-o3", name: "Farm on the Kano plains", lon: 34.96, lat: -0.205, user_type: "farmer" },
  ],
  plans: {
    "nya-o1": { kind: "relocation" },
    "nya-o2": { kind: "to_shelter" },
    "nya-o3": { kind: "relocation" },
  },
};

const CONFIGS: Record<AreaId, AreaConfig> = { nairobi: NAIROBI, nyando: NYANDO };

// ---------------------------------------------------------------------------
// The fake hydrology
// ---------------------------------------------------------------------------

interface RiverInfo {
  line: Feature<LineString>;
  lengthKm: number;
}

function riverInfo(cfg: AreaConfig): RiverInfo[] {
  return cfg.rivers.map((r) => {
    const line = turf.lineString(r.coords);
    return { line, lengthKm: turf.length(line, { units: "kilometers" }) };
  });
}

/** Smooth, deterministic noise in [-1, 1] so flood edges look natural. */
function noise(lon: number, lat: number): number {
  return 0.5 * (Math.sin(lon * 310 + lat * 90) + Math.cos(lat * 280 - lon * 70));
}

interface CellState {
  depth: number;
  arrival_h: number;
  riverDistKm: number;
}

function stateAt(cfg: AreaConfig, rivers: RiverInfo[], lon: number, lat: number, rain: number, enso: Enso): CellState {
  const pt = turf.point([lon, lat]);
  let best = { d: Infinity, along: 0, len: 1 };
  for (const r of rivers) {
    const np = turf.nearestPointOnLine(r.line, pt, { units: "kilometers" });
    const d = np.properties.dist ?? Infinity;
    if (d < best.d) best = { d, along: np.properties.location ?? 0, len: r.lengthKm };
  }
  const ensoW = enso === "elnino" ? 1.3 : 1;
  const ensoD = enso === "elnino" ? 1.2 : 1;
  const downstream = best.along / best.len; // 0 at source, 1 at mouth
  const widen = 1 + cfg.downstreamWidening * downstream;
  const width = (cfg.width.a + cfg.width.b * rain) * ensoW * widen * (1 + 0.25 * noise(lon, lat));
  const maxDepth = (cfg.depth.a + cfg.depth.b * rain) * ensoD;
  const rel = 1 - best.d / width;
  const depth = rel > 0 ? maxDepth * Math.pow(rel, 1.2) : 0;
  const arrival_h = cfg.speed.lag_h + best.along / cfg.speed.along + best.d / cfg.speed.across;
  return { depth, arrival_h, riverDistKm: best.d };
}

function riskOf(depth: number): Risk | null {
  if (depth <= 0.02) return null;
  if (depth < 0.3) return "low";
  if (depth <= 1.0) return "medium";
  return "high";
}

function densityAt(cfg: AreaConfig, lon: number, lat: number): number {
  let d = cfg.density.base;
  for (const h of cfg.density.hotspots) {
    const km = turf.distance(turf.point([lon, lat]), turf.point(h.at), { units: "kilometers" });
    d += h.peak * Math.exp(-(km * km) / (2 * h.sigmaKm * h.sigmaKm));
  }
  return d;
}

const round = (n: number, dp = 5) => Math.round(n * 10 ** dp) / 10 ** dp;

// ---------------------------------------------------------------------------
// Generation
// ---------------------------------------------------------------------------

function writeJson(rel: string, data: unknown) {
  const file = path.join(OUT, rel);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(data));
}

function lineIsBlocked(cfg: AreaConfig, rivers: RiverInfo[], coords: LL[], rain: number, enso: Enso): boolean {
  const line = turf.lineString(coords);
  const len = turf.length(line, { units: "kilometers" });
  const step = cfg.cellDeg * 111 * 0.5;
  for (let s = 0; s <= len; s += step) {
    const [lon, lat] = turf.along(line, s, { units: "kilometers" }).geometry.coordinates;
    const st = stateAt(cfg, rivers, lon, lat, rain, enso);
    if (st.riverDistKm < cfg.bridgeKm) continue; // bridge crossing
    if (st.depth >= 0.3) return true;
  }
  return false;
}

function lineKm(coords: LL[]): number {
  return turf.length(turf.lineString(coords), { units: "kilometers" });
}

/** Simple two-leg path that bends away from the nearest river. */
function shelterPath(from: LL, to: LL): LL[] {
  const mid: LL = [(from[0] + to[0]) / 2 + (to[1] - from[1]) * 0.15, (from[1] + to[1]) / 2 - (to[0] - from[0]) * 0.15];
  return [from, [round(mid[0]), round(mid[1])], to];
}

function generateArea(cfg: AreaConfig) {
  const rivers = riverInfo(cfg);
  const [w, s, e, n] = cfg.area.bbox;
  const c = cfg.cellDeg;
  const midLat = (s + n) / 2;
  const cellKm2 = c * 111.32 * Math.cos((midLat * Math.PI) / 180) * (c * 110.57);

  // Precompute the grid of cell centres
  const cells: { lon: number; lat: number; density: number }[] = [];
  for (let lon = w + c / 2; lon < e; lon += c) {
    for (let lat = s + c / 2; lat < n; lat += c) {
      cells.push({ lon, lat, density: densityAt(cfg, lon, lat) });
    }
  }

  const id = cfg.area.id;
  writeJson(`${id}/origins.json`, cfg.origins);

  const summary: string[] = [];

  for (const rain of RAIN_VALUES) {
    for (const enso of ENSO_VALUES) {
      const key = `${rain}_${enso}`;
      // --- flood cells grouped by (risk, arrival bin) ---
      const groups = new Map<string, { risk: Risk; arrival: number; depthSum: number; polys: number[][][][] }>();
      let floodedCells = 0;
      let people = 0;
      for (const cell of cells) {
        const st = stateAt(cfg, rivers, cell.lon, cell.lat, rain, enso);
        const risk = riskOf(st.depth);
        if (!risk) continue;
        floodedCells++;
        people += cell.density * cellKm2;
        const bin = cfg.area.type === "urban" ? Math.round(st.arrival_h * 2) / 2 : Math.round(st.arrival_h);
        const gk = `${risk}|${bin}`;
        if (!groups.has(gk)) groups.set(gk, { risk, arrival: bin, depthSum: 0, polys: [] });
        const g = groups.get(gk)!;
        g.depthSum += st.depth;
        const h = c / 2;
        const x0 = round(cell.lon - h), x1 = round(cell.lon + h), y0 = round(cell.lat - h), y1 = round(cell.lat + h);
        g.polys.push([[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]);
      }
      const order: Record<Risk, number> = { low: 0, medium: 1, high: 2 };
      const features: Feature<MultiPolygon>[] = [...groups.values()]
        .sort((a, b) => order[a.risk] - order[b.risk])
        .map((g) => ({
          type: "Feature",
          geometry: { type: "MultiPolygon", coordinates: g.polys },
          properties: {
            risk: g.risk,
            depth_m: Math.round((g.depthSum / g.polys.length) * 100) / 100,
            arrival_h: g.arrival,
          },
        }));
      writeJson(`${id}/scenarios/${key}.geojson`, { type: "FeatureCollection", features });

      // --- roads cut ---
      const roadsCut = cfg.roads.filter((r) => lineIsBlocked(cfg, rivers, r.coords, rain, enso)).map((r) => r.name);

      // --- exposure ---
      const medium = Math.round(people);
      const exposure: Exposure = {
        year: YEAR,
        population: { low: Math.round(medium * 0.88), medium, high: Math.round(medium * 1.12) },
        buildings: Math.round(medium / cfg.peoplePerBuilding),
        flooded_area_km2: Math.round(floodedCells * cellKm2 * 10) / 10,
        roads_cut: roadsCut,
        source: "mock",
      };
      writeJson(`${id}/scenarios/${key}.exposure.json`, exposure);

      // --- shelters ---
      const shelters: Shelter[] = cfg.shelters.map((sh) => ({
        ...sh,
        safe: stateAt(cfg, rivers, sh.lon, sh.lat, rain, enso).depth <= 0.02,
      }));
      writeJson(`${id}/scenarios/${key}.shelters.json`, shelters);

      // --- routes ---
      const routes: Route[] = cfg.origins.map((o) => {
        const plan = cfg.plans[o.id];
        const from: LL = [o.lon, o.lat];
        if (plan.kind === "commute") {
          const [baselineCoords, ...alts] = plan.candidates;
          const baseMin = Math.round((lineKm(baselineCoords) / 18) * 60);
          const baseBlocked = lineIsBlocked(cfg, rivers, baselineCoords, rain, enso);
          let safeCoords = baselineCoords;
          if (baseBlocked) {
            safeCoords = alts.find((a) => !lineIsBlocked(cfg, rivers, a, rain, enso)) ?? alts[alts.length - 1];
          }
          // cut roads that the baseline route actually runs along (any vertex within 300 m)
          const baseLine = turf.lineString(baselineCoords);
          const avoided = baseBlocked
            ? cfg.roads
                .filter((r) => roadsCut.includes(r.name))
                .filter((r) => r.coords.some((p) => turf.pointToLineDistance(turf.point(p), baseLine, { units: "kilometers" }) < 0.3))
                .map((r) => r.name)
            : [];
          return {
            origin_id: o.id,
            kind: "commute",
            shelter_id: null,
            destination_name: plan.destination,
            baseline: { geometry: { type: "LineString", coordinates: baselineCoords }, minutes: baseMin },
            // the detour is also slower because of flood traffic
            safe: {
              geometry: { type: "LineString", coordinates: safeCoords },
              minutes: baseBlocked ? Math.round((lineKm(safeCoords) / 14) * 60) : baseMin,
            },
            avoided: baseBlocked && avoided.length === 0 ? ["Flooded section of the usual route"] : avoided,
          };
        }
        // to_shelter / relocation: nearest safe shelter of the right type whose path is not blocked
        const pool = shelters.filter((sh) => sh.safe && (plan.kind === "relocation" ? sh.type === "high_ground" : true));
        const ranked = pool
          .map((sh) => ({ sh, km: turf.distance(turf.point(from), turf.point([sh.lon, sh.lat]), { units: "kilometers" }) }))
          .sort((a, b) => a.km - b.km);
        const pick =
          ranked.find((r) => !lineIsBlocked(cfg, rivers, shelterPath(from, [r.sh.lon, r.sh.lat]), rain, enso)) ?? ranked[0];
        const target = pick?.sh ?? shelters[0];
        const coords = shelterPath(from, [target.lon, target.lat]);
        const speedKmh = plan.kind === "relocation" ? 4 : 4.5; // walking
        // cut roads within 1.5 km of the starting point: the ones this person should avoid
        const avoided = cfg.roads
          .filter((r) => roadsCut.includes(r.name))
          .filter((r) => turf.pointToLineDistance(turf.point(from), turf.lineString(r.coords), { units: "kilometers" }) < 1.5)
          .map((r) => r.name);
        return {
          origin_id: o.id,
          kind: plan.kind,
          shelter_id: target.id,
          destination_name: target.name,
          baseline: null,
          safe: { geometry: { type: "LineString", coordinates: coords }, minutes: Math.round((lineKm(coords) / speedKmh) * 60) },
          avoided,
        };
      });
      writeJson(`${id}/scenarios/${key}.routes.json`, routes);

      summary.push(
        `${id.padEnd(8)} ${key.padEnd(11)} area=${String(exposure.flooded_area_km2).padStart(6)} km²  people=${String(medium).padStart(7)}  roads_cut=${roadsCut.length}  safe_shelters=${shelters.filter((x) => x.safe).length}/${shelters.length}`,
      );
    }
  }
  return summary;
}

// ---------------------------------------------------------------------------
// Crops (rules table). Content is indicative and MUST be checked against
// FAO EcoCrop and KALRO guidance before the pitch.
// ---------------------------------------------------------------------------

function crops(): CropRule[] {
  const src = ["FAO EcoCrop (to verify)", "KALRO crop guidance (to verify)"];
  const rows: CropRule[] = [];
  const add = (crop: string, season: CropRule["season"], enso: Enso, risk: Risk, actions: string[]) =>
    rows.push({ crop, season, enso, risk, actions, sources: src });

  for (const season of ["short_rains", "long_rains"] as const) {
    add("maize", season, "elnino", "high", [
      "Delay planting until the flood risk has passed",
      "Plant on raised beds or ridges",
      "Clear drainage channels around the field",
      "Use a short-maturity variety",
    ]);
    add("maize", season, "normal", season === "long_rains" ? "medium" : "low", [
      "Plant at the onset of reliable rains",
      "Avoid the lowest, waterlogged parts of the field",
      "Keep drainage channels open",
    ]);
    add("sorghum", season, "elnino", "medium", [
      "Good flood-tolerant alternative to maize",
      "Plant on the higher parts of the farm",
      "Watch for waterlogging after heavy storms",
    ]);
    add("sorghum", season, "normal", "low", ["Plant as normal", "Use certified seed", "Weed early to cut competition"]);
    add("rice", season, "elnino", "low", [
      "Suited to the flood-prone plains",
      "Prepare paddies and strengthen bunds",
      "Check irrigation scheme gates before peak rains",
    ]);
    add("rice", season, "normal", "low", ["Prepare paddies and bunds", "Plan water management with the scheme"]);
    add("cassava", season, "elnino", "high", [
      "Plant on mounds, never in waterlogged soil",
      "Harvest mature roots before the peak rains",
      "Move new plantings to higher ground",
    ]);
    add("cassava", season, "normal", "low", ["Plant on mounds", "Avoid waterlogged soil"]);
  }
  return rows;
}

// ---------------------------------------------------------------------------

function main() {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });

  writeJson("areas.json", AREA_IDS.map((a) => CONFIGS[a].area));
  writeJson("advice/crops.json", crops());
  writeJson("meta.json", {
    mock: true,
    generated_at: new Date().toISOString(),
    sources: [
      "MOCK: hand-entered approximate river, road and shelter locations",
      "Basemap: © OpenStreetMap contributors, OpenFreeMap",
    ],
    notes: "Mock data for UI development. Screening-level model, not a forecast.",
  });

  for (const a of AREA_IDS) {
    const lines = generateArea(CONFIGS[a]);
    console.log(lines.join("\n"));
  }
  console.log(`\nMock data written to ${OUT}`);
}

main();
