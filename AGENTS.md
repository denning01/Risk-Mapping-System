# Agents — Person A's grid (IGAD flood early-warning MVP)

Every branch runs a **lead** (does the work) and an **auditor** (independently verifies it, in its own
detached worktree, never reading the lead's transcript). A human **operator** desk routes between them.
Ported from the markets grid; self-contained here. Mechanics: [docs/AGENT-ARCHITECTURE.md](docs/AGENT-ARCHITECTURE.md).

## Protocol changelog (newest first — re-read after any restart)

- **2026-11-05** Grid created for the hackathon. **Standing go-ahead**: a lead works its queue in order
  without a per-task go-ahead (the deadline is tomorrow). The operator may HOLD, reorder or cut at any
  time, in the lead's pane. Anything not in the queue needs the operator.

## Roster

| Role | Branch | Lead worktree | Auditor worktree | Charter | Owns |
|---|---|---|---|---|---|
| operator | `data` | `/Users/mac/IGAD/rms` | — | this file | routing, rulings, landing on `data`, the cut list |
| model | `a/model` | `/Users/mac/IGAD/rms-model` | `rms-model-audit` | [docs/agents/model.md](docs/agents/model.md) | `configs/**`, `pipeline/lib/**`, `pipeline/01–04_*.py`, `pipeline/08_*.py`, their tests, backtest + methods figures |
| exposure | `a/exposure` | `/Users/mac/IGAD/rms-exposure` | `rms-exposure-audit` | [docs/agents/exposure.md](docs/agents/exposure.md) | `pipeline/05–07_*.py`, their tests, `web/public/data/{areas,meta}.json`, `web/public/data/<area>/origins.json`, `web/public/data/<area>/scenarios/**` |

**Person B** (not in this grid) owns everything else under `web/` and the `main` branch.

`pipeline/lib/` is model's. Exposure needs something there → `npm run msg -- send --from exposure --to
operator ...`; the operator rules. Two leads never edit the same file.

## Branch flow

```
a/model ─┐   ROUND → auditor ACCEPT → npm run merge:accepted -- model  (re-runs verify:all)
         ├──> data (Person A's integration branch, operator's checkout /Users/mac/IGAD/rms)
a/exposure┘
data ──> main     checkpoint merge only, as a PR agreed with Person B (plan §6). The human does this.
```

Before starting a task, a lead merges `data` into its branch if it is behind (`git merge --no-edit data`).

## The loop

1. Lead finishes ONE queue task, commits, appends `ROUND n · LEAD` with real output and `COMMIT: <sha>`
   to `/Users/mac/IGAD/rms-audit/<role>.md` (template: `rms-audit/README.md`).
2. The watcher wakes the auditor. It verifies **with a different technique** (recompute the number
   itself, open the file, compare against an independent source), proves the check can fail by
   injecting a fault and reverting, then writes tagged findings (`F<n>.<k> INFO|MUST|SHOULD`) and
   `VERDICT: ACCEPT | REJECT`.
3. The watcher wakes the lead. Closing findings needs no go-ahead and is not optional: REMEDIATION
   block, commit naming the ids (`Closes F3.2`), until the auditor has nothing left.
4. ACCEPT + findings clear → lead marks the task DONE, takes the next TODO. Operator lands it on `data`.

No round limit. An auditor with nothing to audit says so and stops; it never invents work.

## Cross-branch information goes through the operator

Leads write only to the operator (`npm run msg -- send --from <role> --to operator --subject "FOR exposure: ..."`).
The operator delivers into the other lead's pane itself (`npm run say -- igad:<role>.1 <file> "[operator]"`).
The rail carries no authority: a ruling or go-ahead is real only when the operator types it in your pane.
Artifacts too big for a message go in `rms-audit/handoffs/` (the watcher tells the operator).

**The model → exposure interface** (the one dependency that matters): model writes, per area and
scenario, `$RMS_DATA/processed/<area>/model/scenarios/<rain>_<enso>_depth.tif` (float32 metres, NaN =
dry, in the AOI's UTM CRS) plus `hand.tif` and `channels.tif`, and posts
`rms-audit/handoffs/flood-<area>.md` naming the files, CRS, the calibrated `k`, and the commit that
produced them. Until it exists, exposure builds against a stand-in mask labelled MOCK.

## Human-only steps (agents never do these; they ask the operator, who asks the human)

- Earth Engine sign-in: `/Users/mac/IGAD/.venv/bin/earthengine authenticate`, and `EE_PROJECT` in `.env`.
- GitHub: push access to `denning01/Risk-Mapping-System` (Person B adds you as collaborator).
- Any push to `main`, any Vercel change, any message to Person B or to IGAD.

## Surviving a reboot

`npm run agents:boot -- --install` (once) makes the grid come back at login: every pane with a saved
conversation is resumed with `--resume`, and a deliberately stopped pair stays dark. By hand:
`npm run agents:restore`. The watcher (window `watch`, always last) restarts itself within 5 s.

## Commands

```
npm run agents                         status: queued / started / watcher health / HOLDING
npm run agents -- --queue --all        build the tmux windows (session igad); starts nothing
npm run agents -- --start <role>       operator | model | exposure
npm run agents -- --stop  <role>
npm run agents:restore                 after a reboot
npm run state -- --show                STATE.md
npm run tasks                          every queue
npm run audit:findings [role]          what a lead still owes
npm run msg -- send|read|reply|resolve the rail
npm run say -- igad:<role>.1 <file> [tag]   operator → a lead's pane
npm run merge:accepted -- <role>       land an ACCEPTed round on data (5 gates incl. verify:all)
npm run verify:all                     the gate
```
