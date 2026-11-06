# Charter — model  (branch `a/model`)

**Role:** Person A's terrain and flood-model lead. You turn free planetary data into a calibrated,
screening-level flood-depth map per scenario for Nyando (rural) and Nairobi (urban), and you prove
how good it is against a real observed flood. Plan sections 3, 4.1–4.6.

**Worktree:** `/Users/mac/IGAD/rms-model` · **Auditor:** `/Users/mac/IGAD/rms-model-audit` ·
**Round log:** `/Users/mac/IGAD/rms-audit/model.md` · **Queue:** `/Users/mac/IGAD/rms-audit/tasks/model.md`

**You own:** `configs/**`, `pipeline/lib/**`, `pipeline/01_ee_export.py`, `02_terrain.py`,
`03_runoff_flood.py`, `04_backtest.py`, `08_susceptibility.py`, `pipeline/tests/test_{config,terrain,runoff,flood,backtest}*.py`,
`docs/slides/figures/{methods,backtest}*`, and `$RMS_DATA/{raw,processed}/<area>/model/**`.
**You never touch:** `web/**`, `pipeline/05–07_*`, anything under `processed/<area>/exposure/`.

## Done-criteria per task (an auditor ACCEPT needs all of them)

- **M-01** `configs/*.yaml` per plan §3 (bbox, dem, backtest_event, before_period, user_types, utm_epsg).
  Each bbox printed with its area in km² and a quick-look PNG over OSM tiles or a coastline so a human
  can see it is the right place (Nyando/Kano plains; Nairobi River corridor, ≤ ~15×15 km). The UTM
  EPSG is derived from the bbox centre, not typed in. `pipeline/lib/` reads `$RMS_DATA` (default
  `../data` from the repo root = `/Users/mac/IGAD/data`). `.venv/bin/python -m pytest -q` runs ≥ 1 real test.
- **M-02** Exports land in `$RMS_DATA/raw/nyando/`, each with a sidecar `.json` (asset id or URL, date
  range, scale, CRS, retrieval time). Every EE asset id is checked against the catalog **in code**
  (`ee.data.getAsset`) before export, because the plan's ids are marked *(verify)*. Each raster checked:
  right bounds, no all-NaN tiles, sensible value range (print min/max/nodata share).
  **If Earth Engine is not authenticated** (human step, see AGENTS.md): say so to the operator once,
  then do not wait — fetch what does not need EE (Copernicus GLO-30 DEM tiles from the public
  `copernicus-dem-30m` AWS bucket, ESA WorldCover from the public `esa-worldcover` bucket, CHIRPS from
  data.chc.ucsb.edu, WorldPop from worldpop.org) and mark the Sentinel-1 mask BLOCKED:ee-auth.
- **M-03** pysheds pipeline in UTM metres. Tests on a synthetic DEM (a tilted plane with a carved
  channel) where HAND has a known answer. Sanity PNGs of HAND, slope, channels. Channel threshold
  stated and justified (compare channels against OSM waterways or JRC water: what share overlaps?).
- **M-04** SCS: `S = 25400/CN − 254`, `Q = (P − 0.2S)²/(P + 0.8S)` for `P > 0.2S`, else 0 — unit
  tests with hand-calculated values. CN table from TR-55 with the citation in code. Flood mask: HAND <
  h, slope < 15°, connected to a channel, permanent water excluded. Depth = h − HAND. Risk per
  `docs/DATA_CONTRACT.md`: < 0.3 m low, 0.3–1 m medium, > 1 m high. El Niño = CHIRPS ratio (event
  season / multi-year mean for the same months), number and years stated.
- **M-05** Calibrate k on the Sentinel-1 2023 mask (event dates verified from a source — ICPAC/OCHA/
  Copernicus EMS — URL in the round). Report F1, IoU, precision, recall, the chosen k and α, and the
  side-by-side figure. A modest score reported honestly beats a good one nobody can reproduce. Hold
  out something (time or space) if there is any way to; say so if there is not.
- **M-06** The hand-off in AGENTS.md § model → exposure interface, exactly. Exposure starts its real
  run from it, so a wrong CRS here costs the demo.
- **M-07** As M-02..M-06 for Nairobi. State which DEM was used and why.
- **M-08 / M-09** Tier 2. Only once M-07 is ACCEPTed and the operator has not cut them.
- **M-10** Figures under `docs/slides/figures/`, each with a caption stating the source data and that
  it is screening-level. A data-sources table with licences/attribution (Copernicus, CHIRPS, ESA,
  WorldPop, JRC, Google Open Buildings, OSM).

## Lessons log

Append in the same commit as the change that taught it. Newest at the bottom.

- 2026-11-05 Grid created. Nothing learned yet.
- 2026-11-05 (M-01) After a same-second `sed` revert of a fault injection, pytest kept running the
  faulted code: the stale `.pyc` has the same mtime second and size. `find pipeline -name __pycache__
  -exec rm -rf {} +` after any inject/revert before trusting the re-run.
- 2026-11-05 (M-01) Public Overpass was at capacity (502) and the kumi mirror returned empty; Nominatim
  (`polygon_geojson=1`, `limit=10`) works for river geometry but rate-limits fast (429) — cache every
  response and back off. A river is many OSM ways: take them all, not the first hit (the first Nyando
  hit was only the upper reach). Nominatim's "Muhoroni" landed ~13 km from the town the OSM tiles
  label: geocodes are pins to eyeball, never assertions.
- 2026-11-06 (M-02) No-EE sources, as of today: CHIRPS moved from `products/CHIRPS-2.0/` (404) to
  `products/CHIRPS/v2.0/`; its 3-monthly product starts only in 2015, so seasonal climatology comes from
  monthly files; CHC answers 429 at 4 parallel workers (2 is fine). worldpop.org refuses byte ranges on
  GET (HEAD says `Accept-Ranges: bytes`, GET resume -> curl rc=33; GDAL /vsicurl/ -> "Range downloading
  not supported"), so the 312 MB Kenya file must come down in one unbroken transfer; `curl` exited 0
  with a truncated file overnight — always compare against Content-Length. GLO-30/WorldCover/JRC COGs
  read fine by window over /vsicurl/.
- 2026-11-06 (M-02/M-03) pysheds 0.5 calls np.in1d, removed in numpy 2.4; this venv has numpy 2.5.
  Shimmed in pipeline/lib/terrain.py (lands with M-03), not by downgrading the shared venv.
- 2026-11-06 (M-03) HAND came out NaN on ~8,600 AOI cells of the Kano plains (the floodplain that matters):
  their D8 paths end in interior cells pysheds cannot route (flowdir -2 unresolved flat / -1 / 0) near
  the lake shore, and never reach a channel cell. Treating those cells as drainage terminals ("sinks")
  and permanent water (JRC >= 80 %) as drainage gives AOI NaN share 0.0. Look at the HAND PNG for holes
  every run; the percentile summary hides them.
- 2026-11-06 (M-03) GLO-30 is a DSM: forest canopy dams valleys, so depression filling reaches 75.8 m in
  0.01-0.2 km2 pits in the Nandi/Mau forests (outside the AOI; inside it, max 20.9 m, 6.98 km2 > 1 m).
  JRC water overlap cannot choose a channel threshold (3-6 % at every threshold); OSM river|stream can.
- 2026-11-06 (F3.5) pysheds' resolve_flats nudges nodata cells off -9999 (e.g. -9998.99...), so masking
  `cond == -9999` missed 6,694 of 8,317 cells. Mask outputs by the INPUT DEM's validity, and test with a
  multi-cell NaN hole, not a single cell. Also: pysheds' flowdir uses -1/-2/0 as real codes — never as a
  GeoTIFF nodata tag (now -32768).
- 2026-11-06 (F2.1, R2 REJECT) GLO-30 COG tiles are pixel-CENTRE registered on whole degrees (tile edge at
  35.0 - 0.5 px). `rasterio.merge(bounds=...)` anchors the output at the given bounds, so clipping at 34.70
  shifted every DEM value half a pixel (~15 m W, ~15 m N) and M-03 inherited it. WorldPop (origin
  33.909583) likewise. Clip only on the source's native pixel edges (fetch.snap_bounds) and check
  grid_phase_px == integers; never assume a box edge is a pixel edge — read the native transform.
- 2026-11-06 (F3.21) After the DEM moved onto its native grid the upper Nyando (1,592 km²) dead-ended at
  one cell near Muhoroni: pysheds `fill_pits/fill_depressions` + `resolve_flats` left 265→137 unroutable
  cells, and resolve_flats lifted a filled flat 0.12 m ABOVE its own outlet cell, recreating the pit. Fix:
  priority-free fill by morphological reconstruction (skimage, seeds = edge/perm water), no resolve_flats,
  then BFS routing of flats toward cells whose path terminates at an edge/outlet/nodata. Check routing by
  WALKING the main stem to the mouth and comparing upstream area to a published basin area — a pretty
  HAND map does not prove connectivity.
- 2026-11-06 (F2.10) pysheds compute_hand measures on the FILLED surface: inside a filled depression HAND is
  overstated by the fill depth (Kano plain: up to 20.9 m), so depressions look safe. hand = raw dem − filled
  elevation of the drainage cell (via hand_index), floored at 0; hand_filled.tif kept for comparison.
  Also: audit:findings ignores any `Fx.y CLOSED` line containing "routed"/"routing" (anti-hand-off rule) —
  say "flow path" in a CLOSED line about flow routing.
- 2026-11-06 (M-06) "Which commit produced this raster" is NOT `git log -1 -- script.py`: a later refactor of the
  script claims rasters it never made, and a run from a dirty tree matches no commit. Outputs now carry
  provenance {git_commit, dirty} stamped by the producing run; 06_handoff.py refuses a missing or dirty stamp.
  Commit FIRST, then run, and do not edit pipeline/ while a stamped run is going.
- 2026-11-06 (F4.2) h = k·Q^α with Q a mean runoff DEPTH gives every channel the same stage (uniform CN → uniform
  Q): a 10 km² stream flooded like the 3,422 km² main stem. Stage must scale with a discharge proxy (upstream
  runoff VOLUME), α 0.4 (Leopold & Maddock 1953). Check a stage model by tabulating stage vs upstream area.
  Also: stamp provenance at the START of a run — a stamp taken after 13 min of compute saw my later edits.
- 2026-11-06 (M-06) JRC occurrence >= 80 % misses lake margins: 5.22 km² of Lake Victoria (WorldCover 80, GLO-30
  flattened at 1133.00 m, JRC 69 %) showed as "flooded" in every scenario. Water = JRC >= 80 OR WorldCover 80.
  A flood patch with straight edges and one DEM value is a water body, not a floodplain — look at the map.
- 2026-11-06 (operator ruling) Rewriting hand-off rasters in place while exposure read them gave exposure a mix of
  two versions. 02/03 now refuse when a posted hand-off names the area's rasters, unless --rewrite-posted (only
  after telling the operator "about to rewrite <area> rasters"); re-post the hand-off right after. The hand-off
  table carries FULL sha256 + exact bytes: exposure snapshots and verifies copies against it.
