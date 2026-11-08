// M-18 · Esri World Imagery is not clearly allowed for a keyless web demo (Esri's terms need Esri software or an
// ArcGIS account; ROUND 19). This guard fails if an Esri / ArcGIS tile or service host appears anywhere in web/src
// code, so a later change cannot quietly switch the Satellite basemap to it. Comments are allowed to name Esri.
import { expect, test } from "@playwright/test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const SRC = join(__dirname, "..", "web", "src");
const ESRI_HOST = /(arcgisonline\.com|arcgis\.com|server\.arcgisonline|basemaps-api\.arcgis|esri\.com)/i;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? files(p) : /\.(tsx?|jsx?|css|json)$/.test(n) ? [p] : [];
  });
}

/** The source with comments blanked: a host named in a comment (the M-18 note) is not a tile source. */
function code(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
}

test("no Esri / ArcGIS host in web/src code (M-18: keyless use not clearly allowed)", () => {
  const all = files(SRC);
  expect(all.length).toBeGreaterThan(10);
  const hits = all.flatMap((f) =>
    code(readFileSync(f, "utf8"))
      .split("\n")
      .filter((l) => ESRI_HOST.test(l))
      .map((l) => `${f}: ${l.trim()}`),
  );
  expect(hits).toEqual([]);
  // the Satellite source is still EOX
  expect(readFileSync(join(SRC, "components", "FloodMap.tsx"), "utf8")).toContain("tiles.maps.eox.at");
});
