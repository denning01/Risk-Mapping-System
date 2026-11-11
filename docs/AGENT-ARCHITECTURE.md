# The agent grid — how it works here

A port of the multi-agent grid from `~/dev/markets`, made **self-contained**: own tmux session
(`igad`), own handoff directory (`/Users/mac/IGAD/rms-audit`), own LaunchAgent label
(`com.igad.boot-restore`), no reference to that project at runtime. Deleting `~/dev/markets` would not
affect it.

```
/Users/mac/IGAD/
  rms/                  data         operator desk + integration checkout   (window: operator)
  rms-model/            a/model      lead   ┐ window: model
  rms-model-audit/      detached     auditor┘
  rms-exposure/         a/exposure   lead   ┐ window: exposure
  rms-exposure-audit/   detached     auditor┘
  rms-audit/            outside git: <role>.md round logs, tasks/, mail/, handoffs/, STATE.md,
                        .watch/ (watcher log, heartbeat), .state/ (sessions, pane memory, .live/.stopped)
  data/                 outside git: rasters and caches ($RMS_DATA), shared by every worktree
  .venv/                one Python venv, symlinked into every worktree as .venv
```

## Pieces (all in `scripts/`)

| Script | Does |
|---|---|
| `tmux-agents.sh` | the launcher and the **watcher**. `--queue` builds windows (starts nothing), `--start` launches lead+auditor with assigned session ids, `--restore` brings everything back after a reboot, `--watch` is the loop |
| `operator-send.sh` | `npm run say` — types a message into a pane safely (refuses over a dialog or a draft, confirms submission) |
| `agent-msg.sh` | `npm run msg` — the lead ↔ operator rail (hub and spoke; no authority) |
| `state-tree.sh` | writes `rms-audit/STATE.md`; the watcher refreshes it about once a minute |
| `audit-findings.sh` / `agent-tasks.sh` | open findings / queue status |
| `merge-accepted.sh` | lands an ACCEPTed round on `data`: verdict, audited sha, no open findings, clean tree, `verify:all` |
| `verify-all.sh` | the gate: pytest, validate:data, web tests, tsc, lint, build |
| `bootstrap-agents.sh` | rebuilds all of the above from a clone (idempotent; `--check` changes nothing) |
| `boot-restore.sh` | `--install` a LaunchAgent that runs `--restore` at login |
| `test-audit-watch.sh` | runs the REAL watcher against a throwaway tmux session with fake Claude panes |

## What the watcher does, every 5 s

- A new `ROUND n · LEAD` (or `REMEDIATION · ROUND n`) with a `COMMIT:` line → the auditor pane is told,
  and its checkout is moved to that commit when it is idle and clean.
- A new `VERDICT:` → the lead pane is told (close findings; on ACCEPT take the next queue item).
- Mail in `rms-audit/mail/pending/` → a short pointer typed into the recipient's pane.
- A new file in `rms-audit/handoffs/` → the operator is told.
- It never types into a pane showing a permission dialog or a human's unsent text, and never into an
  auditor that is not in manual mode (it HOLDs and `npm run agents` shows why).
- Every 60 s: pane scrollback snapshots, session-id registry, revives a pane whose Claude died (from
  its saved conversation), regenerates STATE.md.
- It runs inside a respawn loop in the `watch` window (always the last tab): if it crashes it is back in
  5 s, and `npm run agents` reports a stale heartbeat as STUCK rather than running.

## Permission modes

Leads: `--permission-mode auto` (never `bypassPermissions`). Auditors: `manual --restricted` with the
allowlist in `rms-audit/auditor-settings.json`; commits and pushes are denied to them outright.

## Rebuild from nothing

```
git clone https://github.com/denning01/Risk-Mapping-System /Users/mac/IGAD/rms
cd /Users/mac/IGAD/rms && git switch data      # or: git switch -c data origin/data
npm run agents:bootstrap                      # venv, branches, worktrees, hooks, handoff dir, node_modules
npm run agents:bootstrap -- --check           # must say Complete
npm run agents -- --queue --all
npm run agents:boot -- --install
```
The handoff directory's CONTENT (rounds, queues, verdicts) is not in git; copy `rms-audit/` to move it.
