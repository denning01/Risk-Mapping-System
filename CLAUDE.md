# Working agreement — IGAD flood early-warning MVP (Person A grid)

**Hackathon. The MVP is submitted to IGAD tomorrow.** Read `FLOOD_EWS_MVP_PLAN.md` (the plan),
`TASKS.md` (the master list), `docs/DATA_CONTRACT.md` (what the app reads) and **[AGENTS.md](AGENTS.md)**
(who does what, the lead/auditor loop) before anything else.

## Start here, every session

0. `npm run state -- --show` — the generated picture of the grid (`../rms-audit/STATE.md`).
1. `git branch --show-current`, then find your role in AGENTS.md and open `docs/agents/<role>.md`.
2. Read your charter's **Lessons log**. Append to it in the same commit when you learn something a
   future session would otherwise rediscover the hard way.
3. Your queue is `../rms-audit/tasks/<role>.md`. Work it in order.

## Who is who

- **Person A** (the human running this grid) owns data and model. This grid does Person A's work.
- **Person B** owns `web/` (the Next.js app, pitch, deploy) and `main`. The app is already built on
  mock data. Our job is to replace the mock data with real pipeline output **without any change to
  `web/src`** — `docs/DATA_CONTRACT.md` is the interface. A contract change goes through the operator
  to the human, who agrees it with Person B. Never edit `web/src`, `web/scripts`, `web/package.json`,
  `web/public/data/advice/**` or `web/public/data/*/population.json` (Person B's).

## The non-negotiables (from the plan; they decide whether judges trust us)

1. **Honest numbers.** Every number that can reach a slide carries: value, unit, how it was computed,
   and its source. A ROUND lists them under `NUMBERS:`. Real-world facts (event dates, census totals,
   impacts) are verified from a primary source (KNBS, ICPAC, OCHA, KMD, Copernicus EMS) with the URL —
   never from memory. Numbers in the plan marked *(verify)* are unverified until a round verifies them.
2. **Mocked or hypothetical is labelled.** A scenario is a scenario, not a forecast. Anything not from
   the model keeps `"source":"mock"` / `"mock": true`. Flipping `meta.json` to `"mock": false` is the
   last step, after real files exist for all 20 scenarios.
3. **Screening-level, said plainly.** HAND + SCS is a calibrated approximation, not a hydraulic model.
   Report the backtest F1/IoU honestly even if modest.
4. **The backtest, the slider demo, the exposure counter, the safe route and the limitations slide are
   never cut.** Everything else follows the plan's cut list (§8) when time runs short.
5. **Coordinates out are WGS84 lon/lat.** Rasters are processed in the AOI's UTM zone (Nairobi and
   Nyando are both in UTM 37S/36S — check, do not assume) and reprojected on export.

## Reporting standard — evidence, not description

Every claim carries the evidence that makes it checkable. A description of what the code does is not
an answer.

| Claim | Required evidence |
|---|---|
| "the code does X" | the lines, with `path:line` |
| "the output is right" | the command, its REAL output, and a check by a second method (e.g. area from pixel count AND from the polygon) |
| "N people exposed" | the computation, the inputs' sources and years, and the low/medium/high range |
| "the file matches the contract" | `cd web && npm run validate:data` output, pasted |
| any pass/fail | the command and its real output — never a predicted one |

1. **Run it. Paste the output.** If a command could not run (no Earth Engine auth, no network), say so.
2. **Separate verified from assumed**, explicitly. Every ROUND has a `NOT VERIFIED:` line.
3. **A suspiciously easy success is a finding.** An empty GeoJSON that validates, a 2 ms test run, a
   flood map that is all-low or all-high, an F1 of 0.99 — check before reporting.
4. **Never build a list a decision rests on from a truncated command** (`| head`, filtered grep).
   Write the full result to a file and count it.
5. **Never put a credential in a command or a file in git.** Reference it from the environment
   (`$EE_PROJECT`). Earth Engine sign-in is a human step (`../.venv/bin/earthengine authenticate`).
6. **Name what you did not check.**

## Data layout

- Heavy files live OUTSIDE git, shared by every worktree: `$RMS_DATA` (default `/Users/mac/IGAD/data`).
  `raw/<area>/…` (exports), `processed/<area>/model/…` (written only by the model lead),
  `processed/<area>/exposure/…` (only by the exposure lead), `audit/…` (auditors' own recomputations).
- What the app reads is committed: `web/public/data/**` per `docs/DATA_CONTRACT.md`, a few MB per file.
- Python: `.venv/bin/python` (a symlink to the shared `/Users/mac/IGAD/.venv`). Add a dependency to
  `requirements.txt` in the same commit that first imports it.

## Verification commands

```
npm run verify:all                      # the gate: pytest, validate:data, web tests, tsc, lint, build
.venv/bin/python -m pytest -q           # pipeline unit tests
cd web && npm run validate:data         # the contract with Person B's app
cd web && npm run dev                   # click through both areas, all rainfall values
```

## How we build

Small, verified, committed increments. One task per round. Lean: the simplest thing that is actually
correct and verified. A working demo beats a complete system (plan §0) — but a number on a slide that
is wrong loses the room.
