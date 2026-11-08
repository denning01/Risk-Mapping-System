// F15.3 · the client reads graph.json v3 (E-19: every target has a kind, Nyando's ranked relocation sites added).
//  (1) always: a synthetic v3 built in memory from the app's v2 file is accepted; a v3 target without a kind and an
//      unknown version are refused.
//  (2) when the real exports are on this machine ($RMS_DATA, default /Users/mac/IGAD/data): both v3 files are accepted;
//      Nyando has relocation targets; clientAnswers with each preset's user type reproduces EVERY published card,
//      to_shelter AND relocation (target + minutes); a free tap at a Nyando preset gets two answers.
//      Skipped, with the reason, where the exports are absent (the app still ships v2 until the operator says E-19 is in).
import { expect, test } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { checkGraph, clientAnswers, prepareGraph, relocationTargets, type GraphJson } from "../web/src/lib/routing";
import { ENSOS, RAINS, areas, readJson } from "./helpers";

const RMS_DATA = process.env.RMS_DATA ?? "/Users/mac/IGAD/data";
/** the E-19 exports (exposure ROUND 20; rewritten in place as v3 under the E-16 snapshot folders, auditor F15.2) */
const V3: Record<string, string> = {
  nairobi: join(RMS_DATA, "processed/nairobi/exposure/graph/856ad74/graph.json"),
  nyando: join(RMS_DATA, "processed/nyando/exposure/graph/56322d6/graph.json"),
};

test("a synthetic v3 is accepted; a v3 target without a kind and version 4 are refused", () => {
  const v2 = readJson<GraphJson>("nyando/graph.json");
  const s0 = v2.shelters[0];
  const v3 = {
    ...v2,
    version: 3,
    shelters: [...v2.shelters.map((s) => ({ ...s, kind: "shelter" })), { ...s0, id: "hg-test", kind: "relocation", name: "High ground test" }],
  };
  const g = checkGraph(v3);
  expect(relocationTargets(g)).toBe(1);
  expect(() => checkGraph({ ...v3, shelters: [...v3.shelters, { ...s0, id: "no-kind", kind: undefined }] })).toThrow(/v3 target no-kind has no kind/);
  expect(() => checkGraph({ ...v3, version: 4 })).toThrow(/version 4, expected 2 or 3/);
  expect(() => checkGraph({ ...v2, version: 2 })).not.toThrow();
});

test("the real v3 exports: accepted, Nyando has relocation targets, every published card reproduced (64 + 90)", () => {
  test.skip(!Object.values(V3).every(existsSync), `v3 exports not on this machine (${RMS_DATA})`);
  const counts: Record<string, number> = {};
  for (const area of areas()) {
    const g = checkGraph(JSON.parse(readFileSync(V3[area.id], "utf8")));
    expect(g.version).toBe(3);
    expect(g.area).toBe(area.id);
    expect(relocationTargets(g)).toBe(area.id === "nyando" ? 6 : 0);
    const P = prepareGraph(g);
    const origins = readJson<{ id: string; lon: number; lat: number; user_type: string }[]>(`${area.id}/origins.json`);
    for (const rain of RAINS)
      for (const enso of ENSOS) {
        const key = `${rain}_${enso}`;
        const routes = readJson<{ origin_id: string; kind: string; shelter_id: string | null; safe: { minutes: number } }[]>(`${area.id}/scenarios/${key}.routes.json`);
        for (const row of routes.filter((x) => x.kind !== "commute")) {
          const o = origins.find((x) => x.id === row.origin_id)!;
          const kind = row.kind === "relocation" ? "relocation" : "shelter";
          const ans = clientAnswers(P, key, o.lon, o.lat, o.user_type);
          const where = `${area.id} ${key} ${o.id} ${o.user_type}`;
          expect(Object.keys(ans), where).toEqual([kind]);
          const a = ans[kind]!;
          expect(a.ok, where).toBe(true);
          if (!a.ok) continue;
          expect([a.primary.shelter.id, a.primary.shelter.kind, a.primary.minutes], where).toEqual([row.shelter_id, kind, row.safe.minutes]);
          counts[area.id] = (counts[area.id] ?? 0) + 1;
        }
        if (area.id === "nyando")
          for (const o of origins) expect(Object.keys(clientAnswers(P, key, o.lon, o.lat)), `${key} ${o.id} free tap`).toEqual(["shelter", "relocation"]);
      }
  }
  expect(counts).toEqual({ nairobi: 64, nyando: 90 });
});
