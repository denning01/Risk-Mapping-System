// M-14 · the JS route client (web/src/lib/routing.ts) against its oracles, in Node (no browser):
//  (1) the Python reference client_route() (pipeline/06_routing.py) on every preset and on seeded random taps, every
//      scenario, both areas: fixtures/route-oracle.json, written by fixtures/make_route_oracle.py from the SAME
//      web/public/data/<area>/graph.json. Same shelter, minutes, edge list (edge for edge), snap legs, cost.
//  (2) the published routes.json: every to_shelter route from its preset origin (shelter AND minutes).
import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { MinHeap, checkGraph, clientRoute, prepareGraph, utmProjector, type GraphJson, type PreparedGraph } from "../web/src/lib/routing";
import { RAINS, ENSOS, areas, readJson } from "./helpers";

type Oracle = {
  area: string;
  key: string;
  tap: string;
  lon: number;
  lat: number;
  error?: string;
  shelter?: string;
  minutes?: number;
  edges?: number[];
  cost_s?: number;
  snap_m?: [number, number];
};
/** The M-14 oracle and the published to_shelter routes were made on the v2 targets, which v3 keeps as kind "shelter"
 * (exposure ROUND 20 check A: v3 OSM targets == v2). With v3 in, those comparisons run on that kind. */
const SHELTERS: ReadonlySet<string> = new Set(["shelter"]);
const ORACLE: Oracle[] = JSON.parse(readFileSync(join(__dirname, "fixtures", "route-oracle.json"), "utf8"));
const REFUSAL: Record<string, string> = {
  "nearest road/path node is cut off by the flood": "cut_off",
  "no usable safe shelter in this scenario": "no_usable_shelter",
  "no usable shelter reachable": "unreachable",
};

const prepared = new Map<string, PreparedGraph>();
const graph = (area: string) => {
  if (!prepared.has(area)) prepared.set(area, prepareGraph(checkGraph(readJson<GraphJson>(`${area}/graph.json`))));
  return prepared.get(area)!;
};

test("the binary heap pops in (cost, kind, shelter id, node) order", () => {
  let seed = 7;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);
  const items = Array.from({ length: 2000 }, () => ({
    c: Math.floor(rnd() * 50),
    kind: (rnd() < 0.5 ? 0 : 1) as 0 | 1,
    sid: rnd() < 0.5 ? "" : `s${Math.floor(rnd() * 9)}`,
    node: Math.floor(rnd() * 100),
  }));
  const h = new MinHeap();
  items.forEach((x) => h.push(x));
  const key = (x: (typeof items)[number]) => [x.c, x.kind, x.sid, x.node] as const;
  const want = [...items].sort((a, b) => {
    const [p, q] = [key(a), key(b)];
    for (let i = 0; i < 4; i++) if (p[i] !== q[i]) return p[i] < q[i] ? -1 : 1;
    return 0;
  });
  const got = [];
  for (let e = h.pop(); e; e = h.pop()) got.push(e);
  expect(got.map(key)).toEqual(want.map(key));
});

for (const area of areas()) {
  test(`${area.id}: graph.json is v3 for this area with every scenario; every target has a kind (M-19: v3 copied in)`, () => {
    const g = graph(area.id).g;
    expect(g.area).toBe(area.id);
    expect(g.version).toBe(3);
    const kinds = g.shelters.map((t) => (t as { kind?: string }).kind);
    expect(kinds.every((k) => k === "shelter" || k === "relocation")).toBe(true);
    expect(kinds.filter((k) => k === "relocation").length).toBe(area.id === "nyando" ? 6 : 0);
    expect(g.client_targets).toBe("all_usable");
    expect([...g.scenarios].sort()).toEqual(RAINS.flatMap((r) => ENSOS.map((e) => `${r}_${e}`)).sort());
  });

  test(`${area.id}: the JS client == the Python client_route on every oracle tap (shelter, minutes, edges, snap legs)`, () => {
    const P = graph(area.id);
    const rows = ORACLE.filter((o) => o.area === area.id);
    expect(rows.length).toBeGreaterThan(100);
    let routed = 0;
    let refused = 0;
    for (const o of rows) {
      const r = clientRoute(P, o.key, o.lon, o.lat, undefined, SHELTERS);
      const where = `${o.key} ${o.tap} (${o.lon}, ${o.lat})`;
      if (o.error) {
        expect(r.ok, where).toBe(false);
        if (!r.ok) expect(r.reason, where).toBe(REFUSAL[o.error]);
        refused++;
        continue;
      }
      expect(r.ok, where).toBe(true);
      if (!r.ok) continue;
      expect(r.shelter.id, where).toBe(o.shelter);
      expect(r.minutes, where).toBe(o.minutes);
      expect(r.edges, where).toEqual(o.edges);
      expect(Math.abs(r.snapM[0] - o.snap_m![0]), `${where} tap snap leg (UTM)`).toBeLessThan(1e-3);
      expect(r.snapM[1], where).toBe(o.snap_m![1]);
      expect(Math.abs(r.costS - o.cost_s!), where).toBeLessThan(1e-3);
      // the drawn line starts at the tap and ends at the shelter
      expect(r.coords[0], where).toEqual([o.lon, o.lat]);
      expect(r.coords.at(-1), where).toEqual([r.shelter.lon, r.shelter.lat]);
      routed++;
    }
    expect(routed).toBeGreaterThan(0);
    expect(refused).toBeGreaterThan(0); // both outcomes are exercised
  });
}

test("the JS client reproduces every published to_shelter route from its preset origin (84 = 64 + 20)", () => {
  const counts: Record<string, number> = {};
  for (const area of areas()) {
    const P = graph(area.id);
    const origins = readJson<{ id: string; lon: number; lat: number }[]>(`${area.id}/origins.json`);
    for (const rain of RAINS)
      for (const enso of ENSOS) {
        const key = `${rain}_${enso}`;
        const routes = readJson<{ origin_id: string; kind: string; shelter_id: string | null; safe: { minutes: number } }[]>(
          `${area.id}/scenarios/${key}.routes.json`,
        );
        for (const row of routes.filter((x) => x.kind === "to_shelter")) {
          const o = origins.find((x) => x.id === row.origin_id)!;
          const r = clientRoute(P, key, o.lon, o.lat, undefined, SHELTERS);
          const where = `${area.id} ${key} ${o.id}`;
          expect(r.ok, where).toBe(true);
          if (!r.ok) continue;
          expect(r.shelter.id, where).toBe(row.shelter_id);
          expect(r.minutes, where).toBe(row.safe.minutes);
          counts[area.id] = (counts[area.id] ?? 0) + 1;
        }
      }
  }
  expect(counts).toEqual({ nairobi: 64, nyando: 20 });
});

test("every edge of a client path is open in its scenario, and consecutive edges share a node", () => {
  let checked = 0;
  for (const o of ORACLE.filter((x) => !x.error)) {
    const P = graph(o.area);
    const ki = P.g.scenarios.indexOf(o.key);
    const r = clientRoute(P, o.key, o.lon, o.lat, undefined, SHELTERS);
    if (!r.ok) throw new Error("oracle routed, client did not");
    const E = P.g.walk.edges;
    for (let k = 0; k < r.edges.length; k++) {
      const i = r.edges[k];
      expect((P.g.walk.flooded[i] >> ki) & 1).toBe(0);
      if (k) {
        const a = [E[3 * r.edges[k - 1]], E[3 * r.edges[k - 1] + 1]];
        expect(a.includes(E[3 * i]) || a.includes(E[3 * i + 1])).toBe(true);
      }
      checked++;
    }
  }
  expect(checked).toBeGreaterThan(1000);
});

test("the drawn line follows each edge in the direction travelled (drawn length per edge <= its walking length)", () => {
  // walk_kph 3.6 = 1 m/s, so an edge's deciseconds / 10 is its length in metres (full geometry; the drawn one is
  // simplified, so never longer). An edge drawn backwards zig-zags to ~3x its length.
  let edges = 0;
  for (const o of ORACLE.filter((x) => !x.error)) {
    const P = graph(o.area);
    expect(P.g.walk_kph).toBe(3.6);
    const proj = utmProjector(P.g.utm_epsg);
    const r = clientRoute(P, o.key, o.lon, o.lat, undefined, SHELTERS);
    if (!r.ok) throw new Error("oracle routed, client did not");
    let at = 1; // coords[1] = the start node
    for (const i of r.edges) {
      const n = P.g.walk.geom[i].length / 2 + 1; // interior vertices + the far node
      let len = 0;
      for (let q = at; q < at + n; q++) {
        const [x0, y0] = proj(...r.coords[q]);
        const [x1, y1] = proj(...r.coords[q + 1]);
        len += Math.hypot(x1 - x0, y1 - y0);
      }
      const metres = P.g.walk.edges[3 * i + 2] / 10;
      expect(len, `${o.area} ${o.key} ${o.tap} edge ${i}`).toBeLessThanOrEqual(metres * 1.02 + 2);
      at += n;
      edges++;
    }
    expect(at, "every vertex accounted for: the last node, then the shelter").toBe(r.coords.length - 2);
  }
  expect(edges).toBeGreaterThan(1000);
});
