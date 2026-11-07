# Impact-Based Flood Early Warning System: One-Day MVP Plan

IGAD Hackathon | Pilot areas: **Nairobi (urban)** and **Nyando, Kisumu (rural)** | Team of 2 | Build window: 1 day

> **Pitch in one line:** Most systems tell you *what the weather will do*. Ours tells *this person* what to do about it: where the water goes, who is exposed, where to move, which road to take, and what to do with their crops.

---

## 0. Ground rules for a one-day build

1. **A working demo beats a complete system.** Anything not working by the freeze time gets cut or mocked, and labelled as mocked.
2. **Precompute everything heavy.** The live demo only slides between precomputed scenarios, so nothing heavy runs live and nothing can break on stage.
3. **One engine, two area configs.** Nairobi and Nyando run through the same code, driven by a config file.
4. **Floods only.** Drought (Scenario 2 in your notebook) is a roadmap slide.
5. **Be honest about data limits.** Free elevation data is not accurate to the last metre. We call this a *screening-level risk map* and say so. Judges reward honesty and punish overclaiming.
6. **Verify every real-world fact** (event dates, census numbers, impacts) from the source before it goes on a slide. Numbers quoted in this file from memory are marked *(verify)*.

---

## 1. Scope

### Must have (Tier 1, the MVP)
- Map with a **Nairobi / Nyando switcher**
- **Flood risk layer** (low / medium / high) driven by a **rainfall slider (mm in 24h)** and an **El Niño toggle**
- **People and buildings at risk** counter (census-calibrated population)
- **Safe-place recommendation**: nearest high-ground shelter and a route that avoids flooded roads (urban: reroute commutes; rural: relocation)
- **Farmer advisory** for Nyando (crop, season, El Niño, action)
- **Backtest slide**: model vs real observed flood extent (Sentinel-1) for one event

### Should have (Tier 2, only if Tier 1 is done)
- Estimated **flood arrival time** from Manning velocity
- XGBoost susceptibility score with feature importances
- Mock **user report** ("bridge damaged") that updates the map
- Mock **SMS alert** screen (Africa's Talking sandbox, or a phone-frame mock)
- Plain-language alert text in English and Swahili via the Claude API, with fixed templates as fallback

### Roadmap slide only (Tier 3)
- Drought module (NDVI anomaly, CHIRPS deficit, rainfall forecast)
- IoT river and rain gauge sensors
- M-Pesa donation and resource-mobilisation flow
- Live forecast ingestion (Open-Meteo / ICPAC outlook)
- Offline USSD for feature phones

---

## 2. Architecture

```
            +------------------ OFFLINE / PRECOMPUTE (Python) ------------------+
Earth Engine --> GeoTIFFs --> HAND, slope, flow --> SCS runoff --> flood extent  |
OSM / Buildings / KNBS ------------------------------------------^   per scenario|
            +-------------------------------+---------------------------------+
                                            v  GeoJSON + JSON per scenario
                              /data/{area}/{rain_mm}_{enso}.geojson
                                            |
                        FastAPI (routing + advice)  <---->  Next.js + MapLibre UI
                                                              (Vercel)
```

**Key design choice:** pre-generate flood-extent GeoJSON for a grid of scenarios, for example rain = 50, 100, 150, 200, 250 mm x El Niño on/off, for each area. The slider snaps between files. Routing and advice can be precomputed too, so the backend is optional. If time is tight, ship **fully static** on Vercel.

### Stack
| Layer | Choice | Why |
|---|---|---|
| Geodata | Google Earth Engine (Community tier) | Free planetary data |
| Processing | Python: `rasterio`, `geopandas`, `pysheds`, `numpy`, `shapely`, `osmnx`, `networkx`, `xgboost` | Standard, quick to write |
| API | FastAPI | Quick, typed, free hosting on Render / Railway |
| Frontend | Next.js + MapLibre GL + Tailwind | Vector maps, no API key needed |
| Basemap | OpenStreetMap tiles or a free MapLibre style | No billing |
| Hosting | Vercel (frontend), Render (API) | Free tiers |
| Optional DB | Supabase (PostGIS) | Only if storing user reports |
| Alerts | Africa's Talking sandbox | Realistic Kenyan last-mile channel |
| Advisories | Claude API with templates as fallback | Plain-language output |

---

## 3. Data catalogue

**Earth Engine asset IDs, check each in the catalog before use, since names and versions change.**

| Need | Source | EE asset (verify) | Used for |
|---|---|---|---|
| Elevation (rural) | Copernicus GLO-30 | `COPERNICUS/DEM/GLO30` | Slope, HAND, flow |
| Elevation (urban) | FABDEM (community catalog) | `projects/sat-io/open-datasets/FABDEM` | Buildings and trees removed, better for Nairobi |
| Elevation (fallback) | SRTM 30 m | `USGS/SRTMGL1_003` | Backup |
| Rainfall history | CHIRPS daily | `UCSB-CHG/CHIRPS/DAILY` | Event rainfall, El Niño anomaly |
| Satellite rainfall | GPM IMERG | `NASA/GPM_L3/IMERG_V07` | Cross-check |
| Land cover | ESA WorldCover | `ESA/WorldCover/v200` | Curve number, Manning n |
| Soil texture | OpenLandMap | `OpenLandMap/SOL/SOL_TEXTURE-CLASS_USDA-TT_M/v02` | Soil group for runoff |
| Population grid | WorldPop 100 m | `WorldPop/GP/100m/pop` | Dasymetric weights |
| Buildings | Google Open Buildings | `GOOGLE/Research/open-buildings/v3/polygons` | Buildings at risk |
| Observed floods | Sentinel-1 SAR | `COPERNICUS/S1_GRD` | Backtest flood mask |
| Permanent water | JRC Global Surface Water | `JRC/GSW1_4/GlobalSurfaceWater` | Exclude permanent water |
| Roads, shelters, hospitals, schools | OpenStreetMap | via `osmnx` (not EE) | Routing and safe places |
| Census | KNBS 2009 and 2019 (ward / sub-county) | KNBS website download | Population projection |
| ENSO status | NOAA ONI | noaa.gov table | El Niño / La Niña context |
| Crop rules | FAO EcoCrop, KALRO guides | download | Farmer advisory |

### Pilot areas (config)
Keep each AOI small to stay under the 150 EECU-hour Community limit.

```yaml
# configs/nyando.yaml
name: Nyando (rural)
bbox: [34.85, -0.45, 35.30, 0.00]   # adjust to the Nyando / Kano plains; verify on a map
dem: COPERNICUS/DEM/GLO30
backtest_event: {start: "2023-11-01", end: "2023-11-30"}   # verify dates against reports
before_period: {start: "2023-09-01", end: "2023-10-10"}
user_types: [settler, farmer, trader]

# configs/nairobi.yaml
name: Nairobi (urban)
bbox: [36.78, -1.33, 36.92, -1.22]  # central river corridor (Mathare / CBD / Nairobi River); keep ~15x15 km max
dem: projects/sat-io/open-datasets/FABDEM
backtest_event: {start: "2024-04-20", end: "2024-05-10"}   # verify dates against reports
before_period: {start: "2024-03-01", end: "2024-04-10"}
user_types: [commuter, informal_settlement_resident, trader]
```

> Hypothetical scenarios (for example "100 mm in 24 h") must be labelled **scenario**. Backtests must use real events. Say on the slide which is which.

---

## 4. Methods and models

### 4.1 Terrain: slope, flow direction, HAND
- Fill pits and resolve flats, compute **D8 flow direction** and **flow accumulation** with `pysheds`.
- Channels = cells with accumulation above a threshold (tune per area).
- **HAND** (Height Above Nearest Drainage) = elevation minus the elevation of the nearest channel cell it drains to. HAND is much more robust to DEM error than absolute elevation, and it is the core of the flood layer.

### 4.2 Rainfall to runoff: SCS Curve Number
```
S  = 25400 / CN - 254          # mm, potential retention
Q  = (P - 0.2 S)^2 / (P + 0.8 S)   if P > 0.2 S else 0   # runoff depth, mm
```
- CN comes from land cover x soil group. Starting values below, adjust with a source (USDA TR-55) before presenting.

| Land cover | Rough CN range (verify with TR-55) |
|---|---|
| Built-up / paved | 90 to 98 |
| Cropland | 70 to 85 |
| Grassland | 60 to 80 |
| Tree cover | 55 to 70 |
| Wetland / water | treat as flood-prone |

- **Pitch point:** the same 100 mm produces far more runoff in built-up Nairobi than in Nyando farmland.

### 4.3 Runoff to flood extent (calibrated, honest)
We are not running a hydraulic model in a day. We use a transparent screening approach:

1. Compute catchment runoff depth Q per scenario.
2. Convert Q to an effective **flood stage** h (metres above channel): `h = k * Q^alpha`, with `alpha` around 0.5 to start.
3. Mark a cell flooded if `HAND < h` AND it is hydrologically connected to a channel (connected-component check). Exclude steep slopes (for example > 15 degrees) where water does not pond.
4. **Calibrate k** on the backtest: pick the k that maximises F1 / IoU against the Sentinel-1 observed flood mask. Report the score honestly, even if it is modest.
5. Risk classes by how much HAND sits below h (for example < 0.5 m x h = low, up to 1.0 = medium, higher = high).

> Say this on the slide: *"Screening-level model calibrated on a real event. It shows where to look closely. It is not a survey-grade inundation model. HEC-RAS or LISFLOOD-FP would be the next step."*

### 4.4 Speed and arrival time (Tier 2)
Manning's equation along the flow path:
```
v = (1/n) * R^(2/3) * S^(1/2)      # n from land cover (about 0.03 channel, 0.05 to 0.15 floodplain/urban), R about flow depth, S = local slope
travel_time = sum(cell_distance / v)   # from channel head to each cell
```
Output "estimated time before water reaches this area". Present it as an approximation.

### 4.5 El Niño / ENSO scenario (data-derived, not guessed)
- Compute the **rainfall anomaly ratio** from CHIRPS: (season total in the El Niño year) / (multi-year climatological mean for the same season) over each AOI.
- The El Niño toggle applies that ratio to the slider rainfall (or raises the baseline wetness / CN class).
- Present it as "wetter than normal, by X% in this area in the 2023 event", and cite the source.

### 4.6 Susceptibility ML (Tier 2)
- Sample flood and non-flood points from the Sentinel-1 mask (stratified, spatial train/test split by blocks to avoid leakage).
- Features: elevation, slope, HAND, flow accumulation, distance to channel, land cover, CHIRPS event rain, TWI.
- **XGBoost** classifier -> probability map + feature importance chart + AUC.
- Use it as a cross-check of the HAND model and for a good slide. If time is short, skip it.

### 4.7 Exposure and population (census-calibrated)
1. Download **KNBS 2009 and 2019** ward or sub-county counts for the AOIs. Check that boundaries match between censuses.
2. Growth rate per unit: `r = (P2019 / P2009)^(1/10) - 1`
3. Projection to year t: `P(t) = P2019 * (1 + r)^(t - 2019)`
4. **Three scenarios:** low (growth rate slows by about 30%), medium (historical r), high (historical r +20%). State these multipliers as assumptions.
5. **Dasymetric distribution:** spread each ward's projected population over its pixels using WorldPop (or building footprint area) as weights, so totals match the census projection.
6. **Exposed population** = sum of projected population in flooded cells. **Buildings at risk** = count of Open Buildings footprints intersecting flooded cells.

Caveats to list on a slide: informal settlements are often undercounted, growth rates change over time, the next census is due around 2029, and everything after 2019 is an estimate.

### 4.8 Recommendations engine

**Urban (Nairobi), commuters and residents**
- OSM road graph via `osmnx` (drive + walk).
- Remove edges whose midpoint is in a flooded cell (or in a high-risk class).
- Shortest path (Dijkstra, travel time) from the user's location to the **nearest safe shelter** (school, church, hospital, community hall) with HAND above h + margin and outside flood cells.
- Commute reroute: origin-destination pair, baseline route vs flood-avoiding route, extra minutes shown.
- Show alerts per risk class ("High: avoid Juja Road, use Thika Road instead", generated from the routing result, not hard-coded).

**Rural (Nyando), settlers and traders**
- Rank candidate **high-ground relocation sites**: HAND high, slope low, outside flood cells, within X km of a road, near a school or health facility.
- Safe access route to the site (same graph logic, rural roads).
- Traders: flag market centres and roads likely to be cut.

**Farmers (Nyando)**, a rules table: `region x season x ENSO state x crop -> action`
```csv
crop,season,enso,risk,action
maize,short_rains,el_nino,high,"Delay planting until flood risk passes; plant on raised beds; improve drainage; use short-maturity variety"
sorghum,short_rains,el_nino,medium,"Good flood-tolerant alternative; plant on higher ground"
rice,short_rains,el_nino,low,"Suited to flood-prone plains; prepare paddies and bunds"
cassava,long_rains,normal,low,"Plant on mounds; avoid waterlogged soil"
```
- Build the CSV from FAO EcoCrop and KALRO guidance. **Cite sources on the slide.**
- The Claude API can turn a structured result into a short Swahili or English advisory. Ground it strictly in the table and the model output, and keep fixed templates as a fallback if the API is slow or down.

---

## 5. API contract (agree this in the first 30 minutes)

The frontend builds against mock responses of exactly this shape; the backend swaps in real data later.

```
GET /areas
-> [{"id":"nairobi","name":"Nairobi (urban)","bbox":[...]},{"id":"nyando", ...}]

GET /risk?area=nyando&rain_mm=150&enso=true
-> {
  "area":"nyando","rain_mm":150,"enso":true,
  "flood_geojson": { ...FeatureCollection with property "risk": "low|medium|high" },
  "exposure": {"population_2026": 12400, "buildings": 3100, "scenario":"medium", "low":9800, "high":14900},
  "arrival_minutes_geojson": null
}

GET /route?area=nairobi&from=-1.28,36.85&to=-1.30,36.82&rain_mm=100
-> {"baseline":{"geometry":{...},"minutes":18},"safe":{"geometry":{...},"minutes":26},"avoided":["Road name", "..."]}

GET /shelters?area=nyando&rain_mm=150
-> [{"name":"...","type":"school","lat":0,"lon":0,"distance_m":1800,"route":{...}}]

GET /advice?area=nyando&crop=maize&season=short_rains&enso=true&lang=en
-> {"risk":"high","actions":["..."],"text":"...","sources":["FAO EcoCrop","KALRO"]}
```

---

## 6. Repo structure

```
flood-ews/
  README.md
  FLOOD_EWS_MVP_PLAN.md          # this file
  configs/
    nyando.yaml
    nairobi.yaml
  data/
    raw/            # GeoTIFFs from Earth Engine, KNBS CSVs, OSM extracts (gitignored if large)
    processed/      # HAND, slope, flow, runoff rasters
    scenarios/      # {area}/{rain_mm}_{enso}.geojson  <- what the UI loads
  pipeline/
    01_ee_export.py          # Earth Engine exports
    02_terrain.py            # slope, flow dir, accumulation, HAND
    03_runoff_flood.py       # SCS CN, stage, flood extent, calibration
    04_backtest.py           # compare vs Sentinel-1 mask, F1 / IoU
    05_population.py         # census projection + dasymetric exposure
    06_routing.py            # OSM graph, shelters, safe routes
    07_scenarios.py          # loops rain x enso, writes scenarios/
    08_susceptibility.py     # XGBoost (Tier 2)
  api/
    main.py                  # FastAPI
    mock/                    # mock responses for the frontend
  advice/
    crops.csv                # rules table
    templates.py             # fallback text
  web/                       # Next.js + MapLibre app
  docs/
    slides/                  # pitch deck, demo script, backtest figures
```

### Git workflow
- `main` is always demo-ready. Branches: `data` (Person A), `app` (Person B). Merge to `main` at checkpoints only.
- Commit small and often. Never commit credentials. Large rasters go in `.gitignore`; share them via Drive.

### Setup
```bash
# Python
python -m venv .venv && source .venv/bin/activate
pip install earthengine-api geemap rasterio geopandas shapely pysheds numpy pandas \
            osmnx networkx xgboost scikit-learn fastapi uvicorn pyyaml matplotlib
earthengine authenticate
# Frontend
npx create-next-app@latest web --ts --tailwind
cd web && npm i maplibre-gl
```

### Earth Engine export skeleton
```python
import ee, yaml
ee.Initialize(project="YOUR_PROJECT_ID")
cfg = yaml.safe_load(open("configs/nyando.yaml"))
aoi = ee.Geometry.Rectangle(cfg["bbox"])

dem   = ee.Image(cfg["dem"]) if "FABDEM" in cfg["dem"] else ee.ImageCollection(cfg["dem"]).mosaic()
dem   = dem.clip(aoi)
rain  = (ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
         .filterDate(cfg["backtest_event"]["start"], cfg["backtest_event"]["end"])
         .sum().clip(aoi))
wc    = ee.Image("ESA/WorldCover/v200").select("Map").clip(aoi)
pop   = (ee.ImageCollection("WorldPop/GP/100m/pop")
         .filter(ee.Filter.eq("country","KEN")).filter(ee.Filter.eq("year",2020))
         .mosaic().clip(aoi))

def s1(a, b):
    return (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(aoi).filterDate(a, b)
            .filter(ee.Filter.eq("instrumentMode","IW")).select("VV").median().clip(aoi))
diff = s1(cfg["backtest_event"]["start"], cfg["backtest_event"]["end"]) \
         .subtract(s1(cfg["before_period"]["start"], cfg["before_period"]["end"]))
perm = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").gt(80)
flood_obs = diff.lt(-3).And(perm.Not())    # rough threshold; tune and visually check

for name, img in {"dem":dem,"rain":rain,"landcover":wc,"pop":pop,"flood_obs":flood_obs}.items():
    ee.batch.Export.image.toDrive(image=img, description=f"nyando_{name}",
                                  region=aoi, scale=30, fileFormat="GeoTIFF").start()
```
Export once, then work offline from the GeoTIFFs so you stay inside the 150 EECU-hour limit. Use `scale=10` only if a layer needs it and the AOI is small.

### Core flood-extent sketch
```python
import numpy as np
def scs_runoff(P, CN):
    S = 25400/CN - 254
    Ia = 0.2*S
    return np.where(P > Ia, (P-Ia)**2/(P+0.8*S), 0.0)

def flood_mask(hand, slope, Q_mm, k, alpha=0.5, max_slope=15):
    h = k * (Q_mm ** alpha)                  # stage in metres, k calibrated on backtest
    return (hand < h) & (slope < max_slope)  # then keep only cells connected to a channel
```

---

## 7. Work split (two people)

| | **Person A: Data and Model** | **Person B: App and Pitch** |
|---|---|---|
| Owns | Earth Engine exports, terrain/HAND, runoff, flood extent, calibration + backtest, population projection, routing, scenario generation, FastAPI | Next.js + MapLibre UI, area switcher, rainfall slider, El Niño toggle, risk legend, exposure panel, shelter/route display, farmer advisory screen, SMS/alert mock, deployment |
| Also owns | Methodology and accuracy slides | Pitch deck, demo script, README, demo video |
| Starts with | Authenticate EE, run exports for Nyando | Scaffold Next.js with mock `/risk` GeoJSON |

When one of you is blocked, help the other. Person B can also build `crops.csv` and collect KNBS tables while A waits on exports.

---

## 8. One-day schedule (relative hours; start now)

| Hour | Person A | Person B | Checkpoint |
|---|---|---|---|
| **H0 to H0.5** | Together: lock scope, create repo, agree API contract (section 5), pick roles | | Repo + contract written |
| **H0.5 to H2** | EE auth, export Nyando DEM, rain, land cover, pop, flood_obs | Next.js + MapLibre scaffold with mock data; area switcher; slider and toggle UI | EE exports running; map shows mock layer |
| **H2 to H4** | Terrain + HAND for Nyando; first flood mask | Risk legend, exposure panel, layout polish; start `crops.csv` | **First real flood layer visible on the map** |
| **H4 to H6** | SCS runoff + calibration + backtest (Nyando); start Nairobi exports (FABDEM) | Shelter/route display components; advisory screen | Backtest F1 / IoU number in hand |
| **H6 to H8** | Nairobi terrain, built-up CN, flood layer; population projection | Wire UI to real scenario GeoJSON; deploy a first version to Vercel | **Both areas live on a deployed URL** |
| **H8 to H10** | OSM graph, shelters, safe routes, `07_scenarios.py` batch run; FastAPI (or static JSON) | Advisory wiring; SMS/alert mock; user-report mock | **Feature freeze** |
| **H10 to H12** | Methodology and backtest figures; sanity checks; README data notes | Pitch deck, demo script, record backup video, rehearse x2 | Submit-ready |

If you fall behind, **cut in this order:** XGBoost, arrival time, user report, Swahili generation, Nairobi to a single neighbourhood. Never cut the backtest slide, the slider demo, or the safe-route recommendation.

---

## 9. Demo script (about 3 minutes)

1. **Problem (20 s):** floods hit the same communities every season. Forecasts exist, but people lack actionable guidance. Reference the November 2023 El Niño season and the 2024 Nairobi floods, with sources verified.
2. **Nyando, rural (60 s):** set rain to 150 mm, enable El Niño. The flood zone grows; the panel shows people and buildings at risk (with low/high range); relocation sites appear on higher ground with an access route; open the farmer advisory for maize vs sorghum.
3. **Nairobi, urban (60 s):** switch area. The same 100 mm turns into about 40% more runoff in built-up Nairobi (71 vs 50 mm, 61% impervious vs under 1%), but terrain sets how much land floods: Nairobi's rivers run in narrow valleys, so the flood is narrower and faster and the river corridors take the hit. (Flooded share at 100 mm normal: Nyando 3.7% / 103 km², Nairobi 2.9% / 5.5 km². The old "bigger footprint in Nairobi" claim is **false on our model** — do not use it.) Show a flooded road, the commuter reroute with extra minutes, the nearest shelter, and the no-route message for a start point inside the flood.
4. **Trust (30 s):** backtest slide: model vs Sentinel-1 observed floods with F1/IoU, plus the stated data limits and next steps.
5. **Close (10 s):** roadmap: drought, IoT sensors, SMS/USSD, donations, ICPAC integration. Complements ICPAC and KMD, does not replace them.

Record the demo as video **before** the live pitch, as a backup.

---

## 10. Honest limitations (put on a slide)

- Free DEMs (about 30 m) are not accurate to the last metre. We use HAND, which tolerates elevation error, and call the output screening-level. Higher-resolution LiDAR or drone data would plug into the same pipeline.
- Flood extent is a screening-level approximation (terrain + rainfall-runoff, not a hydraulic model), calibrated against Sentinel-1 observations of the Nov 2023 Nyando flood. Nairobi uses Nyando's calibration.
- Nyando terrain is GLO-30, a surface model: on buildings it sits about 1-2 m above bare earth, so flood depth there may be understated. Nairobi uses bare-earth FABDEM.
- Nairobi's flood model is not calibrated locally (satellite radar cannot see urban floods reliably); it uses Nyando's calibration.
- Backtest (Nyando vs Sentinel-1, Nov 2023): F1 0.19, IoU 0.10, precision 0.12, recall 0.47. A terrain-only baseline scores F1 0.18, so almost all the skill comes from terrain: terrain tells you *where* it floods, the rainfall scenarios tell you *how far* it spreads, and that part is not yet validated.
- Population after 2019 is a projection with low / medium / high scenarios; informal settlements are likely undercounted. Nyando spans six counties, so the census base must cover all six.
- The rainfall slider is a scenario tool, not a forecast. Live forecasts (Open-Meteo, ICPAC) are on the roadmap.
- Crop advice is rule-based from published guidance and needs local extension validation.

---

## 11. Definition of done (check before submitting)

- [ ] Deployed URL opens on a phone and a laptop
- [ ] Nairobi and Nyando both load; slider and El Niño toggle visibly change the map
- [ ] Exposure numbers shown with ranges and the year of projection
- [ ] At least one safe route and one shelter recommendation work per area
- [ ] Farmer advisory works for at least 3 crops
- [ ] Backtest figure with a real score and a map comparison
- [ ] Every real-world number on the slides has a verified source
- [ ] Mocked features are labelled as mocked
- [ ] Backup demo video recorded
- [ ] Submitted at least 2 hours early

---

## 12. Competitor and context slide (verify each before use)

- **ICPAC / GHACOF:** regional seasonal outlooks. We build on them.
- **Google Flood Hub / GloFAS:** river flood forecasts. They forecast; we personalise the action.
- **FEWS NET, NDMA:** drought and food-security early warning.
- **Ushahidi:** crowdsourced reporting, Kenyan. Inspiration for our report-and-alert loop.

**Differentiator:** impact-based, personalised, urban + rural, with agriculture advice and a user-reporting loop, designed to complement official warnings.
