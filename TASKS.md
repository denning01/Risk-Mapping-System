# Flood EWS: Master Task List

Legend: **[A]** Person A (data and model) | **[B]** Person B (app and pitch) | **[AB]** together
Tier: **T1** must have | **T2** nice to have | **T3** roadmap slide only
Tick boxes as you go. If you are running late, cut T2 items first.

---

## Phase 0: Setup and alignment (H0 to H0.5)

- [ ] [AB] T1 Read `FLOOD_EWS_MVP_PLAN.md` together
- [ ] [AB] T1 Confirm submission deadline and format (code, deck, video, live pitch)
- [ ] [AB] T1 Confirm scope: floods only, Nairobi + Nyando, one backtest event per area
- [ ] [AB] T1 Agree roles (A = data/model, B = app/pitch)
- [ ] [AB] T1 Create GitHub repo, invite each other, add `.gitignore` (rasters, `.env`, `node_modules`, `.venv`)
- [ ] [AB] T1 Create branches `data` and `app`
- [ ] [AB] T1 Agree API contract (section 5 of the plan) and commit it
- [ ] [AB] T1 Set a check-in rhythm (every 3 to 4 hours, two minutes: done / blocked / next)
- [ ] [AB] T1 Create a shared Drive folder for large files, screenshots and slides

## Phase 1: Accounts and environment

- [ ] [A] T1 Earth Engine registration approved (Community tier)
- [ ] [A] T1 Google Cloud project created, Earth Engine API enabled, project ID noted
- [ ] [A] T1 `pip install` Python dependencies in a virtualenv
- [ ] [A] T1 `earthengine authenticate` and a successful `ee.Initialize(project=...)`
- [ ] [B] T1 Node installed, `create-next-app` scaffold, `maplibre-gl` installed
- [ ] [B] T1 Vercel account connected to the GitHub repo
- [ ] [B] T1 Render or Railway account (only if running a live API)
- [ ] [AB] T2 Africa's Talking sandbox account
- [ ] [AB] T2 Anthropic API key (for plain-language advisories), stored in `.env`, never committed
- [ ] [AB] T2 Supabase project (only if storing user reports)

## Phase 2: Data acquisition

**Earth Engine (check each asset ID in the catalog first)**
- [ ] [A] T1 Define `configs/nyando.yaml` and `configs/nairobi.yaml`, with AOI boxes checked on a map
- [ ] [A] T1 Export Nyando: DEM (Copernicus GLO-30), CHIRPS event rainfall, WorldCover, WorldPop, Sentinel-1 flood mask
- [ ] [A] T1 Export Nairobi: FABDEM (or Copernicus fallback), CHIRPS event rainfall, WorldCover, WorldPop, Sentinel-1 flood mask
- [ ] [A] T1 Visually check each export in QGIS or geemap (right area, no empty tiles, correct CRS)
- [ ] [A] T1 Exclude permanent water using JRC Global Surface Water
- [ ] [A] T2 Export soil texture (OpenLandMap) for the curve number
- [ ] [A] T2 Export Google Open Buildings (or building count raster) for both areas
- [ ] [A] T2 Compute CHIRPS El Niño anomaly ratio (event season total / multi-year mean) for each AOI

**Non-Earth-Engine data**
- [ ] [A] T1 OSM road graph for each AOI via `osmnx`
- [ ] [A] T1 OSM shelters: schools, churches, hospitals, clinics, community centres, police stations
- [ ] [B] T1 KNBS 2009 and 2019 census tables for the relevant wards / sub-counties (download and record the source URLs)
- [ ] [A] T1 Ward / sub-county boundary files, checked for consistency between censuses
- [ ] [B] T1 NOAA ONI table (ENSO status for the event years), with the source link
- [ ] [B] T1 FAO EcoCrop and KALRO crop guidance for 3 to 5 crops
- [ ] [B] T1 Verify real event facts from reliable sources: dates, affected areas, impacts (ICPAC, OCHA, KMD, news)

## Phase 3: Terrain and hydrology (Person A)

- [ ] [A] T1 Load DEM, fill pits, resolve flats
- [ ] [A] T1 Compute slope
- [ ] [A] T1 Compute D8 flow direction and flow accumulation
- [ ] [A] T1 Extract channels (accumulation threshold tuned per area)
- [ ] [A] T1 Compute HAND
- [ ] [A] T1 Save rasters to `data/processed/`
- [ ] [A] T1 Quick sanity maps (HAND, slope, channels) saved as PNGs for slides
- [ ] [A] T2 Twi (topographic wetness index) for the ML features

## Phase 4: Runoff and flood model (Person A)

- [ ] [A] T1 Build curve number raster from land cover (and soil group if available)
- [ ] [A] T1 Implement SCS runoff function and unit-test it with hand-calculated values
- [ ] [A] T1 Implement runoff to flood stage conversion (`h = k * Q^alpha`)
- [ ] [A] T1 Implement flood mask (HAND < h, slope limit, connectivity to channel)
- [ ] [A] T1 Implement risk classes (low / medium / high)
- [ ] [A] T1 Apply the El Niño ratio as a rainfall or wetness multiplier
- [ ] [A] T1 Calibrate `k` against the Sentinel-1 flood mask (maximise F1 or IoU)
- [ ] [A] T1 Backtest report per area: F1, IoU, precision, recall, and a side-by-side map (model vs observed)
- [ ] [A] T1 Write down limitations found during backtest (honest numbers, even if modest)
- [ ] [A] T2 Manning velocity and flood arrival-time layer
- [ ] [A] T2 XGBoost susceptibility model: spatial block train/test split, AUC, feature importance chart
- [ ] [A] T2 Compare XGBoost map with the HAND map and note where they agree or differ

## Phase 5: Population and exposure (Person A, with B's census download)

- [ ] [A] T1 Calculate growth rate per ward: `r = (P2019/P2009)^(1/10) - 1`
- [ ] [A] T1 Project population to the current year and +10 years
- [ ] [A] T1 Create low / medium / high scenarios (state the multipliers as assumptions)
- [ ] [A] T1 Dasymetric distribution of ward totals to pixels using WorldPop or building weights
- [ ] [A] T1 Check that pixel totals sum back to the ward projection
- [ ] [A] T1 Exposed population per scenario (people inside flooded cells)
- [ ] [A] T1 Buildings at risk (Open Buildings intersecting flooded cells)
- [ ] [A] T2 Cross-check against WorldPop's own totals and explain any gap
- [ ] [A] T2 Note the census caveats for the slide (informal settlement undercount, boundary changes, 2029 census)

## Phase 6: Recommendations (Persons A and B)

**Routing and safe places**
- [ ] [A] T1 Build road graph, assign travel times
- [ ] [A] T1 Mark flooded road edges per scenario
- [ ] [A] T1 Identify safe shelters (outside flood cells, high HAND)
- [ ] [A] T1 Nearest safe shelter route per user location
- [ ] [A] T1 Commuter reroute: baseline vs flood-avoiding route, with extra minutes (Nairobi)
- [ ] [A] T1 Rank relocation sites on higher ground (Nyando): HAND, slope, distance to road, nearby school or clinic
- [ ] [A] T2 Alert text generated from the routing result (named roads that are cut)

**Farmer advisory (Nyando)**
- [ ] [B] T1 Write `advice/crops.csv` for at least 3 crops (region, season, ENSO state, risk, action) with sources
- [ ] [B] T1 Fallback text templates in `advice/templates.py`
- [ ] [B] T1 `/advice` endpoint or static JSON
- [ ] [B] T2 Claude API step to produce short English and Swahili advisories grounded in the table, with timeout and fallback to templates
- [ ] [B] T2 Have a Swahili speaker review the generated text

## Phase 7: Scenario generation and API

- [ ] [A] T1 `07_scenarios.py`: loop rain = 50 / 100 / 150 / 200 / 250 mm x El Niño on/off x both areas
- [ ] [A] T1 Output `data/scenarios/{area}/{rain}_{enso}.geojson`, simplified to keep files small (target a few MB each)
- [ ] [A] T1 Write exposure JSON per scenario (people, buildings, low/high range)
- [ ] [A] T1 Precompute shelters and routes per scenario, or serve them via FastAPI
- [ ] [A] T1 FastAPI endpoints: `/areas`, `/risk`, `/route`, `/shelters`, `/advice`
- [ ] [A] T1 CORS configured for the Vercel domain
- [ ] [A] T1 Replace mock responses with real ones, same response shape
- [ ] [A] T2 Deploy API to Render or Railway and test from the deployed frontend

## Phase 8: Frontend (Person B)

- [ ] [B] T1 Layout: map, side panel, header with area switcher
- [ ] [B] T1 MapLibre basemap and area switcher (Nairobi / Nyando) with fly-to
- [ ] [B] T1 Rainfall slider (snaps to the available scenarios) and El Niño toggle
- [ ] [B] T1 Flood layer rendering with a low / medium / high colour legend
- [ ] [B] T1 Exposure panel (people at risk with range, buildings at risk, projection year)
- [ ] [B] T1 Shelter markers and a "nearest safe place" action
- [ ] [B] T1 Route display (baseline vs safe route, extra minutes)
- [ ] [B] T1 Rural view: relocation sites + farmer advisory panel (crop picker)
- [ ] [B] T1 "Scenario" and "Modeled / mocked" labels visible on the UI
- [ ] [B] T1 Loading and error states (the demo must not show a blank map)
- [ ] [B] T1 Mobile layout check
- [ ] [B] T2 Arrival-time layer toggle
- [ ] [B] T2 Mock SMS alert screen (phone frame) and a "send test alert" button against the Africa's Talking sandbox
- [ ] [B] T2 Mock user report ("bridge damaged"), which marks the road as blocked on the map
- [ ] [B] T2 Language toggle English / Swahili
- [ ] [B] T3 Drought placeholder tab linked to the roadmap

## Phase 9: Integration and testing

- [ ] [AB] T1 First end-to-end run: slider change -> new flood layer -> new exposure numbers
- [ ] [AB] T1 Merge `data` and `app` into `main`; tag a "working demo" release
- [ ] [AB] T1 Test every scenario file loads (no missing combos)
- [ ] [AB] T1 Check numbers are plausible (flood area, population exposed) against known reality
- [ ] [AB] T1 Test on a phone and on the demo laptop, and on weak wifi
- [ ] [AB] T1 Test the demo path from a clean browser (no cache, no logged-in state)
- [ ] [AB] T1 **Feature freeze**: bug fixes only after this point

## Phase 10: Deployment

- [ ] [B] T1 Deploy frontend to Vercel; check the public URL
- [ ] [B] T1 Environment variables set on Vercel (never in the repo)
- [ ] [A] T2 API deployed and reachable; health check
- [ ] [B] T1 Offline fallback: a local build you can run without internet
- [ ] [B] T1 Shortened or custom URL for the slides

## Phase 11: Pitch and submission materials

- [ ] [B] T1 Slide: problem and impact (verified facts, sourced)
- [ ] [B] T1 Slide: existing systems and the gap we fill (ICPAC, Flood Hub, FEWS NET, Ushahidi)
- [ ] [B] T1 Slide: solution overview and user segments (rural vs urban)
- [ ] [B] T1 Slide: architecture diagram
- [ ] [A] T1 Slide: data sources and methods (HAND, SCS, calibration, census projection)
- [ ] [A] T1 Slide: backtest result (map + F1 / IoU)
- [ ] [AB] T1 Slide: limitations and how we handle them (data resolution, screening-level model, projection uncertainty)
- [ ] [B] T1 Slide: impact and who benefits (people, farmers, commuters, county governments, NGOs)
- [ ] [B] T1 Slide: roadmap (drought, IoT sensors, SMS/USSD, M-Pesa donations, live forecasts, ICPAC integration)
- [ ] [B] T1 Slide: sustainability and business model (county governments, NGOs, insurers, telcos)
- [ ] [B] T1 Slide: team
- [ ] [B] T1 Demo script (about 3 minutes) with a backup plan if the live demo fails
- [ ] [B] T1 Record a backup screen-capture demo
- [ ] [AB] T1 Rehearse twice, with timing, and prepare answers to likely questions (data accuracy, validation, sustainability, who will use it)
- [ ] [B] T1 README: what it is, how to run it, data sources, limitations, team
- [ ] [AB] T1 Check the submission requirements one more time and submit at least 2 hours early

## Phase 12: Final checks

- [ ] [AB] T1 Every real-world number on a slide has a verified source
- [ ] [AB] T1 Mocked and hypothetical parts are labelled as such
- [ ] [AB] T1 No API keys or credentials in the repo or in screenshots
- [ ] [AB] T1 Licences and attribution noted (OSM, CHIRPS, WorldPop, Copernicus, Google Open Buildings, FAO)
- [ ] [AB] T1 Repo is public or shared with the judges if required
- [ ] [AB] T1 Phones charged, charger, offline copy of the deck and demo video

---

## Cut list (in this order, if you run out of time)

1. XGBoost susceptibility model
2. Arrival-time layer
3. Mock user report
4. Swahili generation
5. SMS sandbox integration (keep a static phone-frame mock)
6. Nairobi reduced to a single neighbourhood

**Never cut:** the backtest slide, the rainfall slider demo, the exposure counter, the safe-route recommendation, the limitations slide.
