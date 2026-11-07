# Slide numbers — exposure, routes, and reported impacts (E-08)

Status: **PROVISIONAL, under audit** (exposure ROUND 8; it rests on model ROUND 7 at 56322d6 and ROUND 8 at 856ad74, and on
exposure ROUNDs 5–7, none ACCEPTed yet at the time of writing). `meta.json` is still `"mock": true`. Do not put a number from
this page on a slide until the operator says the rounds are ACCEPTed. If a model raster changes, every number below changes too.

Every number here was read from the committed files in `web/public/data/<area>/scenarios/*.exposure.json` (commit 7eaf152),
or from the round named next to it. Reported real-world impacts are quoted from a primary document with its URL, or they are
marked **UNVERIFIED**.

---

## 1. What a scenario is

A scenario is a **hypothetical 24-hour storm** of 50/100/150/200/250 mm on normal or El Niño-wet ground. It is **not a
forecast** and **not a reconstruction** of a real event. The flood map is a screening-level HAND + SCS-CN model (terrain
height above the nearest channel, plus a runoff estimate). It is a calibrated approximation, not a hydraulic model.

- **Projection year: 2026.** Population is the KNBS 2009 and 2019 census county totals, projected to 2026 with the method in
  `population.json`. People are spread inside each county with WorldPop 2020, weighted by Google Open Buildings v3 footprint
  area ("W2").
- **Low / medium / high** = the census growth rate × 0.7 / 1.0 / 1.2 (`population.json` assumptions). The range is about
  growth uncertainty only. It does not cover the flood model's uncertainty, which is much larger (see §4).
- **Buildings** = Open Buildings v3 footprints (≥ 85 % precision threshold) whose centroid lies in a flooded cell.
- KNBS sources (verified in exposure ROUND 5): 2019 KPHC Vol. I,
  https://open.africa/dataset/9b94fe50-9d75-4b92-be00-6354c6e6cc88/resource/778659b5-c5ab-4d13-9f89-f61baf9cf32a/download/volume-1-kphc-2019.pdf
  (Nairobi 4,397,073; Kisumu 1,155,574; Kericho 901,777). 2009 KPHC county table,
  https://www.knbs.or.ke/wp-content/uploads/2023/09/2009-Kenya-population-and-Housing-Census-Population-Distribution-by-Sex-Number-of-Households-Area-and-Density-by-County-and-District.pdf
- Nyando spans several counties (Kisumu 47 %, Kericho 40 %). Each county's people are scaled to that county's own KNBS total
  (operator ruling, option B).

## 2. Exposure per scenario (2026)

#### Nyando (Kisumu, rural)

| Scenario (24 h rain) | ENSO | Flooded area | People exposed, 2026 (low / medium / high) | Buildings in flood |
|---|---|---|---|---|
| 50 mm | normal | 83.56 km² | 4,549 / 4,720 / 4,836 | 1,638 |
| 50 mm | El Niño | 93.02 km² | 5,401 / 5,603 / 5,741 | 1,960 |
| 100 mm | normal | 103.08 km² | 6,306 / 6,542 / 6,704 | 2,421 |
| 100 mm | El Niño | 113.63 km² | 7,400 / 7,677 / 7,866 | 3,039 |
| 150 mm | normal | 115.51 km² | 7,569 / 7,852 / 8,046 | 3,141 |
| 150 mm | El Niño | 127.62 km² | 9,028 / 9,366 / 9,597 | 4,037 |
| 200 mm | normal | 125.19 km² | 8,797 / 9,126 / 9,351 | 3,883 |
| 200 mm | El Niño | 138.20 km² | 10,492 / 10,885 / 11,154 | 4,896 |
| 250 mm | normal | 133.51 km² | 9,779 / 10,145 / 10,395 | 4,469 |
| 250 mm | El Niño | 147.23 km² | 11,822 / 12,264 / 12,567 | 5,744 |

#### Nairobi (urban)

| Scenario (24 h rain) | ENSO | Flooded area | People exposed, 2026 (low / medium / high) | Buildings in flood |
|---|---|---|---|---|
| 50 mm | normal | 4.76 km² | 49,431 / 53,014 / 55,525 | 6,602 |
| 50 mm | El Niño | 4.90 km² | 52,254 / 56,043 / 58,697 | 6,901 |
| 100 mm | normal | 5.53 km² | 62,701 / 67,246 / 70,431 | 8,169 |
| 100 mm | El Niño | 5.68 km² | 65,051 / 69,767 / 73,071 | 8,470 |
| 150 mm | normal | 5.98 km² | 70,144 / 75,229 / 78,791 | 9,135 |
| 150 mm | El Niño | 6.14 km² | 73,199 / 78,506 / 82,224 | 9,477 |
| 200 mm | normal | 6.34 km² | 76,819 / 82,388 / 86,290 | 9,897 |
| 200 mm | El Niño | 6.52 km² | 79,804 / 85,589 / 89,643 | 10,224 |
| 250 mm | normal | 6.63 km² | 82,118 / 88,071 / 92,242 | 10,480 |
| 250 mm | El Niño | 6.81 km² | 85,578 / 91,782 / 96,129 | 10,863 |

Suggested slide lines (medium, with the range):

- "Nyando, 150 mm in a day on El Niño-wet ground: about **9,400 people (9,000–9,600)** and **4,000 buildings** in the flood
  zone, 2026 population. Screening estimate."
- "Nairobi, same storm: about **78,500 people (73,200–82,200)** in **6.1 km²**. A small area, densely built."
- "El Niño-wet ground at 150 mm: Nyando +19 % people (7,852 → 9,366), Nairobi +4 % (75,229 → 78,506)."
  (Arithmetic from the table: 9,366 / 7,852 = 1.193; 78,506 / 75,229 = 1.044.)

Sanity checks done in exposure ROUND 7:
- Exposure rises with rain in every step, and El Niño ≥ normal in all 10 pairs, in both areas.
- People per flooded building: Nyando 2.1–2.9 (AOI average 2.03); Nairobi 8.0–8.4 (AOI average 12.54).
- Flooded km² equals the model's hand-off table in every scenario (10 per area, 20 in all). The drawn polygons are within +0.004 %
  (Nyando, 18 m simplification). Nairobi's drawn area equals the table to 2 dp.

**Not for slides (audit only):** if people are spread by WorldPop alone ("W1"), medium exposure is 29,821–53,559 (Nyando) and
108,348–171,566 (Nairobi). W1 puts about 41 % of Nyando's people in pixels with no building, so it is an upper bound, not a
range. It stays off screen by ruling.

## 3. El Niño — the rainfall context (each row has its own source; see below the table)

CHIRPS October–December 2023 rainfall against the OND 1991–2020 mean, over each AOI:

| Area | OND 2023 | OND mean 1991–2020 | Ratio | Rank among 33 seasons 1991–2023 |
|---|---|---|---|---|
| Nyando | 549.4 mm | 387.1 mm | **×1.419** (42 % wetter) | **6th** wettest |
| Nairobi | 329.7 mm | 286.8 mm | **×1.1497** (15 % wetter) | **10th** wettest |

Sources, row by row:
- **Nyando** ×1.419, 6th of 33: model ROUND 5, finding F5.3 closed, ACCEPTed.
- **Nairobi** ×1.1497, 10th of 33: model ROUND 8 (rms-audit/model.md:1298). The model auditor checked it in their ROUND 8
  (model.md:1540, "10th of 33 ✓"), but that round is **not closed** yet: model F8.2 is still open (model.md:1675). Use the Nairobi
  row only once model ROUND 8 is closed.

Do **not** use "5th of 31" for Nyando: it skipped 2021–2022 and is wrong.
The ratios come from the unrounded totals: the rounded Nairobi millimetres give 329.7 / 286.8 = 1.1496. On a slide, say
"×1.15" and "×1.42".

## 4. How good is the flood map — the backtest (model ROUND 6, F6.1–F6.2)

- **Nyando: F1 0.19 / IoU 0.10** against the Sentinel-1 flood mask of November 2023 (precision 0.118, recall 0.465). The model
  floods 103 km² where Sentinel-1 saw 26.13 km², in a 2,723 km² domain.
- A terrain-only map (HAND < 1 m, no rainfall at all) scores **F1 0.18** (0.177). Most of the skill comes from terrain. The
  rainfall → stage chain adds +0.01, and calibration adds +0.006. Screening-level.
- **Nairobi: k transferred from Nyando, not calibrated locally.** Nairobi's own Sentinel-1 backtest scores F1 0.068, with the
  best k at the top of the grid. Say this plainly. Do not show a Nairobi accuracy number as if it were skill.

**Why the model floods about 4× what the satellite saw (an explained mismatch, not a hidden one):**
- Sentinel-1 sees standing open water at one overpass. It misses water under crops, trees and buildings, and water that has
  already drained.
- The model draws every cell that can flood for a given storm.
- HAND also wets every low cell connected to a channel, including closed depressions (model F2.13).

So the model is better at saying **where** water can go (recall 0.47) than **exactly how much** (precision 0.12). That is how
a screening tool should fail: it over-warns. It means exposure counts are best read as "people living where flooding is
plausible", not "people who will be flooded".

## 5. Routes (exposure ROUND 6–7; checked by resampling every drawn line against the raster)

- **Nairobi commute, Westlands → Kasarani (drive, free-flow):**
  - The usual route takes 15 min. At 50 mm it is unaffected.
  - At 100 mm the usual route is cut and the safe route takes **28 min**. From 150 mm it takes **33 min**.
  - The usual route loses 3 graph edges to the flood at 100–150 mm, and 4 from 200 mm.
  - Avoided road names are taken from the graph, never typed.
- **Gikomba Market (Nairobi trader):** from 150 mm the start point itself is cut off by water. **No route is drawn**, and in
  the current app no message appears for that origin either (web/src FloodApp.tsx:151, panels.tsx:227 render a route block
  only when a route exists). The wording "No safe route on foot. Move to an upper floor and call for help" is **pending with
  Person B**: do not say on a slide or in the demo that the app shows it until Person B ships it. If the message
  gives a number, the Kenya Red Cross toll-free line is **1199**, verified at https://www.redcross.or.ke/?p=56 ("Toll Free:
  1199").
- **Mathare and Kibera:** a 3 min walk in every scenario to the nearest school outside the flood (Angel Junior Academy;
  Mzalendo High Technical Center).
- **Nyando:**
  - Ahero town → high ground near Onjiko Boys High School (HAND 16 m): **39 min**.
  - A farm in the Ahero Irrigation Scheme → the same high ground: **90 min** (**113 min** at 250 mm El Niño).
  - Katito Market → Katito hospital: **9 min**.
- **NOT FOR SLIDES until exposure ROUND 9 lands (operator ruling).** The road-cut test sampled too sparsely and missed
  1–10 % of flooded road segments, so the lists below may be missing roads. The drawn routes are unaffected.
  ROUND 9 will publish the corrected lists.
- Roads cut (named, from the graph; PROVISIONAL, see above):
  - Nairobi 250 mm El Niño: Thika Road, Kiambu Road, Murang'a Road, Uhuru Highway, Chiromo Road, Mombasa Road, …
  - Nyando 250 mm El Niño: Kisii–Kisumu Road, Kericho–Kisumu Highway, Katito–Kendu Bay–Homa Bay road, …
  - Some Thika Road / Murang'a Road cuts are shallow cells that are the F2.13 closed-depression limit (§7).

## 6. Reported impacts of the real events — what we could and could not verify

The slide must not suggest the model "predicted" these numbers. A scenario is a single 24-hour storm over one AOI. The reported
figures are **national**, cover a **whole season**, and count **households affected or displaced**, not people living in a
flood zone. They set the scale of the problem. **They are not a validation of our exposure counts.**

### Verified (primary source, quoted)

| Event | Figure | Source (primary, with URL) |
|---|---|---|
| OND 2023 El Niño short rains, Kenya (national) | "A population of **757,173 people (138,560 households)** has been affected to date since the onset of the OND 2023 short rains. Out of these, **64,373 households** have been displaced in … Kisumu, … Nairobi and Kitui Counties." 38 counties affected. | IFRC Emergency Appeal MDRKE058, Operation Update #1, issued 05/02/2024, covering 23/11/2023–03/01/2024: https://go-api.ifrc.org/api/DownloadFile/86479/MDRKE058eu1 |
| March–May 2024 long rains, Kenya (national) | "To date, there are at least **245 fatalities, 78,683 households affected, and 45,778 households displaced**." **42 of 47 counties** affected. "The floods have also hit residential informal settlement areas in the capital, Nairobi, as rivers overflowed." | IFRC Revised Emergency Appeal MDRKE058, Revision #1, 16/05/2024: https://go-api.ifrc.org/api/DownloadFile/87844/MDRKE058rea1 |
| Both seasons, people affected (IFRC appeal totals) | "People affected: **478,860 OND / 413,304 MAM**" | same document, MDRKE058rea1 |
| Kisumu County in both seasons | Kisumu is listed among the displacement counties (OND 2023) and among the priority counties (MAM 2024). The appeal shows KRCS shelter work in Nyakach, Kisumu County. | MDRKE058eu1; MDRKE058rea1 |

The two IFRC documents give different "affected" totals for OND 2023: 757,173 in Update #1 and 478,860 in the revised appeal.
We could not find the reason for the difference in the documents. If the slide needs one figure, quote one document by name
and date. Do not mix them.

### UNVERIFIED — do not put on a slide as fact

| Figure as reported | Why unverified |
|---|---|
| "1,500 households displaced in Nyando" (Kenya News Agency, Nov 2023) | kenyanews.go.ke failed TLS certificate verification. We did not bypass it, so the page was not read. |
| Nairobi County: "20,968 households, 147,061 people" affected (2024) | Secondary only (The Star, Eastleigh Voice quoting a county statement). The OCHA Flash Update said to cite it returned HTTP 403. |
| "39 killed, 20,000 displaced in Nairobi" (2024) | Newspaper (The Star), secondary. |
| Mathare: 6,935 displaced (2024) | A county official quoted in the press, secondary. |
| Kenya national: 60 deaths, 136,025 displaced (19 Nov 2023); 210 deaths (3 May 2024) | OCHA figures seen only through ECHO Daily Flash summaries. OCHA/ReliefWeb pages returned 403. |
| Copernicus EMS mapping of Kisumu 2023 or Nairobi 2024 | No activation was found. EMSR438 is Kisumu, May 2020, a different event. |

No county-level primary figure for Kisumu/Nyando 2023 or Nairobi 2024 could be retrieved today. If one is found later (OCHA
Flash Update, NDMA, NDOC or KRCS sitrep), it goes into this table with its URL before it goes on a slide.

### How our numbers relate to the reports (mismatches explained)

- **Nairobi.**
  - Our range for one 150–250 mm day is 75,000–92,000 people in the flood zone.
  - The county figure (147,061 people affected, UNVERIFIED) covers a whole season of repeated storms. "Affected" in
    humanitarian counts can include people whose homes did not flood; we have not seen the county's definition.
  - The model evaluates 189.6 km² of the city and floods only cells near a mapped channel (HAND). It does not model
    surface-water flooding in streets away from channels.
  - So a lower count from us is expected, not a contradiction.
- **Nyando.**
  - Our 4,700–12,300 people (medium) is an order of magnitude below Kisumu-wide or national "affected" counts.
  - Our AOI is the lower Nyando floodplain only, and the counts use the 2026 population inside modelled cells.
  - People per flooded building (2.1–2.9) is consistent with the rural average (2.03), so the count is not inflated by
    farmland pixels. That was the E-04 problem, now fixed.
- **Households vs people.** IFRC counts households. Our counts are people. Do not compare the two directly.

## 7. Limitations (for the limitations slide; wording as ruled)

- **Screening-level, not a forecast.** HAND + SCS-CN is a calibrated approximation, not a hydraulic model.
- **Backtest:** Nyando F1 0.19 / IoU 0.10 against Sentinel-1 (Nov 2023). A terrain-only HAND < 1 m map scores F1 0.18, so most
  of the skill comes from terrain.
- **Nairobi:** k transferred from Nyando, not calibrated locally (own backtest F1 0.068).
- **Terrain:** "Nyando terrain is GLO-30, a surface model: on buildings it sits 0.8-1.8 m above bare earth, so HAND there is
  overstated, and flood depth understated, by about 1-2 m. Nairobi uses bare-earth FABDEM."
- **Closed depressions (model F2.13):** HAND wets low cells connected to a channel even where water would not reach. Some of
  the shallow cells that cut Thika Road and Murang'a Road in Nairobi are this limit.
- **Population:**
  - KNBS 2009/2019 county totals projected to 2026. Low/high cover growth only.
  - People are spread by building footprint area, which also counts sheds, stores and non-residential buildings.
  - Open Buildings v3 footprints are from satellite imagery of varying dates.
- **Routes:**
  - Drive times are free-flow, not congested.
  - Rural road speeds are assumed by road class, not sourced (exposure F3.10).
  - Footpaths are closed at any flood depth. Roads are closed at 0.3 m or more. Source: US National Weather Service, "It
    takes just 12 inches of rushing water to carry away most cars",
    https://www.weather.gov/safety/flood-turn-around-dont-drown
  - Where the start point is cut off by water, no route is drawn.
- **Relocation sites** are high ground selected as follows:
  - robust HAND ≥ 5 m;
  - no mapped building in the cell;
  - slope ≤ 10 %, preferring 2–4 %;
  - within 120 min.
  - The slope source is the UNHCR Emergency Handbook, "Principles & Standards for Settlement Planning", "Ideally, a site
    should have a slope of 2%–4% for good drainage, and not more than 10% to avoid erosion",
    https://emergency.unhcr.org/print/pdf/node/531
  - These are candidates for planners to check on the ground, not designated sites.
- **Shelters** are OSM schools, health facilities (hospitals + clinics; most are clinics) and churches. Rural Nyando is thinly
  mapped in OSM (about 60 schools and 15 health facilities in about 2,500 km²).
- **Wording:** say "health facilities (hospitals + clinics)", never "hospitals", for the OSM count.
