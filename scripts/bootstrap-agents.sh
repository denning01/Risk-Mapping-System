#!/usr/bin/env bash
# One command to rebuild Person A's agent grid for the IGAD flood early-warning hackathon.
# Ported from the markets grid (~/dev/markets) but SELF-CONTAINED: nothing here reads, starts or
# depends on that project. Own tmux session (`igad`), own handoff dir, own LaunchAgent label.
#
#   npm run agents:bootstrap            create everything that is missing (idempotent)
#   npm run agents:bootstrap -- --check report what is missing; change nothing
#   npm run agents:bootstrap -- --force re-run npm ci even where node_modules exists
#
# What it builds (docs/AGENT-ARCHITECTURE.md says why each piece exists):
#   2 role branches + 5 worktrees under /Users/mac/IGAD:
#     rms                 data         operator / integration (Person A's branch, per the plan)
#     rms-model           a/model      lead   · rms-model-audit     detached auditor
#     rms-exposure        a/exposure   lead   · rms-exposure-audit  detached auditor
#   ../rms-audit/       handoff directory, outside git: one round log + one task queue per role
#   ../.venv            ONE shared Python venv (geo stack is ~1 GB; identical for every worktree)
#   web/node_modules    per worktree (verify:all and validate:data need it)
#   core.hooksPath -> .githooks  (audit read-only, findings gate, 20 MB guard, credential guard)
set -uo pipefail

CHECK=0; FORCE=0
for a in "$@"; do case "$a" in --check) CHECK=1 ;; --force) FORCE=1 ;; esac; done

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEV="$(cd "$REPO/.." && pwd)"
AUDIT="$DEV/rms-audit"
VENV="$DEV/.venv"
INTEG="data"

missing=0; made=0
say()  { printf '  %s\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
add()  { printf '  \033[36m+\033[0m %s\n' "$*"; made=$((made+1)); }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; missing=$((missing+1)); }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# role | branch | lead dir | audit dir
ROWS=(
  "model|a/model|rms-model|rms-model-audit"
  "exposure|a/exposure|rms-exposure|rms-exposure-audit"
)
all_dirs() { echo rms; for r in "${ROWS[@]}"; do IFS='|' read -r _ _ l a <<<"$r"; echo "$l"; echo "$a"; done; }

# ---- 1. prerequisites --------------------------------------------------------
step "1. Prerequisites"
for t in git node npm tmux; do
  command -v "$t" >/dev/null 2>&1 && ok "$t  $($t --version 2>&1 | head -1 | cut -c1-40)" || bad "$t is not installed"
done
command -v claude >/dev/null 2>&1 && ok "claude CLI" || bad "claude CLI not on PATH — the panes cannot launch without it"
[ "$(git -C "$REPO" branch --show-current)" = "$INTEG" ] && ok "$REPO is on $INTEG" || bad "$REPO must be on '$INTEG' (git -C $REPO switch $INTEG)"

# ---- 2. Python venv (shared) ---------------------------------------------------
step "2. Shared Python venv  $VENV"
if [ -x "$VENV/bin/python" ]; then
  ok "venv ($("$VENV/bin/python" --version 2>&1))"
  if "$VENV/bin/python" -c "import pysheds.grid, rasterio, geopandas, osmnx, xgboost, ee, pytest" 2>/dev/null; then
    ok "geo stack imports (pysheds rasterio geopandas osmnx xgboost ee pytest)"
  elif [ "$CHECK" = 1 ]; then bad "geo stack does not import"
  else "$VENV/bin/pip" install -q -r "$REPO/requirements.txt" && add "pip install -r requirements.txt" || bad "pip install failed"; fi
elif [ "$CHECK" = 1 ]; then bad "no venv at $VENV"
else
  py="$(command -v python3.12 || command -v python3.11 || command -v python3)"
  "$py" -m venv "$VENV" && "$VENV/bin/pip" install -q --upgrade pip && "$VENV/bin/pip" install -q -r "$REPO/requirements.txt" \
    && add "venv created with $("$VENV/bin/python" --version)" || bad "venv creation failed"
fi

# ---- 3. branches -------------------------------------------------------------
step "3. Role branches (from $INTEG)"
for row in "${ROWS[@]}"; do
  IFS='|' read -r role branch lead audit <<<"$row"
  if git -C "$REPO" show-ref --verify --quiet "refs/heads/$branch"; then ok "$branch"
  elif [ "$CHECK" = "1" ]; then bad "$branch missing"
  else git -C "$REPO" branch "$branch" "$INTEG" >/dev/null 2>&1 && add "$branch created from $INTEG"; fi
done

# ---- 4. worktrees ------------------------------------------------------------
# A lead worktree is ON its branch. An audit worktree is DETACHED: git refuses one branch in two
# worktrees, and detaching makes the audit checkout read-mostly for free.
step "4. Worktrees"
for row in "${ROWS[@]}"; do
  IFS='|' read -r role branch lead audit <<<"$row"
  lp="$DEV/$lead"
  if [ -d "$lp" ]; then
    cur="$(git -C "$lp" branch --show-current 2>/dev/null)"
    [ "$cur" = "$branch" ] && ok "$lead  ($branch)" || bad "$lead is on '${cur:-detached}', expected $branch"
  elif [ "$CHECK" = "1" ]; then bad "$lead missing"
  else git -C "$REPO" worktree add "$lp" "$branch" >/dev/null 2>&1 && add "$lead  ($branch)"; fi
  ap="$DEV/$audit"
  if [ -d "$ap" ]; then
    [ -z "$(git -C "$ap" branch --show-current 2>/dev/null)" ] && ok "$audit  (detached)" \
      || bad "$audit is ON a branch; it must be detached — git -C $ap checkout --detach $branch"
  elif [ "$CHECK" = "1" ]; then bad "$audit missing"
  else git -C "$REPO" worktree add --detach "$ap" "$branch" >/dev/null 2>&1 && add "$audit  (detached)"; fi
done

# ---- 5. per-worktree .venv link and .env copy ----------------------------------
# .venv is a SYMLINK to the shared venv. .env is COPIED, never symlinked, so one session cannot
# repoint another's keys.
step "5. Per-worktree .venv link and .env"
for d in $(all_dirs); do
  p="$DEV/$d"; [ -d "$p" ] || continue
  if [ -L "$p/.venv" ] || [ -d "$p/.venv" ]; then ok "$d/.venv"
  elif [ "$CHECK" = 1 ]; then bad "$d/.venv missing"
  else ln -s "$VENV" "$p/.venv" && add "$d/.venv -> $VENV"; fi
  if [ -f "$REPO/.env" ] && [ "$d" != rms ]; then
    if [ -L "$p/.env" ]; then bad "$d/.env is a SYMLINK — replace with a copy"
    elif [ -f "$p/.env" ]; then ok "$d/.env"
    elif [ "$CHECK" = 1 ]; then bad "$d/.env missing"
    else cp "$REPO/.env" "$p/.env" && add "$d/.env copied"; fi
  fi
done
[ -f "$REPO/.env" ] || warn "no $REPO/.env — fine until a lead needs EE_PROJECT or an API key (see .env.example)"

# ---- 6. handoff directory ----------------------------------------------------
# Outside git ON PURPOSE: uncommitted work and other checkouts are invisible across worktrees; a
# plain shared directory is visible to every pane immediately.
step "6. Handoff directory  $AUDIT"
for sub in "" briefs tasks handoffs mail/pending mail/delivered mail/resolved .launch .watch .state; do
  if [ -d "$AUDIT/$sub" ]; then ok "${sub:-rms-audit}/"
  elif [ "$CHECK" = 1 ]; then bad "${sub:-rms-audit}/ missing"
  else mkdir -p "$AUDIT/$sub" && add "${sub:-rms-audit}/"; fi
done

# ---- 7. per-role audit logs; operator log ------------------------------------
step "7. Audit logs and queues"
for row in "${ROWS[@]}"; do
  IFS='|' read -r role branch lead audit <<<"$row"
  f="$AUDIT/$role.md"
  if [ -f "$f" ]; then ok "$role.md"
  elif [ "$CHECK" = "1" ]; then bad "$role.md missing"
  else
    { printf '# Audit log — %s  (branch %s)\n\n' "$role" "$branch"
      printf 'Protocol: ./README.md · Charter: docs/agents/%s.md · Queue: ./tasks/%s.md\n' "$role" "$role"
      printf "Append only. The auditor reads this file and the repo, never the lead's transcript.\n\n"
      printf '<!-- rounds are appended below this line -->\n'; } > "$f"
    add "$role.md"
  fi
  t="$AUDIT/tasks/$role.md"
  if [ -f "$t" ]; then ok "tasks/$role.md"
  elif [ "$CHECK" = 1 ]; then bad "tasks/$role.md missing"
  elif [ -f "$REPO/docs/agents/queues/$role.md" ]; then cp "$REPO/docs/agents/queues/$role.md" "$t" && add "tasks/$role.md (seeded from docs/agents/queues/)"
  else bad "tasks/$role.md missing and no seed in docs/agents/queues/"; fi
done
f="$AUDIT/operator.md"
if [ -f "$f" ]; then ok "operator.md"
elif [ "$CHECK" = "1" ]; then bad "operator.md missing"
else printf '# Operator log — data (Person A)\n\nWhat the operator routed, ruled and landed. Append, newest at the bottom.\n\n<!-- entries are appended below this line -->\n' > "$f"; add "operator.md"; fi
if [ -f "$AUDIT/README.md" ]; then ok "README.md (round protocol)"
elif [ "$CHECK" = 1 ]; then bad "README.md missing"
else cp "$REPO/docs/agents/HANDOFF-README.md" "$AUDIT/README.md" && add "README.md (from docs/agents/HANDOFF-README.md)"; fi

# ---- 8. auditor permission allowlist -----------------------------------------
# manual mode + this allowlist: an UNLISTED command stops and asks. Python IS allowlisted: auditing
# geodata means recomputing numbers from rasters and GeoJSON. Independence comes from the auditor
# writing its OWN check, not from being unable to run code. Commits and pushes are denied outright.
step "8. Auditor allowlist"
as="$AUDIT/auditor-settings.json"
if [ -f "$as" ]; then ok "auditor-settings.json"
elif [ "$CHECK" = "1" ]; then bad "auditor-settings.json missing"
else
  cat > "$as" <<EOF
{
  "permissions": {
    "allow": [
      "Bash(npm run verify:all)", "Bash(npm run verify:*)", "Bash(npm run audit:findings:*)",
      "Bash(cd web && npm run validate:data)", "Bash(cd web && npm test:*)", "Bash(cd web && npx tsc:*)",
      "Bash(.venv/bin/python:*)", "Bash(.venv/bin/pytest:*)",
      "Bash(git status:*)", "Bash(git log:*)", "Bash(git diff:*)", "Bash(git show:*)",
      "Bash(git branch:*)", "Bash(git rev-parse:*)", "Bash(git ls-files:*)", "Bash(git blame:*)",
      "Bash(git checkout --detach:*)",
      "Bash(rg:*)", "Bash(grep:*)", "Bash(jq:*)", "Bash(sed:*)", "Bash(awk:*)", "Bash(head:*)",
      "Bash(tail:*)", "Bash(cat:*)", "Bash(diff:*)", "Bash(comm:*)", "Bash(ls:*)", "Bash(wc:*)",
      "Bash(sort:*)", "Bash(uniq:*)", "Bash(echo:*)", "Bash(pwd)", "Bash(du:*)", "Bash(file:*)",
      "Edit(/$AUDIT/**)", "Read(/$AUDIT/**)"
    ],
    "deny": [
      "Read(/$HOME/.claude/projects/**)",
      "Bash(git -C:*)", "Bash(git --git-dir:*)", "Bash(git --work-tree:*)",
      "Bash(git push:*)", "Bash(git commit:*)"
    ]
  }
}
EOF
  add "auditor-settings.json"
fi

# ---- 9. git hooks ------------------------------------------------------------
step "9. Git hooks"
hp="$(git -C "$REPO" config core.hooksPath 2>/dev/null)"
if [ "$hp" = ".githooks" ]; then ok "core.hooksPath = .githooks"
elif [ "$CHECK" = "1" ]; then bad "core.hooksPath is '${hp:-unset}', expected .githooks"
else git -C "$REPO" config core.hooksPath .githooks && add "core.hooksPath set"; fi
for h in pre-commit commit-msg; do
  [ -x "$REPO/.githooks/$h" ] && ok ".githooks/$h" || bad ".githooks/$h missing or not executable"
done

# ---- 10. web dependencies per worktree ----------------------------------------
step "10. web/node_modules per worktree"
for d in $(all_dirs); do
  p="$DEV/$d/web"; [ -d "$p" ] || continue
  if [ -d "$p/node_modules" ] && [ "$FORCE" = "0" ]; then ok "$d/web"
  elif [ "$CHECK" = "1" ]; then bad "$d/web has no node_modules"
  else say "npm ci in $d/web…"; (cd "$p" && npm ci --no-audit --no-fund >/dev/null 2>&1) && add "$d/web" || bad "$d/web npm ci FAILED"; fi
done

# ---- 11. human-only steps (reported, never automated) ---------------------------
step "11. Human-only steps"
if [ -f "$HOME/.config/earthengine/credentials" ]; then ok "Earth Engine credentials present"
else warn "Earth Engine NOT authenticated — you run:  $VENV/bin/earthengine authenticate   (browser sign-in; agents cannot)"; fi
perm="$(gh api repos/denning01/Risk-Mapping-System --jq .permissions.push 2>/dev/null)"
[ "$perm" = "true" ] && ok "GitHub push access to denning01/Risk-Mapping-System" \
  || warn "no push access to denning01/Risk-Mapping-System — ask Person B to add you as a collaborator"

step "Summary"
if [ "$CHECK" = "1" ]; then
  if [ "$missing" -eq 0 ]; then printf '  \033[32mComplete — every piece is present.\033[0m\n'; exit 0
  else printf '  \033[31m%s item(s) missing.\033[0m Run without --check to create them.\n' "$missing"; exit 1; fi
fi
[ "$made" -gt 0 ] && say "created $made item(s)" || say "nothing to create — already complete"
cat <<'NEXT'

  Next:
    npm run agents -- --queue --all       build the tmux layout (session `igad`); starts NOTHING
    npm run agents -- --start operator    the operator desk
    npm run agents -- --start model       lead + auditor
    npm run agents -- --start exposure    lead + auditor
    npm run agents:boot -- --install      bring the grid back by itself after a reboot
NEXT
[ "$missing" -gt 0 ] && exit 1 || exit 0
