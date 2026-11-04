# Flood Early Warning System (Nairobi & Nyando)

An **impact-based flood early warning** prototype for an IGAD hackathon. Most systems tell you what the weather will do; this one tells a person what to do about it: where the water goes, who is exposed, where to move, which road to take, and what to do with their crops.

- **Pilot areas:** Nairobi (urban) and Nyando, Kisumu (rural)
- **Plan and tasks:** [`FLOOD_EWS_MVP_PLAN.md`](FLOOD_EWS_MVP_PLAN.md), [`TASKS.md`](TASKS.md)
- **Data contract (Person A ↔ Person B):** [`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md)
- **Demo script:** [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)

> The app currently runs on **mock data** (clearly labelled in the UI). Person A's pipeline output replaces it without code changes.

## Run it

Requires Node.js 20 or newer.

```bash
cd web
npm install
npm run mock:data   # regenerate mock data + population + validate (data is already committed)
npm run dev         # http://localhost:3000
```

| Command | What it does |
|---|---|
| `npm run dev` | Development server |
| `npm run build` / `npm run start` | Production build and server (also the offline fallback) |
| `npm run lint` | ESLint |
| `npm test` | Unit tests for the population maths |
| `npm run mock:data` | Writes all 20 mock scenarios, runs the population projection, validates everything |
| `npm run population` | Census projection from `web/data-inputs/census.csv` to `public/data/{area}/population.json` |
| `npm run validate:data` | Checks every file in `public/data` against the data contract |

## Swap in real data

1. Person A writes their files into `web/public/data/` using the paths and shapes in [`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md).
2. Set `"mock": false` in `meta.json` and `"source": "model"` in the exposure files.
3. Run `npm run validate:data`, then `npm run dev` and click through both areas.

Replace the placeholder census figures in `web/data-inputs/census.csv` with verified KNBS 2009/2019 numbers, then run `npm run population`.

## What's in the app

- Map with a Nairobi / Nyando switcher, flood risk layer (low / medium / high by water depth) and legend
- Rainfall slider (50–250 mm in 24 h), El Niño toggle, and an **Animate** button showing the pace of impact
- People and buildings at risk, with a low–high range and projection year
- Safe places (green = safe, grey = flooded), nearest-safe-place routes, and a commuter reroute with extra minutes
- Relocation to high ground and a farmer advisory for Nyando
- User types (commuter, resident, settler, farmer, trader) that change which panel is emphasised
- Tier 2: arrival-time layer, SMS alert preview in English and Kiswahili, optional Africa's Talking sandbox and Claude API advisories, mock blocked-road reports, drought roadmap tab
- About & limitations modal

## Stack

Next.js (App Router, TypeScript) + Tailwind CSS + MapLibre GL JS, with an OpenFreeMap basemap (falls back to OSM raster tiles). Data is static JSON/GeoJSON in `web/public/data/`, validated with zod. Two optional route handlers live in `web/src/app/api/`.

```
web/
  public/data/          contract files (mock now, real later)
  scripts/              mock generator, population projection, validator, tests
  data-inputs/          census.csv (placeholder)
  src/app/              page, layout, optional API routes
  src/components/       FloodApp, FloodMap, panels, ui
  src/lib/              schema (contract), types, data loader, geo, alert templates
docs/                   data contract, demo script
```

## Deploy to Vercel

1. Push the repo to GitHub.
2. In Vercel: **Add New → Project → Import** this repo.
3. Set **Root Directory = `web`**. The framework is detected as Next.js; keep the default build settings.
4. Optional environment variables (Settings → Environment Variables):
   - `ANTHROPIC_API_KEY`: plain-language farmer advisories
   - `AT_USERNAME` and `AT_API_KEY`: Africa's Talking **sandbox** test SMS
5. Deploy, then open the URL on a phone and a laptop.

Without those keys the app still works and uses fixed templates. Never commit `.env.local`.

**Offline fallback:** `cd web && npm run build && npm run start`, opened at http://localhost:3000 before the pitch. The basemap needs internet; flood layers, markers and routes still show without it.

## Data sources and licences

OpenStreetMap (ODbL), Copernicus DEM GLO-30 and FABDEM, CHIRPS, ESA WorldCover (CC BY 4.0), WorldPop (CC BY 4.0), Google Open Buildings (CC BY 4.0 / ODbL), Sentinel-1 (Copernicus), JRC Global Surface Water, KNBS census, NOAA ONI, FAO EcoCrop, KALRO. Basemap: OpenFreeMap, © OpenStreetMap contributors. Verify each licence before submission.

## Limitations

- Free elevation data (~30 m) is not accurate to the last metre. The model uses HAND and the output is a **screening-level** risk map.
- Flood extent is a calibrated approximation, not a hydraulic simulation.
- Population after 2019 is a projection with low / medium / high scenarios; informal settlements are likely undercounted.
- The rainfall slider is a **scenario tool, not a forecast**.
- Crop advice is rule-based and needs validation by local extension officers. Swahili text needs review by a native speaker.
- Mock data uses approximate, hand-entered coordinates.

## Team

- Person A: data and model
- Person B (Denning): app and pitch
