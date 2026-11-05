# Tasks — model  (branch a/model) · Person A: terrain, flood model, backtest
# Format: <id> | <state> | <round-or-"-"> | <title>   States: TODO WIP AUDIT DONE BLOCKED:<what>
# Work in order (standing go-ahead). Done-criteria for each id are in docs/agents/model.md.
# Plan cut order if late: M-09 first, then M-08. NEVER cut M-05 (backtest).

M-01 | TODO | - | Skeleton: configs/{nyando,nairobi}.yaml (AOIs checked on a map), pipeline/lib (config, paths, $RMS_DATA, UTM pick), pytest running
M-02 | TODO | - | 01_ee_export.py Nyando: DEM GLO-30, CHIRPS event rain, WorldCover, WorldPop, Sentinel-1 2023 flood mask, JRC permanent water (no-EE fallback for DEM/WorldCover if auth is missing)
M-03 | TODO | - | 02_terrain.py Nyando: fill/flats, D8 flow dir + accumulation, channels, HAND, slope; sanity PNGs; tests on a synthetic DEM
M-04 | TODO | - | 03_runoff_flood.py: CN raster, SCS runoff (hand-checked unit tests), h=k*Q^a, flood mask (HAND<h, slope, connectivity, minus permanent water), depth + risk classes per contract, El Nino ratio from CHIRPS
M-05 | TODO | - | 04_backtest.py Nyando: calibrate k vs Sentinel-1 mask (F1/IoU/precision/recall), side-by-side figure, honest limitations
M-06 | TODO | - | Hand-off: write 10 Nyando depth rasters (5 rain x 2 enso) + hand/channels to $RMS_DATA, post rms-audit/handoffs/flood-nyando.md
M-07 | TODO | - | Nairobi: FABDEM (or GLO-30 fallback, say which), terrain, built-up CN, flood layers, 2024 backtest, hand-off flood-nairobi.md
M-08 | TODO | - | (T2) Manning velocity -> arrival_h per flood cell, added to the hand-off rasters
M-09 | TODO | - | (T2) XGBoost susceptibility: spatial block split, AUC, feature importance, compare to HAND map
M-10 | TODO | - | Slides material: methods figure (HAND/SCS/calibration), backtest figure + score, data-sources table with licences, limitations numbers
