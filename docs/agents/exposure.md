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
- 2026-11-06 (E-02) osmnx simplification returns list-valued attributes (`highway`, `name`, ...) in SET order, which
  changes with PYTHONHASHSEED; anything that takes element [0] (osmnx add_edge_speeds does) is non-reproducible.
  Same counts across runs does not mean same graph: compare sum(travel_time) under two seeds. Fixed by slowest_class.
- 2026-11-06 (E-03) Take an origin's coordinates from its OSM feature (by id), never type them. A large OSM area's
  representative point can sit far from any road (West Kano scheme: 605 m from the drive graph), so check the snap
  distance to both graphs before choosing it. "X market" in mock data is not evidence that an OSM marketplace exists.
- 2026-11-06 (E-04) A flood model's raster can cover a bigger box than the AOI: mask to the AOI BEFORE counting km2,
  people or buildings (aoi_mask). A test whose rounded output hides a 12-vs-8 cell difference is not a test.
- 2026-11-06 (E-04/E-06) Never read a model directory in place: it was rewritten mid-run (10:38-10:39) and produced a
  silent mix of two model versions. `07_scenarios.py snapshot` copies + sha256-checks first; read only the copy.
- 2026-11-06 (E-04) Unconstrained WorldPop (ken_ppp_2020) puts ~41 % of Nyando's people in pixels with no building, so
  flood exposure in farmland came out ~6x too high (16 vs 2-3 people per flooded building). Sanity-check people per
  flooded building against the AOI average. Weight by building footprint area (W2) instead.
- 2026-11-06 (E-04) A rural AOI can span several counties (Nyando: Kisumu 47 %, Kericho 40 %); population.json has one.
  Measure the county shares before scaling. data.worldpop.org has no HTTP range support and drops long downloads:
  start the 300 MB national file early; the 1 km aggregate (3 MB) is enough for county-level sums.
- 2026-11-06 Use `date` for ROUND timestamps; a guessed timestamp needed an erratum.
- 2026-11-06 (E-05) Never "snap to the nearest node that still has an uncut edge": when the origin's own node is cut off,
  that node can be 1-1.5 km away and the route draws a straight line through the water. Snap on the unflooded graph,
  then refuse (report unreachable) if that node is cut off or the snap leg is wet. Found only by resampling the WRITTEN
  LineStrings against the raster (a second method); every unit test was green.
- 2026-11-06 (E-05) A HAND flood raster marks the river cell under a bridge as wet, so every river crossing (even the
  elevated Nairobi Expressway) gets "cut". Exempt samples on OSM bridge WAYS (raw XML), not bridge-tagged graph EDGES:
  osmnx simplification merges approach roads into the bridge edge (Nyando: median 468 m, max 7 km).
- 2026-11-06 (E-05) Don't diagnose a DEM bias from one transect. I called Ahero's 12-14 m HAND "rooftops" from a spike
  between 4-6 m cells; model measured GLO-30 vs bare-earth FABDEM on Ahero building pixels: only 0.8 m (p50) / 1.8 m
  (p90). The surface-model bias is ~1-2 m (HAND overstated, depth understated on buildings); ask model for the
  DSM-minus-DTM difference before writing a limitation. Nairobi uses FABDEM; Nyando GLO-30.
- 2026-11-06 (E-06) "polygon km2 = pixel km2" was measured BEFORE simplification, so it could not see what
  simplification did: at 20 m the DRAWN Nyando polygons were +0.12 % (Douglas-Peucker cuts staircase corners once the
  tolerance passes ~19 m); at 18 m +0.004 %. The writer now prints the drawn area. A symmetric test shape hides it (the
  errors cancel); use an asymmetric notch. Don't promise a number you read from the wrong column.
- 2026-11-06 A zsh helper with "${3:+--flag $3}" passes "--flag value" as ONE word (no word splitting), argparse rejects
  it, and an `echo exit=$?` after a redirect can still print 0. Write landing commands out in full.
- 2026-11-06 (E-08) A slide doc drafted from memory of the data over-claims. "Loses 4 segments from 150 mm" was really 3 at
  100–150 and 4 from 200, and the river names were never measured. Check every sentence against routes_check / the JSON,
  and match the tables to the files by script (all 20 rows), before committing. Reported impacts: IFRC GO PDFs
  (go-api.ifrc.org/api/DownloadFile/…) are fetchable primary sources when ReliefWeb/OCHA return 403.
- 2026-11-06 (R5 audit) A fixture whose only wet buildings sit in the MEDIUM block cannot tell "depth > 0" from "depth > 0.3":
  put a building in every class you claim to count. A fixture that already equals the right answer (old year = manifest
  year) cannot catch carrying the wrong one; make them differ. "Downloaded this round" in EVIDENCE must mean a file under
  $RMS_DATA with its sha256, not a scratchpad copy.
- 2026-11-07 (R6 F6.5) "Sample every 15 m along the edge" is not "every cell gets a sample": sampling at fractions of
  the whole edge skips interior vertices, and a line can clip a cell corner between samples. Missed 2-8 % of wet edges
  on the model floods, with every test green, because no fixture put a VERTEX or a CORNER CLIP in a wet cell. Sample every
  vertex plus <= s m: then any wet stretch longer than s m is caught (straight between vertices), which is provable.
  Test the exactness with a fixture that the coarser rule demonstrably misses (assert that as a precondition). At 0.5 m
  the walk graph is 19.5 M samples: compute the bridge exemption only on edges near a bridge, never on every sample.
