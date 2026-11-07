# Demo script (about 3 minutes)

Open the deployed URL in a fresh browser window before you go on stage. The app opens on **Nyando** at **150 mm, El Niño off**.

## 0. Opener (10 s)
Point at the blue banner at the top of the panel: **"ICPAC outlook OND 2026: wetter than normal (70–90% chance)"**, and the line under it — the next 16 days' wettest day is below our lowest 50 mm scenario, so no flood scenario is expected. Say: "That is the official outlook, not ours. When a real storm is forecast, this banner offers a button that jumps the slider to the matching scenario."

## 1. Problem (20 s)
"Floods hit the same communities every season. Forecasts exist, but people don't get told *what to do*." Mention the November 2023 El Niño short rains and the April–May 2024 Nairobi floods (use verified, sourced facts from the slides).

## 2. Nyando, rural (60 s)
1. Click **Animate**. The flood zone spreads along the Nyando River from 50 to 250 mm. Say: "This is the pace of impact."
2. Set the slider to **150 mm** and switch **El Niño on**. "Same storm, wetter soil: more people exposed." Point to the people counter and its low–high range.
3. Click **Settler**, then **Ahero town**. "Ahero's settlers get a relocation site on high ground and a walking route."
4. Click **Farmer**. Show the advisory for **maize** (high risk), then switch to **sorghum** or **rice**. "Practical crop advice, tied to the season and El Niño."
5. Optional: scroll to the **SMS alert preview** and switch to **Kiswahili**.

## 3. Nairobi, urban (60 s)
1. Switch to **Nairobi**. Set **100 mm**, El Niño off. Say:

   > "The same 100 mm of rain turns into about 40% more runoff in built-up Nairobi (71 vs 50 mm), because 61% of the city is paved or built (vs under 1% in Nyando). But how much land floods is set by terrain: Nairobi's rivers run in narrow valleys, so the flood is narrower and faster, and roads and homes along the river corridors take the hit."

   Do **not** say the footprint is bigger in Nairobi: at 100 mm normal the model floods 3.7% of Nyando (103 km²) and 2.9% of Nairobi (5.5 km²).
2. Click **Commuter** (Westlands → Kasarani). Raise to **200 mm**. The usual route turns into a dashed grey line, the safe route shows in blue with **+N min**, and the panel lists the roads avoided.
3. Click **Resident**, then **Mathare**: nearest safe place and route.
4. Set **150 mm** and click **Gikomba**: the panel shows **"No safe route on foot. Move to an upper floor or high ground and call for help: Kenya Red Cross toll-free 1199."** That starting point is inside the flood, so there is no route to give. Say: "When the honest answer is 'you cannot walk out', the app says that instead of drawing a line."
5. Click **Show arrival time**: "Mathare has under an hour; downstream has longer."
6. Optional: **Report blocked road (mock)**, then tap the map: "Community reports feed back into routing."

## 4. Trust (30 s)
Switch to the backtest slide and give the audited numbers, not a polished one.

- **Nyando vs Sentinel-1, Nov 2023:** F1 **0.19**, IoU **0.10**, precision **0.12**, recall **0.47**. The model floods more than the satellite saw (about **103 vs 26 km²**). Part of that is radar missing water under vegetation and short-lived floods, but mostly it is our screening-level model.
- **The honest line:** a terrain-only baseline ("land less than 1 m above the nearest channel") scores F1 **0.18**, so almost all the skill comes from terrain. Say it plainly:

  > "Terrain tells you WHERE it floods; our rainfall scenarios tell you HOW FAR it spreads, and that part is not yet validated against observations."

Judges trust this more than a polished number. Then open **About & limits** in the app: screening-level model, not a forecast, complements KMD and ICPAC.

## 4b. Numbers you may quote (all verified; full table with source URLs in `SLIDE_NUMBERS.md`)

| Fact | Value |
|---|---|
| OND 2023 rain, Nyando | **1.419×** the 1991–2020 normal (42% wetter), **6th wettest of 33** seasons (CHIRPS) |
| OND 2023 rain, Nairobi | **1.15×** normal, **10th of 33** |
| Flooded share at 100 mm normal | Nyando **3.7%** (103 km²), Nairobi **2.9%** (5.5 km²) |
| Runoff from 100 mm | Nairobi **71 mm** vs Nyando **50 mm**; impervious cover 61% vs under 1% |
| OND 2023 impacts (national, IFRC) | **757,173 people affected**, **64,373 households displaced** — cite the one IFRC document by name |
| MAM 2024 impacts (national, IFRC) | at least **245 deaths**, **78,683 households affected**, **45,778 displaced** |

**Withdrawn — do not use:** "5th of 31" and "1.414" for the Nyando El Niño ratio; both were wrong.
**Not verified — keep off the slides:** county-level figures for Nyando 2023 and Nairobi 2024 (press reports only), and the "roads cut" road names (a fix is being audited). The two IFRC documents disagree on people affected (757,173 vs 478,860), so name the document you are quoting.

## 4c. Sources slide (must appear)

- **FABDEM V1-2 (CC BY-NC-SA 4.0, © University of Bristol / Fathom)** for Nairobi — **non-commercial and ShareAlike; the Nairobi flood layers inherit this licence.** This line is mandatory.
- Copernicus GLO-30 for Nyando
- OpenStreetMap (ODbL), Geofabrik extract of 2026-11-04
- Google Open Buildings v3
- CHIRPS, ESA WorldCover, WorldPop, Sentinel-1 (Copernicus), JRC Global Surface Water, KNBS census, NOAA ONI, FAO EcoCrop, KALRO
- Basemap: OpenFreeMap, © OpenStreetMap contributors

## 5. Close (10 s)
Roadmap: drought module (click the **Drought (roadmap)** tab), live forecasts, IoT gauges, SMS/USSD, county integration.

## If the live demo fails
- Wi-fi down: run the local build (`cd web && npm run build && npm run start`, opened before the pitch) on the laptop.
- Anything else: play the recorded backup video straight away, and don't debug on stage.

## Before the pitch
- [ ] Mock data replaced by Person A's real files, or every Mock badge left visible and mentioned
- [ ] Rehearsed twice with a timer
- [ ] Backup video recorded
