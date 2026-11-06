# M-10 slide material: model (Person A)

Everything here was taken from files written by audited pipeline runs. Each number gives its value, unit, how it was
computed, the source, and the ROUND that verified it. **Screening-level throughout:** HAND + SCS-CN is a calibrated
terrain-and-runoff approximation, not a hydraulic model. The slider scenarios are "what if this much rain falls in
24 h", not forecasts.

Withdrawn numbers. **Never reuse** "5th of 31" or 1.414; the correct values are 6th of 33 and 1.419 (below).

## Figures (`docs/slides/figures/`)

| file | caption (use as written) | source |
|---|---|---|
| `methods_chain.png` | How the screening model works: terrain (HAND), SCS-CN runoff and a stage rule h = k·V^0.4, with k calibrated against Sentinel-1. Not a hydraulic model; the scenarios are not forecasts. | drawn for M-10 from the parameters in `runoff_flood.json` (k 0.012559, α 0.4) and the ROUND 6 backtest |
| `backtest_nyando.png` | Nyando, November 2023: model (k = 0.0126) against the Sentinel-1 flood mask (UN-SPIDER change detection, VH). F1 0.19, IoU 0.10, precision 0.12, recall 0.46. A terrain-only map (HAND < 1 m, no rainfall) scores F1 0.18. Screening-level. Contains modified Copernicus Sentinel data 2023. | `$RMS_DATA/processed/nyando/model/backtest/backtest.png` (05_backtest.py at 255aab5), sha256 5684830e…; ROUND 6 ACCEPT |
| `backtest_nairobi.png` | Nairobi, April–May 2024: in the city, radar change shows scattered urban patches, not river floods, so the backtest **cannot calibrate k** (the best k sits on the edge of the search grid; F1 0.07). Nairobi uses Nyando's k and is labelled uncalibrated. | `processed/nairobi/model/backtest/backtest.png` (at 1726a52), sha256 c00b1c65…; ROUND 8 ACCEPT |
| `methods_aoi_*.png`, `methods_terrain_*_nyando.png` | (existing, M-01 and M-03) areas of interest; Nyando HAND, channels and slope | ROUNDS 1 and 3 |

## Backtest score: never cut (Nyando, k calibrated)

| quantity | value | how | source |
|---|---|---|---|
| F1 / IoU | **0.188 / 0.104** | model mask (union of the 8 and 20 Nov 2023 dates) vs S1 observed mask, 2,723 km² evaluated, permanent water excluded | backtest.json, 255aab5; ROUND 6 ACCEPT (independent recompute) |
| precision / recall | 0.118 / 0.465 | same | same |
| observed flood | 26.13 km² | S1 VH, after/before > 1.25, slope < 5 %, ≤ 8-neighbour patches removed | same |
| terrain-only baseline | F1 0.177 (HAND < 1 m, no rainfall) | same domain and observed mask | baseline.json, 69e066d; ROUND 6 re-audit ACCEPT |
| skill from rainfall + calibration | +0.011 F1 over that baseline | 0.188 − 0.177 | same |
| hold-out (5 km checkerboard, 2 folds) | F1 0.231 and 0.136 on the held-out tiles | k fitted on one fold, scored on the other | backtest.json |
| Nairobi | not calibrated: best F1 0.068 at the top of the k grid (F1 rises monotonically to it; 0.051 at Nyando's k) | urban SAR change is too weak a flood signal | ROUND 8 ACCEPT (F8.3) |

Slide wording (the lead's; the auditor confirmed the underlying statement, terrain-only F1 0.18 with the rainfall chain adding +0.01, in F6.6): *"Backtest F1 0.19 / IoU 0.10 against Sentinel-1 (Nov 2023). A terrain-only map
already scores F1 0.18, so the rainfall model adds a modest +0.01: this is screening-level, not a precise forecast."*

## Scenario numbers

Flooded area, Nyando (calibrated k), km² inside the ruled box [34.80, −0.45, 35.30, 0.00]. Independently rebuilt in ROUND 7 (ACCEPT).

| rain in 24 h | 50 | 100 | 150 | 200 | 250 |
|---|---|---|---|---|---|
| normal | 83.56 | 103.08 | 115.51 | 125.19 | 133.51 |
| El Niño | 93.02 | 113.63 | 127.62 | 138.20 | 147.23 |

- Nairobi (k transferred, **uncalibrated**): 5.98 km² flooded at 150 mm normal, out of a 189.6 km² AOI.
- Pitch numbers at 100 mm, normal (sent to the operator 2026-11-06):

  | | mean runoff Q | flooded share of AOI |
  |---|---|---|
  | Nyando | 50.5 mm | 3.72 % |
  | Nairobi | 70.7 mm | 2.92 % |

  Nairobi has about 40 % more runoff (70.7 / 50.5 = 1.40) but a smaller flooded share. Why has NOT been analysed; do not give a cause on the slide.
- El Niño multiplier: CHIRPS OND 2023 total divided by the OND 1991–2020 mean, over each area box.
  - Nyando: 549.4 / 387.1 mm = **1.419**; OND 2023 was the 6th wettest of 33 years (1991–2023).
  - Nairobi: 329.7 / 286.8 mm = **1.150**; 10th of 33.
  - Source: CHIRPS v2.0 (Funk et al. 2015).

## Forecast anchor (M-11, snapshot 2026-11-06 11:02 UTC; ROUND 9, awaiting auditor)

Label: "official outlook / forecast snapshot". Never "our forecast".

- **ICPAC GHACOF74, OND 2026:** probability of above-normal rain is **70–80 %** for Nyando and **80–90 %** for Nairobi. These were read from the official map (Figure 1) against its own legend; ICPAC publishes no gridded file. The statement says El Niño conditions are established.
- **Open-Meteo 16-day forecast:** the wettest day is 19.4 mm (Nyando) and 11.3 mm (Nairobi). Both are below 25 mm, so **no slider scenario is triggered** today.
- **GloFAS river flow:** the 30-day peak is 60.7 m³/s for Nyando (34th percentile) and 26.7 m³/s for Nairobi (93rd percentile), both against the 1997–2020 daily record. This is context only.

## Data sources and licences

The licence text below is copied from each export's own manifest (`$RMS_DATA/raw/<area>/*.json`). Rows marked * were
checked against the provider's page today. Rows marked † are NOT verified.

| data | used for | licence / attribution |
|---|---|---|
| Copernicus DEM GLO-30 (DSM) | Nyando terrain | © DLR e.V. 2010–2014 and © Airbus 2014–2018, provided under COPERNICUS by the European Union and ESA; free licence |
| **FABDEM V1-2** | Nairobi terrain (bare earth) | **CC BY-NC-SA 4.0, © University of Bristol / Fathom. Non-commercial use only** (from the tiles' own LICENCE tag; human decision 2026-11-06: MUST be on the slide) |
| CHIRPS v2.0 | El Niño ratio, backtest rainfall | public domain (CC0); cite Funk et al. 2015, doi:10.1038/sdata.2015.66 |
| ESA WorldCover 2021 v200 | curve numbers (land cover) | © ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021); CC BY 4.0 |
| ISRIC SoilGrids 2.0 | soil group for CN | Poggio et al. 2021, doi:10.5194/soil-7-217-2021; CC BY 4.0 |
| JRC Global Surface Water v1.4 | permanent water | Pekel et al. 2016, Nature 540:418–422; EC JRC/Google; CC BY 4.0 |
| Copernicus Sentinel-1 GRD (via Earth Engine) | observed flood (backtest) | Contains modified Copernicus Sentinel data 2023 / 2024 (free, full and open) |
| OpenStreetMap | channel check, roads (routing) | © OpenStreetMap contributors, ODbL |
| WorldPop Kenya 2020 | population (exposure) | WorldPop, doi:10.5258/SOTON/WP00645; CC BY 4.0 |
| Google Open Buildings v3 * | buildings (exposure) | CC BY 4.0 or ODbL v1.0, at the user's choice; cite Sirko et al. 2021, arXiv:2107.12283 (sites.research.google/gr/open-buildings) |
| Open-Meteo forecast API * | forecast snapshot | CC BY 4.0, "Weather data by Open-Meteo.com" (open-meteo.com/en/licence) |
| GloFAS v4 (via Open-Meteo flood API) † | river-flow context | Open-Meteo lists GloFAS under its **own** licence (a linked PDF, not read). The "CC BY 4.0" in forecast.json is NOT VERIFIED; to be corrected after landing |
| ICPAC GHACOF74 statement † | official outlook | © ICPAC; reuse terms not checked. Cite the statement and URL |
| UNOSAT 1 May 2024 Nairobi product | evidence for the Nairobi event dates | geo.btaa.org/catalog/70148c8d-4d8a-4e70-8c03-c9bb8370cfb7; terms not checked |

## Limitations (numbers for the limitations slide: never cut)

1. **Screening-level, modest skill.** F1 0.19 / IoU 0.10. A terrain-only map scores F1 0.18, so rainfall plus calibration adds +0.01 (above).
2. **Nairobi is uncalibrated, and the transferred k likely UNDER-states its flood extent.** Urban radar does not show the
   flood well enough to calibrate (best F1 0.068), so Nairobi uses Nyando's rural k = 0.0126. Nairobi's own backtest,
   weak as it is, points the other way: F1 rises steadily up to the TOP of the k grid (0.05, about 4× Nyando's k), and
   both hold-out folds pick 0.05. At 0.05 the model floods 12.98 km² of the evaluated area, against 6.94 km² at the
   transferred k. Say "k transferred from a rural calibration; Nairobi's own weak evidence suggests more flooding than
   shown". The grid was not extended, so where (if anywhere) F1 peaks is unknown. (Auditor F8.3, ROUND 8.)
   About 44 % of Nairobi's flooded area at 150 mm is the channels themselves (2.62 of 5.98 km²), and extent moves only
   from 4.76 to 6.63 km² between 50 and 250 mm. It is a river-corridor map, not a city-wide pluvial map: there is no
   drainage model (F8.4).
3. **Surface DEM in Nyando.** GLO-30 is a surface model. On Ahero's buildings it reads 0.8–1.8 m above bare earth (FABDEM; median–90th percentile over 441 building cells), so HAND there is overstated, and flood depth understated, by about 1–2 m. Nairobi uses bare-earth FABDEM.
   - Do NOT say "rooftops read as 12–14 m HAND": building cells have median HAND 8.0 m, and that height is mostly above the nearest drainage, not the roofs.
4. **No river hydraulics.** The stage rule is h = k·V^0.4. Closed depressions have HAND 0 and flood in every scenario, with depth h, not pond depth.
5. **Soil gaps.** Under 55 % of the Nairobi AOI, SoilGrids has no texture; those cells take the nearest soil value. Nyando: 1.8 % of cells have no CN and get no runoff.
6. **The El Niño scenario is one season's ratio** (OND 2023 vs 1991–2020), applied uniformly. It is not an ENSO forecast.
7. **Forecast anchor.** The ICPAC bands come from a map image, not data. GloFAS flow is modelled and has not been checked against a gauge. The 25 mm cut-off for "no scenario" is our rule, not an official threshold.
8. **Data dates.** WorldCover 2021, WorldPop 2020 and JRC GSW to 2021 do not show change since then.

NOT VERIFIED here: the GloFAS and ICPAC reuse terms; how complete OSM buildings are around Ahero; FABDEM's own vertical
error. The M-11 (ROUND 9) numbers are awaiting the auditor.
