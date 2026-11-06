# Charter — exposure  (branch `a/exposure`)

**Role:** Person A's people-and-places lead. You turn flood-depth maps into what the app shows:
who is at risk, where the safe places are, and which way to go — written as the exact files
Person B's app reads. Plan sections 4.7, 4.8, 5, 7; contract: `docs/DATA_CONTRACT.md`.

**Worktree:** `/Users/mac/IGAD/rms-exposure` · **Auditor:** `/Users/mac/IGAD/rms-exposure-audit` ·
**Round log:** `/Users/mac/IGAD/rms-audit/exposure.md` · **Queue:** `/Users/mac/IGAD/rms-audit/tasks/exposure.md`

**You own:** `pipeline/05_population.py`, `06_routing.py`, `07_scenarios.py`,
`pipeline/tests/test_{population,routing,scenarios}*.py`, `$RMS_DATA/{raw/osm,raw/buildings,processed/<area>/exposure}/**`,
and these committed outputs: `web/public/data/areas.json`, `meta.json`, `<area>/origins.json`,
`<area>/scenarios/**`.
**You never touch:** `web/src`, `web/scripts`, `web/package.json`, `web/public/data/advice/**`,
`web/public/data/<area>/population.json` (Person B's), `pipeline/lib/**` or model's scripts (ask the
operator). Model's rasters are read-only to you.

## The contract is the product

`cd web && npm run validate:data` must pass after every round that writes `web/public/data`. If the
contract genuinely needs to change, do not change it — message the operator; the human agrees it with
Person B. The app must keep working with **zero code changes**.

## Done-criteria per task

- **E-01** `07_scenarios.py --area <a> --depth-dir <dir>` writes all four files for every one of the
  20 combinations: polygons dissolved by (risk, arrival bin), simplified, WGS84, each file a few MB at
  most (print sizes). Proven end to end on a stand-in depth raster that you generate and **label MOCK**
  (`"source":"mock"`, `meta.json` stays `"mock": true`). Tests: a tiny synthetic raster → known polygon
  count/area/risk classes. `validate:data` output pasted.
- **E-02** Graph + shelters cached under `$RMS_DATA`. Counts per shelter type per area printed.
  Travel-time assumptions (speeds per highway class, walking speed) stated in code with a source.
- **E-03** 3–6 origins per area, real named places, coordinates checked against OSM (print the
  nearest OSM name and distance), `user_type` valid for the area.
- **E-04** Dasymetric: WorldPop pixels scaled so they sum to Person B's `population.json` totals for
  the projection year (print both sums — they must match). Exposed people = population in flooded
  cells, low/medium/high from B's scenarios. Buildings = Google Open Buildings footprints
  intersecting flooded cells (if not obtainable in time, say so and the operator decides). Year stated.
- **E-05** Edges whose midpoint is in a flooded cell are removed. Nearest shelter that is `safe`
  (outside the extent) per origin. Nairobi commute: baseline vs safe minutes and the avoided road
  names, from the graph, never hard-coded. Nyando relocation: ranking criteria and weights stated.
  A route that cannot be found is reported, not silently dropped.
- **E-06 / E-07** Real runs from model's hand-off (`rms-audit/handoffs/flood-<area>.md` names the
  files and the commit). Plausibility: does exposure grow monotonically with rain? Is El Niño ≥
  normal? Is flooded area believable for the place? Flip `meta.json` `"mock": false` only when all 20
  scenarios for BOTH areas are model output. Then click through in `npm run dev` and say what you saw.
- **E-08** For the slides: exposure numbers with ranges and year, set against reported impacts of the
  real events (OCHA/ICPAC/KNBS sources with URLs). Mismatches explained, not hidden.

## Lessons log

Append in the same commit as the change that taught it. Newest at the bottom.

- 2026-11-05 Grid created. Nothing learned yet.
- 2026-11-05 (E-01) Never pipe a long-running writer into `| head`: SIGPIPE can kill it mid-loop and
  leave a partial output set. Send the full log to a file, then read it.
- 2026-11-05 (E-01) Person B's hand-made mock is not self-consistent: a feature labelled `low` has
  `depth_m: 0.3` (contract: 0.3 m = medium), and `nbi-s4` lies inside a flood polygon yet is `safe:true`
  in 3 Nairobi scenarios. Re-deriving from a raster fixes both; don't "match the mock" blindly.
- 2026-11-05 (E-01) `verify:all` on a clean checkout: tsc fails on `LayoutProps` until `next build` has
  generated `.next/types` (it runs tsc first), and pytest is SKIPPED because `ls` of the missing
  `tests/` glob exits 1. Both reported to the operator; run `.venv/bin/python -m pytest -q` yourself.
- 2026-11-06 (R1 remediation) A test with a symmetric fixture cannot catch a row/col transpose — put the
  wet probe and its transpose on opposite classes. Test each guard on its OWN input (MOCK tag alone,
  carried source alone), not only the case where both trip. File sizes: `du` reports disk blocks (816K),
  not bytes (806231 B = 787.3 KiB); measure with os.path.getsize.
- 2026-11-06 (E-02) Public Overpass was at capacity (main + kumi + private.coffee + mail.ru all failed). Use the
  Geofabrik Kenya extract ($RMS_DATA/raw/osm/kenya-261104.osm.pbf, md5-checked) + pyosmium; one pass ~5 min,
  prepare ~7 min for both areas. curl to Overpass without a UA returns 406.
- 2026-11-06 (E-02) OSM has real tag errors (a residential street tagged "120 mph"): cap tagged maxspeed at 110 km/h.
  Drive times are FREE-FLOW, not congested — say so wherever minutes are shown.
- 2026-11-06 (E-02) GDAL's OSM driver (pyogrio) is a usable independent check, but its default osmconf puts closed
  ways tagged only healthcare=* in `lines`, not `multipolygons`, so it undercounts clinics by design.
- 2026-11-06 (E-02) Rural Nyando is thinly mapped in OSM (60 schools, 15 health facilities in ~2,500 km2) — confirmed by
  two readers, so it is the map, not the code. Relocation in E-05 must not rely on OSM shelters alone.
