// M-16 + RULING R20 · the JS client in Node (no browser):
//  (1) clientAnswers() == the Python reference client_answers() at exposure e972b7e (fixtures/answers-oracle.json):
//      per kind, primary and safer target, minutes, edge list, extra minutes; refusals by reason.
//  (2) routeBetween() fastest == an independent scipy Dijkstra (fixtures/trip-oracle.json): same minutes, same true
//      walking time (deciseconds), same refusal.
//  (3) properties of every alternative: no flooded edge, a connected path from the start node to the destination node,
//      pairwise different, the safer one never faster and never nearer the flood, the third under 50 % overlap,
//      drawn line no longer than the walked metres.
//  (4) floodNextTo() on a synthetic square: inside, 20 m, 40 m.
import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  MAX_ALT_OVERLAP,
  checkGraph,
  clientAnswers,
  prepareGraph,
  routeBetween,
  snapStart,
  type GraphJson,
  type PreparedGraph,
  type TripAlt,
} from "../web/src/lib/routing";
import { floodNextTo, lineMetres } from "../web/src/lib/tripAnalysis";
import { areas, readJson } from "./helpers";

type PyRoute = { shelter: string; minutes: number; edges: number[]; extra_min?: number };
type PyAnswer = { error?: string; primary?: PyRoute; safer?: PyRoute };
const ANS: { oracle_commit: string; rows: { area: string; key: string; pt: string; lon: number; lat: number; user_type: string | null; answers: Record<string, PyAnswer> }[] } =
  JSON.parse(readFileSync(join(__dirname, "fixtures", "answers-oracle.json"), "utf8"));
type TripRow = { area: string; key: string; pair: number; from: { lon: number; lat: number }; to: { lon: number; lat: number; targetId?: string }; error?: string; ds?: number; minutes?: number; snap_m?: [number, number] };
const TRIP: TripRow[] = JSON.parse(readFileSync(join(__dirname, "fixtures", "trip-oracle.json"), "utf8"));
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

test("the R20 oracle is the reference at exposure e972b7e and covers presets with a user type and free taps", () => {
  expect(ANS.oracle_commit).toBe("e972b7e");
  expect(ANS.rows.filter((r) => r.user_type !== null).length).toBeGreaterThan(100);
  expect(ANS.rows.filter((r) => r.user_type === null).length).toBeGreaterThan(100);
  expect(ANS.rows.some((r) => Object.values(r.answers).some((a) => a.safer))).toBe(true);
});

for (const area of areas()) {
  test(`${area.id}: clientAnswers == Python client_answers (R20) on every oracle point`, () => {
    const P = graph(area.id);
    const rows = ANS.rows.filter((r) => r.area === area.id);
    let primaries = 0;
    let safers = 0;
    for (const o of rows) {
      const got = clientAnswers(P, o.key, o.lon, o.lat, o.user_type ?? undefined);
      const where = `${o.key} ${o.pt} ${o.user_type}`;
      expect(Object.keys(got).sort(), where).toEqual(Object.keys(o.answers).sort());
      for (const [kind, want] of Object.entries(o.answers)) {
        const a = got[kind as "shelter" | "relocation"]!;
        if (want.error) {
          expect(a.ok, where).toBe(false);
          if (!a.ok) expect(a.reason, where).toBe(REFUSAL[want.error]);
          continue;
        }
        expect(a.ok, where).toBe(true);
        if (!a.ok) continue;
        expect([a.primary.shelter.id, a.primary.minutes, a.primary.edges], where).toEqual([want.primary!.shelter, want.primary!.minutes, want.primary!.edges]);
        primaries++;
        if (want.safer) {
          expect(a.safer, where).toBeDefined();
          expect([a.safer!.shelter.id, a.safer!.minutes, a.safer!.edges, a.safer!.extraMin], where).toEqual([
            want.safer.shelter,
            want.safer.minutes,
            want.safer.edges,
            want.safer.extra_min,
          ]);
          safers++;
        } else expect(a.safer, where).toBeUndefined();
      }
    }
    expect(primaries).toBeGreaterThan(100);
    if (area.id === "nairobi") expect(safers).toBeGreaterThan(0);
  });
}

test("routeBetween fastest == scipy Dijkstra on every oracle pair (minutes, true time, refusals)", () => {
  let routed = 0;
  let refused = 0;
  for (const o of TRIP) {
    const P = graph(o.area);
    const r = routeBetween(P, o.key, o.from, o.to);
    const where = `${o.area} ${o.key} pair ${o.pair}`;
    if (o.error) {
      expect(r.ok, where).toBe(false);
      if (!r.ok) expect(r.reason, where).toBe(o.error);
      refused++;
      continue;
    }
    expect(r.ok, where).toBe(true);
    if (!r.ok) continue;
    const f = r.alts[0];
    expect(f.label).toBe("fastest");
    expect(f.minutes, where).toBe(o.minutes);
    expect(f.edges.reduce((s, i) => s + P.g.walk.edges[3 * i + 2], 0), where).toBe(o.ds);
    expect(Math.abs(r.snapM[0] - o.snap_m![0]), where).toBeLessThan(1e-3);
    expect(Math.abs(r.snapM[1] - o.snap_m![1]), where).toBeLessThan(1e-3);
    routed++;
  }
  expect(routed).toBeGreaterThan(80);
  expect(refused).toBeGreaterThan(0);
});

/** every oracle pair plus shelter-to-shelter trips: the alternatives' properties */
test("alternatives: no flooded edge, connected, pairwise different, safer never faster or nearer, third < 50 % overlap, drawn <= walked", () => {
  const counts = { trips: 0, safer: 0, alternative: 0, three: 0 };
  const check = (P: PreparedGraph, key: string, from: { lon: number; lat: number }, to: { lon: number; lat: number; targetId?: string }, where: string) => {
    const r = routeBetween(P, key, from, to);
    if (!r.ok) return;
    counts.trips++;
    const ki = P.g.scenarios.indexOf(key);
    const E = P.g.walk.edges;
    const src = snapStart(P, from.lon, from.lat).node;
    const t = to.targetId ? P.g.shelters.find((s) => s.id === to.targetId)! : null;
    const dst = t ? t.node : snapStart(P, to.lon, to.lat).node;
    const [fast] = r.alts;
    for (const a of r.alts) {
      const w = `${where} ${a.label}`;
      // one assertion per path, not per edge: Playwright's expect is costly per call (277k calls ran for minutes)
      let at = src;
      let flooded = 0;
      let broken = -1;
      a.edges.forEach((i, k) => {
        flooded += (P.g.walk.flooded[i] >> ki) & 1;
        const u = E[3 * i], v = E[3 * i + 1];
        if (broken < 0 && u !== at && v !== at) broken = k;
        at = u === at ? v : u;
      });
      expect({ flooded, broken, end: at }, w).toEqual({ flooded: 0, broken: -1, end: dst });
      expect(lineMetres(a.coords), w).toBeLessThanOrEqual(a.metres * 1.02 + 2);
      expect(a.coords[0], w).toEqual([from.lon, from.lat]);
    }
    const key2 = (a: TripAlt) => a.edges.join(",");
    expect(new Set(r.alts.map(key2)).size, where).toBe(r.alts.length);
    expect(new Set(r.alts.map((a) => a.label)).size, where).toBe(r.alts.length);
    const safer = r.alts.find((a) => a.label === "safer");
    if (safer) {
      counts.safer++;
      expect(safer.minutes, where).toBeGreaterThanOrEqual(fast.minutes);
      expect(safer.extraMin, where).toBe(safer.minutes - fast.minutes);
      expect(safer.nearM, where).toBeLessThanOrEqual(fast.nearM + 1e-9);
    }
    const alt = r.alts.find((a) => a.label === "alternative");
    if (alt) {
      counts.alternative++;
      expect(alt.overlap, where).toBeLessThan(MAX_ALT_OVERLAP);
      expect(alt.minutes, where).toBeGreaterThanOrEqual(fast.minutes);
    }
    if (r.alts.length === 3) counts.three++;
  };
  for (const o of TRIP) check(graph(o.area), o.key, o.from, o.to, `${o.area} ${o.key} pair ${o.pair}`);
  for (const area of areas()) {
    const P = graph(area.id);
    const S = P.g.shelters;
    for (const key of ["50_normal", "250_elnino"])
      for (let i = 0; i < S.length; i += Math.max(1, Math.floor(S.length / 8)))
        for (let j = S.length - 1; j >= 0; j -= Math.max(1, Math.floor(S.length / 6)))
          if (i !== j) check(P, key, { lon: S[i].lon, lat: S[i].lat }, { lon: S[j].lon, lat: S[j].lat, targetId: S[j].id }, `${area.id} ${key} ${S[i].id}->${S[j].id}`);
  }
  console.log("[trip alternatives]", JSON.stringify(counts));
  expect(counts.trips).toBeGreaterThan(100);
  expect(counts.alternative).toBeGreaterThan(0);
  expect(counts.three).toBeGreaterThan(0);
});

test("floodNextTo: a line inside, 20 m from and 40 m from a flood square", () => {
  const lat0 = -1.3;
  const kx = 110574 * Math.cos((lat0 * Math.PI) / 180);
  const dx = (m: number) => m / kx;
  const sq = [[[36.8, lat0], [36.8 + dx(100), lat0], [36.8 + dx(100), lat0 + 100 / 110574], [36.8, lat0 + 100 / 110574], [36.8, lat0]]];
  const flood = {
    type: "FeatureCollection" as const,
    features: [
      { type: "Feature" as const, geometry: { type: "Polygon" as const, coordinates: sq }, properties: { risk: "medium" as const, depth_m: 0.8, arrival_h: null } },
    ],
  };
  const north = (m: number): [number, number][] => [
    [36.8, lat0 + (100 + m) / 110574],
    [36.8 + dx(100), lat0 + (100 + m) / 110574],
  ];
  expect(floodNextTo(flood, north(20))).toEqual({ risk: "medium", depthMax: 0.8, metres: expect.closeTo(100, 0) });
  expect(floodNextTo(flood, north(40))).toBeNull();
  const inside = floodNextTo(flood, [[36.8 + dx(50), lat0 + 50 / 110574], [36.8 + dx(60), lat0 + 50 / 110574]]);
  expect(inside?.risk).toBe("medium");
  expect(inside?.metres).toBeCloseTo(10, 0);
});
