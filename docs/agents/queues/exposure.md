# Tasks — exposure  (branch a/exposure) · Person A: people, buildings, shelters, routes, scenario files for the app
# Format: <id> | <state> | <round-or-"-"> | <title>   States: TODO WIP AUDIT DONE BLOCKED:<what>
# Work in order (standing go-ahead). Done-criteria for each id are in docs/agents/exposure.md.
# NEVER cut: exposure counter, safe-route recommendation.

E-01 | TODO | - | 07_scenarios.py writer: emits all 20 x 4 contract files from a flood-depth raster input; proven end to end on a stand-in mask labelled MOCK; validate:data green
E-02 | TODO | - | 06_routing.py data: osmnx drive+walk graphs for both AOIs, travel times, shelters from OSM tags (school, place_of_worship, hospital/clinic, community_centre, police) cached in $RMS_DATA
E-03 | TODO | - | origins.json for both areas: named demo points verified against OSM, user_type valid for the area
E-04 | TODO | - | 05_population.py: WorldPop scaled to Person B's population.json totals (dasymetric), sums checked, exposed people low/medium/high per scenario; buildings at risk (Google Open Buildings)
E-05 | TODO | - | Routes per scenario: drop flooded edges, nearest SAFE shelter per origin, Nairobi commute baseline vs safe (+minutes, avoided road names), Nyando relocation sites ranked (HAND, slope, road, school/clinic)
E-06 | TODO | - | Real run, Nyando: 07_scenarios on model's flood-nyando hand-off; plausibility check; source:"model"
E-07 | TODO | - | Real run, Nairobi: same on flood-nairobi hand-off; then meta.json mock:false ONLY when all 20 scenarios are real; validate:data; click-through both areas
E-08 | TODO | - | Slides numbers: exposure with ranges + projection year, compared against reported impacts of the 2023 Nyando / 2024 Nairobi events (sourced)
