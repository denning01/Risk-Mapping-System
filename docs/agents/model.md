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
