/**
 * M-14 · "Route from where I am": the E-16 client, run in the browser on web/public/data/<area>/graph.json (v2, or v3 with relocation targets).
 * A line-for-line port of the Python reference client_route() in pipeline/06_routing.py (the oracle):
 *   1. snap the point to the nearest WALK node in UTM metres (lowest node index on a tie); if that node has no
 *      unflooded walk edge -> no route
 *   2. targets: EVERY shelter usable in the scenario (its "usable" bit), each reached by a virtual edge from its node
 *      costing its snap leg at walking speed
 *   3. ONE Dijkstra from the snapped node: flooded edges removed, cost = deciseconds x near_penalty on near edges; stop
 *      at the first settled shelter. Heap order = (cost, road node before shelter, shelter id, node index), the same
 *      total order as the Python heap tuples, so ties resolve identically.
 *   4. minutes = ceil(TRUE seconds of the path + both snap legs at walking speed)
 * Hand-written binary heap, no dependency. No path aliases: e2e/route-*.spec.ts import this file directly.
 */

export interface GraphShelter {
  id: string;
  /** a routing TARGET: an OSM shelter, or (graph.json v3, E-19) a ranked relocation site on high ground. Absent = shelter. */
  kind?: "shelter" | "relocation";
  name: string;
  type: string;
  lon: number;
  lat: number;
  node: number;
  snap_m: number;
  usable: number; // bitmask over scenarios
}
interface Net {
  edges: number[]; // flat [u, v, deciseconds, ...]
  flooded: number[]; // bitmask per edge
  near: number[]; // bitmask per edge
  geom: number[][]; // per edge, interior vertices flat [lon, lat, ...], oriented u -> v
}
export interface GraphJson {
  area: string;
  version: 2 | 3;
  scenarios: string[];
  time_unit: string;
  walk_kph: number;
  nodes: number[]; // flat [lon, lat, ...]
  walk: Net;
  utm_epsg: number;
  near_penalty: number;
  client_targets: string;
  max_dest_snap_m: number;
  shelters: GraphShelter[];
}

export type RouteOk = {
  ok: true;
  shelter: GraphShelter;
  minutes: number;
  edges: number[]; // walk edge indices, from the snapped start node
  costS: number;
  snapM: [number, number]; // [tap -> start node, shelter node -> shelter]
  coords: [number, number][]; // tap, the path's vertices, the shelter
};
export type RouteRefusal = "cut_off" | "no_usable_shelter" | "unreachable";
export type RouteResult = RouteOk | { ok: false; reason: RouteRefusal };

/** Check the parts of graph.json this client reads; throws on anything else. */
export function checkGraph(j: unknown): GraphJson {
  const g = j as GraphJson;
  const bad = (m: string) => {
    throw new Error(`graph.json: ${m}`);
  };
  if (!g || typeof g !== "object") bad("not an object");
  // v2 (E-16): OSM shelters, no kind. v3 (E-19): every target has a kind, "shelter" or "relocation" (F15.3).
  if (g.version !== 2 && g.version !== 3) bad(`version ${g.version}, expected 2 or 3`);
  if (g.time_unit !== "deciseconds") bad(`time_unit ${g.time_unit}`);
  if (g.client_targets !== "all_usable") bad(`client_targets ${g.client_targets}`);
  if (!Array.isArray(g.scenarios) || g.scenarios.length === 0 || g.scenarios.length > 31) bad("scenarios");
  if (!Array.isArray(g.nodes) || g.nodes.length % 2) bad("nodes");
  const w = g.walk;
  const m = w?.flooded?.length;
  if (!Array.isArray(w?.edges) || w.edges.length !== 3 * m || w.near?.length !== m || w.geom?.length !== m) bad("walk arrays differ in length");
  if (!Array.isArray(g.shelters)) bad("shelters");
  for (const s of g.shelters) {
    if (s.kind !== undefined && s.kind !== "shelter" && s.kind !== "relocation") bad(`target ${s.id} kind ${s.kind}`);
    if (g.version === 3 && s.kind === undefined) bad(`v3 target ${s.id} has no kind`);
  }
  if (!(g.walk_kph > 0) || !(g.near_penalty >= 1)) bad("walk_kph / near_penalty");
  const z = g.utm_epsg - (g.utm_epsg >= 32701 ? 32700 : 32600);
  if (!((g.utm_epsg >= 32601 && g.utm_epsg <= 32660) || (g.utm_epsg >= 32701 && g.utm_epsg <= 32760)) || z < 1) bad(`utm_epsg ${g.utm_epsg}`);
  return g;
}

/** Targets that are relocation sites (high ground). A rural area must have them before a tap may be routed there:
 * routing a Nyando user only to OSM shelters is ruled out (operator, 2026-11-08). */
export const relocationTargets = (g: GraphJson) => g.shelters.filter((s) => s.kind === "relocation").length;

// ---------------------------------------------------------------------------------------------
// WGS84 -> UTM (transverse Mercator, Krueger series to n^6: sub-millimetre inside a zone; pyproj's default "etmerc"
// uses the same series)
// ---------------------------------------------------------------------------------------------
const A_WGS = 6378137;
const F_WGS = 1 / 298.257223563;
const N3 = F_WGS / (2 - F_WGS);
const ALPHA = (() => {
  const n = N3;
  const n2 = n * n, n3 = n2 * n, n4 = n3 * n, n5 = n4 * n, n6 = n5 * n;
  return [
    n / 2 - (2 * n2) / 3 + (5 * n3) / 16 + (41 * n4) / 180 - (127 * n5) / 288 + (7891 * n6) / 37800,
    (13 * n2) / 48 - (3 * n3) / 5 + (557 * n4) / 1440 + (281 * n5) / 630 - (1983433 * n6) / 1935360,
    (61 * n3) / 240 - (103 * n4) / 140 + (15061 * n5) / 26880 + (167603 * n6) / 181440,
    (49561 * n4) / 161280 - (179 * n5) / 168 + (6601661 * n6) / 7257600,
    (34729 * n5) / 80640 - (3418889 * n6) / 1995840,
    (212378941 * n6) / 319334400,
  ];
})();
const A_RECT = (A_WGS / (1 + N3)) * (1 + (N3 * N3) / 4 + N3 ** 4 / 64 + N3 ** 6 / 256);
const ECC = (2 * Math.sqrt(N3)) / (1 + N3);

/** Projector for an EPSG:326xx / 327xx UTM zone: (lon, lat) degrees -> [easting, northing] metres. */
export function utmProjector(epsg: number): (lon: number, lat: number) => [number, number] {
  const south = epsg >= 32701;
  const zone = epsg - (south ? 32700 : 32600);
  const lon0 = ((zone * 6 - 183) * Math.PI) / 180;
  const k0 = 0.9996;
  return (lon, lat) => {
    const phi = (lat * Math.PI) / 180;
    const lam = (lon * Math.PI) / 180 - lon0;
    const s = Math.sin(phi);
    const t = Math.sinh(Math.atanh(s) - ECC * Math.atanh(ECC * s));
    const xi = Math.atan2(t, Math.cos(lam));
    const eta = Math.atanh(Math.sin(lam) / Math.sqrt(1 + t * t));
    let x = eta;
    let y = xi;
    for (let j = 1; j <= 6; j++) {
      x += ALPHA[j - 1] * Math.cos(2 * j * xi) * Math.sinh(2 * j * eta);
      y += ALPHA[j - 1] * Math.sin(2 * j * xi) * Math.cosh(2 * j * eta);
    }
    return [500000 + k0 * A_RECT * x, (south ? 10000000 : 0) + k0 * A_RECT * y];
  };
}

// ---------------------------------------------------------------------------------------------
// Binary min-heap over (cost, kind, shelter id, node): the Python heap tuple order
// ---------------------------------------------------------------------------------------------
interface Entry {
  c: number;
  kind: 0 | 1; // 0 = road node, 1 = shelter
  sid: string;
  node: number;
}
const less = (a: Entry, b: Entry) =>
  a.c !== b.c ? a.c < b.c : a.kind !== b.kind ? a.kind < b.kind : a.sid !== b.sid ? a.sid < b.sid : a.node < b.node;

export class MinHeap {
  private h: Entry[] = [];
  get size() {
    return this.h.length;
  }
  push(e: Entry) {
    const h = this.h;
    h.push(e);
    let i = h.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (!less(h[i], h[p])) break;
      const tmp = h[i];
      h[i] = h[p];
      h[p] = tmp;
      i = p;
    }
  }
  pop(): Entry | undefined {
    const h = this.h;
    if (!h.length) return undefined;
    const top = h[0];
    const last = h.pop()!;
    if (h.length) {
      h[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let m = i;
        if (l < h.length && less(h[l], h[m])) m = l;
        if (r < h.length && less(h[r], h[m])) m = r;
        if (m === i) break;
        const tmp = h[i];
        h[i] = h[m];
        h[m] = tmp;
        i = m;
      }
    }
    return top;
  }
}

// ---------------------------------------------------------------------------------------------
// The client
// ---------------------------------------------------------------------------------------------
interface Adj {
  start: Int32Array; // CSR offsets per node
  to: Int32Array;
  cost: Float64Array; // penalised deciseconds
  t: Float64Array; // true deciseconds
  edge: Int32Array;
}

export interface PreparedGraph {
  g: GraphJson;
  /** walk nodes, ascending index, with their UTM coordinates */
  walkNodes: Int32Array;
  wx: Float64Array;
  wy: Float64Array;
  project: (lon: number, lat: number) => [number, number];
  adj: Map<string, Adj>;
}

export function prepareGraph(g: GraphJson): PreparedGraph {
  const E = g.walk.edges;
  const seen = new Uint8Array(g.nodes.length / 2);
  for (let i = 0; i < E.length; i += 3) seen[E[i]] = seen[E[i + 1]] = 1;
  let n = 0;
  for (let i = 0; i < seen.length; i++) n += seen[i];
  const walkNodes = new Int32Array(n);
  const wx = new Float64Array(n);
  const wy = new Float64Array(n);
  const project = utmProjector(g.utm_epsg);
  for (let i = 0, k = 0; i < seen.length; i++) {
    if (!seen[i]) continue;
    walkNodes[k] = i;
    [wx[k], wy[k]] = project(g.nodes[2 * i], g.nodes[2 * i + 1]);
    k++;
  }
  return { g, walkNodes, wx, wy, project, adj: new Map() };
}

/** Adjacency for one scenario, in the Python client's insertion order (edge order; u's list gets v, then v's gets u). */
function adjacency(P: PreparedGraph, ki: number, pen: number): Adj {
  const tag = `${ki}:${pen}`;
  const hit = P.adj.get(tag);
  if (hit) return hit;
  const { edges: E, flooded: F, near: N } = P.g.walk;
  const nn = P.g.nodes.length / 2;
  const deg = new Int32Array(nn + 1);
  for (let i = 0; i < F.length; i++) {
    if ((F[i] >> ki) & 1) continue;
    deg[E[3 * i]]++;
    deg[E[3 * i + 1]]++;
  }
  const start = new Int32Array(nn + 1);
  for (let x = 0; x < nn; x++) start[x + 1] = start[x] + deg[x];
  const fill = start.slice(0, nn);
  const m = start[nn];
  const to = new Int32Array(m);
  const cost = new Float64Array(m);
  const t = new Float64Array(m);
  const edge = new Int32Array(m);
  for (let i = 0; i < F.length; i++) {
    if ((F[i] >> ki) & 1) continue;
    const u = E[3 * i], v = E[3 * i + 1], tt = E[3 * i + 2];
    const c = tt * ((N[i] >> ki) & 1 ? pen : 1.0);
    for (const [a, b] of [[u, v], [v, u]]) {
      const j = fill[a]++;
      to[j] = b;
      cost[j] = c;
      t[j] = tt;
      edge[j] = i;
    }
  }
  const adj = { start, to, cost, t, edge };
  P.adj.set(tag, adj);
  return adj;
}

/** Step 1: the nearest walk node in UTM metres, and the distance to it; the first (lowest index) on a tie, as numpy argmin. */
export function snapStart(P: PreparedGraph, lon: number, lat: number): { node: number; m: number } {
  const [px, py] = P.project(lon, lat);
  let j = 0;
  let best = Infinity;
  const { wx, wy } = P;
  for (let k = 0; k < wx.length; k++) {
    const dx = wx[k] - px;
    const dy = wy[k] - py;
    const d2 = dx * dx + dy * dy; // squared: same argmin (first index on a tie), no Math.hypot in the loop
    if (d2 < best) {
      best = d2;
      j = k;
    }
  }
  return { node: P.walkNodes[j], m: Math.hypot(wx[j] - px, wy[j] - py) };
}

/** client_route(): the route from (lon, lat) to the best usable shelter in scenario `key` ("<rain>_<enso>"). */
export function clientRoute(
  P: PreparedGraph,
  key: string,
  lon: number,
  lat: number,
  penalty?: number,
  /** Python `kinds`: only targets of these kinds (absent kind = "shelter"); undefined = every target */
  kinds?: ReadonlySet<string>,
): RouteResult {
  const g = P.g;
  const pen = penalty ?? g.near_penalty;
  const ki = g.scenarios.indexOf(key);
  if (ki < 0) throw new Error(`graph.json has no scenario ${key}`);
  // 1. snap
  const { node: src, m: snapO } = snapStart(P, lon, lat);
  const A = adjacency(P, ki, pen);
  if (A.start[src] === A.start[src + 1]) return { ok: false, reason: "cut_off" };
  // 2. targets
  const vms = g.walk_kph / 3.6;
  const at = new Map<number, GraphShelter[]>();
  for (const s of g.shelters) {
    if (!((s.usable >> ki) & 1) || (kinds && !kinds.has(s.kind ?? "shelter"))) continue;
    const l = at.get(s.node);
    if (l) l.push(s);
    else at.set(s.node, [s]);
  }
  if (!at.size) return { ok: false, reason: "no_usable_shelter" };
  // 3. one Dijkstra, early exit at the first settled shelter
  const nn = g.nodes.length / 2;
  const dist = new Float64Array(nn).fill(Infinity);
  const tru = new Float64Array(nn);
  const prevNode = new Int32Array(nn).fill(-1);
  const prevEdge = new Int32Array(nn).fill(-1);
  const done = new Uint8Array(nn);
  dist[src] = 0;
  const pq = new MinHeap();
  pq.push({ c: 0, kind: 0, sid: "", node: src });
  for (let e = pq.pop(); e; e = pq.pop()) {
    const x = e.node;
    if (e.kind === 1) {
      const s = at.get(x)!.find((y) => y.id === e.sid)!;
      const edges: number[] = [];
      const nodes: number[] = [x];
      for (let y = x; y !== src; y = prevNode[y]) {
        edges.push(prevEdge[y]);
        nodes.push(prevNode[y]);
      }
      edges.reverse();
      nodes.reverse();
      const sec = tru[x] / 10 + (snapO + s.snap_m) / vms;
      // 4. minutes: Python int(math.ceil(round(sec / 60.0, 6)))
      const minutes = Math.ceil(roundHalfEven(sec / 60, 6));
      return { ok: true, shelter: s, minutes, edges, costS: e.c / 10 + snapO / vms, snapM: [snapO, s.snap_m], coords: pathCoords(g, lon, lat, nodes, edges, s) };
    }
    if (e.c > dist[x] || done[x]) continue;
    done[x] = 1;
    for (const s of at.get(x) ?? []) pq.push({ c: e.c + (10 * s.snap_m) / vms, kind: 1, sid: s.id, node: x });
    for (let k = A.start[x]; k < A.start[x + 1]; k++) {
      const y = A.to[k];
      const c = e.c + A.cost[k];
      if (c < dist[y]) {
        dist[y] = c;
        tru[y] = tru[x] + A.t[k];
        prevNode[y] = x;
        prevEdge[y] = A.edge[k];
        pq.push({ c, kind: 0, sid: "", node: y });
      }
    }
  }
  return { ok: false, reason: "unreachable" };
}

// ---------------------------------------------------------------------------------------------
// RULING R20: client_answers() -- what the app shows for a point (port of the Python reference at exposure e972b7e)
// ---------------------------------------------------------------------------------------------
/** rural households move to high ground; traders go to a shelter (Python RELOCATION_USER_TYPES) */
export const RELOCATION_USER_TYPES: ReadonlySet<string> = new Set(["settler", "farmer"]);
export type TargetKind = "shelter" | "relocation";
export type Answer =
  | { ok: true; primary: RouteOk; safer?: RouteOk & { extraMin: number } }
  | { ok: false; reason: RouteRefusal };

/**
 * client_answers(): a preset origin passes its user type and gets ONE answer, of the kind its published card uses
 * ("relocation" for settler/farmer when the graph has relocation targets, else "shelter"); a free tap (no user type)
 * gets "shelter" (refuge now) and, where relocation targets exist, "relocation" (high ground).
 * Each answer: PRIMARY = the fastest safe route (flooded edges excluded, penalty 1: the published cards); SAFER = the
 * route with near-flood edges costed x near_penalty, only when its target or edges differ, with extraMin.
 */
export function clientAnswers(P: PreparedGraph, key: string, lon: number, lat: number, userType?: string): Partial<Record<TargetKind, Answer>> {
  const hasRel = relocationTargets(P.g) > 0;
  const wants: TargetKind[] =
    userType !== undefined ? [RELOCATION_USER_TYPES.has(userType) && hasRel ? "relocation" : "shelter"] : hasRel ? ["shelter", "relocation"] : ["shelter"];
  const out: Partial<Record<TargetKind, Answer>> = {};
  for (const kind of wants) {
    const kinds = new Set([kind]);
    const p = clientRoute(P, key, lon, lat, 1.0, kinds);
    if (!p.ok) {
      out[kind] = { ok: false, reason: p.reason };
      continue;
    }
    const ans: Answer = { ok: true, primary: p };
    const s = clientRoute(P, key, lon, lat, undefined, kinds);
    if (s.ok && (s.shelter.id !== p.shelter.id || !sameEdges(s.edges, p.edges))) ans.safer = { ...s, extraMin: s.minutes - p.minutes };
    out[kind] = ans;
  }
  return out;
}

const sameEdges = (a: number[], b: number[]) => a.length === b.length && a.every((x, i) => x === b[i]);

// ---------------------------------------------------------------------------------------------
// M-16: FROM -> TO with up to 3 alternatives (no Python card to match: checked against an independent scipy Dijkstra)
// ---------------------------------------------------------------------------------------------
export type TripPoint = { lon: number; lat: number; /** a graph target id: use its node and snap leg, as the answers do */ targetId?: string };
export type AltLabel = "fastest" | "safer" | "alternative";
export interface TripAlt {
  label: AltLabel;
  minutes: number;
  /** network metres: edges (true time x walking speed) + both snap legs */
  metres: number;
  /** metres of the path on edges NEAR the flood in this scenario (graph near bit: within 30 m of a wet cell) */
  nearM: number;
  /** minutes more than the fastest */
  extraMin: number;
  /** share of this path's edge metres that the fastest path also uses (0 for the fastest itself) */
  overlap: number;
  edges: number[];
  coords: [number, number][];
}
export type TripRefusal = "far_start" | "far_dest" | "cut_off_start" | "cut_off_dest" | "unreachable";
export type TripResult = { ok: true; alts: TripAlt[]; snapM: [number, number] } | { ok: false; reason: TripRefusal };
/** CHOICE (M-16): a third route is kept only when less than this share of its edge metres is shared with the fastest. */
export const MAX_ALT_OVERLAP = 0.5;
/** CHOICE (M-16): the third route = fastest safe search with the fastest route's edges costed x this. */
export const ALT_EDGE_FACTOR = 2;

/** Dijkstra from src to dst on scenario `ki`; cost = deciseconds x pen on near edges x mul[edge]; flooded edges absent. */
function searchTo(P: PreparedGraph, ki: number, pen: number, src: number, dst: number, mul?: Map<number, number>) {
  const A = adjacency(P, ki, pen);
  const nn = P.g.nodes.length / 2;
  const dist = new Float64Array(nn).fill(Infinity);
  const tru = new Float64Array(nn);
  const prevNode = new Int32Array(nn).fill(-1);
  const prevEdge = new Int32Array(nn).fill(-1);
  const done = new Uint8Array(nn);
  dist[src] = 0;
  const pq = new MinHeap();
  pq.push({ c: 0, kind: 0, sid: "", node: src });
  for (let e = pq.pop(); e; e = pq.pop()) {
    const x = e.node;
    if (e.c > dist[x] || done[x]) continue;
    done[x] = 1;
    if (x === dst) {
      const edges: number[] = [];
      const nodes: number[] = [x];
      for (let y = x; y !== src; y = prevNode[y]) {
        edges.push(prevEdge[y]);
        nodes.push(prevNode[y]);
      }
      return { edges: edges.reverse(), nodes: nodes.reverse(), ds: tru[x] };
    }
    for (let k = A.start[x]; k < A.start[x + 1]; k++) {
      const y = A.to[k];
      const c = e.c + A.cost[k] * (mul?.get(A.edge[k]) ?? 1);
      if (c < dist[y]) {
        dist[y] = c;
        tru[y] = tru[x] + A.t[k];
        prevNode[y] = x;
        prevEdge[y] = A.edge[k];
        pq.push({ c, kind: 0, sid: "", node: y });
      }
    }
  }
  return null;
}

/**
 * M-16 FROM -> TO on foot in scenario `key`, flooded edges never used. Up to 3 alternatives:
 *   1. fastest: penalty 1 (RULING R20: the primary is the fastest safe route)
 *   2. safer:   near-flood edges x near_penalty (R20's "safer" alternative), kept when its edges differ
 *   3. alternative: penalty 1 with route 1's edges x ALT_EDGE_FACTOR, kept when it differs from 1 and 2 and shares
 *      less than MAX_ALT_OVERLAP of its edge metres with route 1
 * Start and destination snap to the nearest walk node (a graph target uses its own node and snap leg); further than
 * max_dest_snap_m -> refused. Wet start / destination are checked by the caller against the flood polygons.
 */
export function routeBetween(P: PreparedGraph, key: string, from: TripPoint, to: TripPoint): TripResult {
  const g = P.g;
  const ki = g.scenarios.indexOf(key);
  if (ki < 0) throw new Error(`graph.json has no scenario ${key}`);
  const vms = g.walk_kph / 3.6;
  const a = snapStart(P, from.lon, from.lat);
  if (a.m > g.max_dest_snap_m) return { ok: false, reason: "far_start" };
  const t = to.targetId ? g.shelters.find((s) => s.id === to.targetId) : undefined;
  const b = t ? { node: t.node, m: t.snap_m } : snapStart(P, to.lon, to.lat);
  if (b.m > g.max_dest_snap_m) return { ok: false, reason: "far_dest" };
  const A1 = adjacency(P, ki, 1);
  const open = (n: number) => A1.start[n] !== A1.start[n + 1];
  if (!open(a.node)) return { ok: false, reason: "cut_off_start" };
  if (!open(b.node)) return { ok: false, reason: "cut_off_dest" };
  const { edges: E, near: N } = g.walk;
  const edgeM = (i: number) => (E[3 * i + 2] / 10) * vms;
  const legs = a.m + b.m;
  const make = (label: AltLabel, r: { edges: number[]; nodes: number[]; ds: number }, base?: TripAlt): TripAlt => {
    const sec = r.ds / 10 + legs / vms;
    const em = r.edges.reduce((s, i) => s + edgeM(i), 0);
    const inBase = base ? new Set(base.edges) : null;
    const shared = inBase ? r.edges.reduce((s, i) => s + (inBase.has(i) ? edgeM(i) : 0), 0) : 0;
    const minutes = Math.ceil(roundHalfEven(sec / 60, 6));
    return {
      label,
      minutes,
      metres: em + legs,
      nearM: r.edges.reduce((s, i) => s + ((N[i] >> ki) & 1 ? edgeM(i) : 0), 0),
      extraMin: base ? minutes - base.minutes : 0,
      overlap: base && em > 0 ? shared / em : 0,
      edges: r.edges,
      coords: lineCoords(g, [from.lon, from.lat], r.nodes, r.edges, t ? [t.lon, t.lat] : [to.lon, to.lat]),
    };
  };
  const r1 = searchTo(P, ki, 1, a.node, b.node);
  if (!r1) return { ok: false, reason: "unreachable" };
  const fastest = make("fastest", r1);
  const alts = [fastest];
  const r2 = searchTo(P, ki, g.near_penalty, a.node, b.node);
  if (r2 && !sameEdges(r2.edges, r1.edges)) alts.push(make("safer", r2, fastest));
  if (r1.edges.length) {
    const r3 = searchTo(P, ki, 1, a.node, b.node, new Map(r1.edges.map((i) => [i, ALT_EDGE_FACTOR])));
    if (r3 && alts.every((x) => !sameEdges(x.edges, r3.edges))) {
      const alt = make("alternative", r3, fastest);
      if (alt.overlap < MAX_ALT_OVERLAP) alts.push(alt);
    }
  }
  return { ok: true, alts, snapM: [a.m, b.m] };
}

/** Python's round(x, nd) for the values used here (round-half-even on the decimal value; ties are vanishingly rare). */
function roundHalfEven(x: number, nd: number): number {
  const f = 10 ** nd;
  const y = x * f;
  const r = Math.round(y);
  return (Math.abs(y - Math.trunc(y)) === 0.5 && r % 2 !== 0 ? r - 1 : r) / f;
}

/** The drawn line: tap, start node, each edge's interior vertices in the direction travelled, the shelter. */
function pathCoords(g: GraphJson, lon: number, lat: number, nodes: number[], edges: number[], s: GraphShelter): [number, number][] {
  return lineCoords(g, [lon, lat], nodes, edges, [s.lon, s.lat]);
}
function lineCoords(g: GraphJson, start: [number, number], nodes: number[], edges: number[], end: [number, number]): [number, number][] {
  const pt = (n: number): [number, number] => [g.nodes[2 * n], g.nodes[2 * n + 1]];
  const out: [number, number][] = [start, pt(nodes[0])];
  edges.forEach((i, k) => {
    const a = nodes[k];
    const flat = g.walk.geom[i];
    const pts: [number, number][] = [];
    for (let q = 0; q < flat.length; q += 2) pts.push([flat[q], flat[q + 1]]);
    if (g.walk.edges[3 * i] !== a) pts.reverse(); // geom is oriented u -> v
    out.push(...pts, pt(nodes[k + 1]));
  });
  out.push(end);
  return out;
}

const graphs = new Map<string, Promise<PreparedGraph>>();
/** Fetch and prepare an area's graph once per page (a failure is not cached). */
export function loadGraph(area: string): Promise<PreparedGraph> {
  const hit = graphs.get(area);
  if (hit) return hit;
  const p = fetch(`/data/${area}/graph.json`)
    .then((r) => {
      if (!r.ok) throw new Error(`graph.json HTTP ${r.status}`);
      return r.json();
    })
    .then((j) => {
      const g = checkGraph(j);
      if (g.area !== area) throw new Error(`graph.json is for ${g.area}, not ${area}`);
      return prepareGraph(g);
    });
  graphs.set(area, p);
  p.catch(() => graphs.delete(area));
  return p;
}
