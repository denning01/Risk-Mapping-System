# Data contract: Person A (pipeline) → Person B (app)

The app is **fully static**. It reads only the files below from `web/public/data/`. Person A's pipeline must write exactly these paths and shapes; then the app works with **zero code changes**.

Check your files before handing them over:

```bash
cd web && npm run validate:data
```

The runtime schemas live in `web/src/lib/schema.ts` (zod). If a shape must change, change it there **and** in this doc, and tell the other person.

## Files

```
web/public/data/
  areas.json
  meta.json
  advice/crops.json
  {area}/origins.json
  {area}/population.json                       # written by Person B (npm run population)
  {area}/scenarios/{rain}_{enso}.geojson       # flood polygons
  {area}/scenarios/{rain}_{enso}.exposure.json # people & buildings at risk
  {area}/scenarios/{rain}_{enso}.shelters.json # safe places
  {area}/scenarios/{rain}_{enso}.routes.json   # one route per origin
```

- `area`: `nairobi` | `nyando`
- `rain`: `50` | `100` | `150` | `200` | `250` (mm in 24 h)
- `enso`: `normal` | `elnino`
- 2 × 5 × 2 = **20 scenarios**. Every one of the 4 scenario files must exist for every combination.
- Coordinates are **WGS84 lon/lat (EPSG:4326)**. Reproject from UTM before export.

## Shapes

### areas.json
```json
[{"id":"nairobi","name":"Nairobi (urban)","type":"urban","bbox":[36.78,-1.33,36.92,-1.22],
  "center":[36.85,-1.275],"zoom":12.5,"user_types":["commuter","informal_settlement_resident","trader"]}]
```

### {rain}_{enso}.geojson
A FeatureCollection of `Polygon` or `MultiPolygon` features:
```json
{"risk":"low|medium|high","depth_m":0.6,"arrival_h":3.5}
```
- `risk` comes from water depth: under 0.3 m = low, 0.3–1 m = medium, over 1 m = high.
- `arrival_h` (hours until water arrives) may be `null`. The arrival-time toggle only shows when values exist.
- Keep each file to a few MB: dissolve cells by `(risk, arrival bin)` and simplify.

### {rain}_{enso}.exposure.json
```json
{"year":2026,"population":{"low":9800,"medium":12400,"high":14900},
 "buildings":3100,"flooded_area_km2":18.4,"roads_cut":["Juja Road"],"source":"model"}
```
Set `source` to `"model"` for real output (`"mock"` shows a Mock badge).

### {rain}_{enso}.shelters.json
```json
[{"id":"s1","name":"Example Primary School","type":"school","lon":35.0,"lat":-0.2,"capacity":null,"safe":true}]
```
`type`: `school` | `church` | `hospital` | `community_hall` | `high_ground`. `safe` is false when the shelter is inside the flood extent for that scenario.

### {area}/origins.json
Named demo starting points (routes are precomputed, not computed live).
```json
[{"id":"o1","name":"Mathare","lon":36.858,"lat":-1.260,"user_type":"informal_settlement_resident"}]
```
`user_type` must be one of the area's `user_types`.

### {rain}_{enso}.routes.json
One entry per origin:
```json
[{"origin_id":"o1","kind":"to_shelter","shelter_id":"s1","destination_name":"Example Primary School",
  "baseline":null,
  "safe":{"geometry":{"type":"LineString","coordinates":[[36.85,-1.26],[36.86,-1.25]]},"minutes":12},
  "avoided":["Juja Road"]}]
```
- `kind`: `to_shelter` | `commute` | `relocation`.
- `shelter_id` is `null` for `commute`.
- `baseline` is the usual route, needed only for `commute`; `null` otherwise. If the usual route is clear, make `safe` equal to `baseline` (same minutes) and `avoided` empty.

### advice/crops.json
```json
[{"crop":"maize","season":"short_rains","enso":"elnino","risk":"high",
  "actions":["Delay planting until flood risk passes"],"sources":["FAO EcoCrop","KALRO"]}]
```
`season`: `short_rains` | `long_rains`.

### meta.json
```json
{"mock":false,"generated_at":"2026-11-05T10:00:00Z","sources":["Copernicus DEM","CHIRPS"],"notes":"Screening-level model, not a forecast"}
```
Set `mock` to `false` when real data replaces the mock; the MOCK DATA badge then disappears.

### {area}/population.json (Person B)
Written by `npm run population` from `web/data-inputs/census.csv`. Person A uses these totals to scale WorldPop when computing exposure.

**Why county / sub-county level:** ward boundaries changed between the 2009 and 2019 censuses (wards were created in 2013), so ward-level growth rates are not comparable. Compute `r` at county or sub-county level and apply it to 2019 counts.

```
r     = (p2019 / p2009)^(1/10) - 1
P(t)  = p2019 * (1 + r)^(t - 2019)
low   = r * 0.7   medium = r   high = r * 1.2   (assumptions)
```

## Handover checklist for Person A
1. Write all files above into `web/public/data/` (overwrite the mock ones). Keep `advice/crops.json` and `population.json` unless you changed them.
2. Set `meta.json` `"mock": false` and exposure `"source": "model"`.
3. Run `npm run validate:data` and fix anything it lists.
4. Run `npm run dev` and click through both areas and all rainfall values.
