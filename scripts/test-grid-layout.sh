#!/usr/bin/env bash
# Tests for the grid's SHAPE — scripts/tmux-agents.sh. Run: npm run test:grid-layout
#
# Three claims made on 2026-09-21, none of which the other two suites can see:
#
#   1. the operator session is a first-class pane of this grid, not a window beside it
#   2. `watch` is the LAST window, always, whatever order things were queued in
#   3. the watcher is up whenever anything is provisioned, and comes back by itself if it dies
#
# Each is a layout claim, and CLAUDE.md rule 11 is that a layout check is not a liveness check. So
# every case here reads the running process or the real window list — never the pane title, never
# the launcher's own success message. Case 3b kills the watcher and waits for a DIFFERENT pid,
# because a respawn loop that has never been seen to respawn is not known to respawn.
#
# Runs the REAL launcher against a throwaway tmux session, a throwaway git repo and a fake `claude`.
set -uo pipefail

LAUNCHER="$(cd "$(dirname "$0")" && pwd)/tmux-agents.sh"
T="$(mktemp -d "${TMPDIR:-/tmp}/gltest.XXXXXX")"
SESS="gltest-$$"
DEV="$T/dev"; AUD="$DEV/rms-audit"
STATE="$AUD/.state"; WATCH="$AUD/.watch"
PASS=0; FAIL=0

cleanup() { tmux kill-session -t "$SESS" 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT

ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$1"; [ -n "${2:-}" ] && printf '        %s\n' "$2"; return 0; }

FAKE_BIN="'$T/bin/claude' '$T/fake.sh' '$T'"
run() { AGENTS_SESSION="$SESS" AGENTS_DEV_ROOT="$DEV" AGENTS_CLAUDE_BIN="$FAKE_BIN" \
        PATH="$T/bin:$PATH" bash "$LAUNCHER" "$@" 2>&1; }
wins() { tmux list-windows -t "$SESS" -F '#{window_name}' 2>/dev/null | tr '\n' ' ' | sed 's/ $//'; }
wpid() { cat "$WATCH/pid" 2>/dev/null; }
WATCHLOG="$WATCH/watch.log"

# ---- fixture ------------------------------------------------------------------
# Two roles are enough to prove ordering, and they are the two that changed: `operator` (new, must be
# first, works in ../markets itself on main) and `dashboard-ui` (which grew a real auditor worktree).
mkdir -p "$DEV" "$AUD" "$STATE" "$WATCH" "$T/bin"
git init -q "$DEV/markets"
git -C "$DEV/markets" -c user.email=t@t -c user.name=t commit -q --allow-empty -m base
git -C "$DEV/markets" branch -q -M main
git -C "$DEV/markets" branch feat/dashboard-ui main
git -C "$DEV/markets" worktree add -q "$DEV/markets-ui" feat/dashboard-ui
git -C "$DEV/markets" worktree add -q --detach "$DEV/markets-ui-audit" feat/dashboard-ui
mkdir -p "$DEV/markets-ui-audit/node_modules"   # validate_role refuses an auditor that cannot verify

cp /bin/bash "$T/bin/claude"; codesign -f -s - "$T/bin/claude" 2>/dev/null
"$T/bin/claude" -c true || { echo "fixture broken: cannot run the fake claude binary"; exit 1; }
cat > "$T/fake.sh" <<'FAKE'
D="$1"; shift
printf '%s\n' "$*" >> "$D/argv"
while :; do sleep 1; done
FAKE

# A foreign window, as devtmux really leaves one in the shared `markets` session. Ordering must not
# touch it: the launcher reorders its own windows, not another tool's.
PATH="$T/bin:$PATH" tmux new-session -d -s "$SESS" -n dev -c "$DEV"

echo "grid layout tests — session $SESS"

# ---- 1. ordering, queued in the WRONG order on purpose ------------------------
run --queue dashboard-ui >/dev/null
run --queue operator >/dev/null
got="$(wins)"
[ "$got" = "dev operator dashboard-ui watch" ] \
  && ok "queued out of order, ordered on screen: $got" \
  || bad "queued out of order, ordered on screen" "saw: $got"

case "$got" in "dev "*) ok "the foreign devtmux window keeps its place at the front" ;;
               *) bad "the foreign devtmux window keeps its place at the front" "$got" ;; esac

# ---- 2. the watcher is up from QUEUE alone, with no session started -----------
p1="$(wpid)"
[ -n "$p1" ] && kill -0 "$p1" 2>/dev/null \
  && ok "--queue alone brings the watcher up (pid $p1)" \
  || bad "--queue alone brings the watcher up" "pid file: '${p1:-none}'"

# and it is LAST, which is the half that used to depend on when it happened to be started
[ "$(tmux list-windows -t "$SESS" -F '#{window_name}' | tail -1)" = "watch" ] \
  && ok "watch is the last window" || bad "watch is the last window" "$(wins)"

# ---- 3. a window queued AFTER the watcher does not displace it ----------------
# This is the case the old code got wrong: ensure_watcher fired on the first --start, so anything
# provisioned later landed to the right of it.
run --queue operator >/dev/null           # already queued; the re-order must still run
tmux new-window -d -t "$SESS" -n zzlate 2>/dev/null
run --queue dashboard-ui >/dev/null
[ "$(tmux list-windows -t "$SESS" -F '#{window_name}' | tail -1)" = "watch" ] \
  && ok "a window created after the watcher does not displace it" \
  || bad "a window created after the watcher does not displace it" "$(wins)"
tmux kill-window -t "$SESS:zzlate" 2>/dev/null

# ---- 3b. MUTATION: kill the watcher; the pane must bring it back --------------
# Without this case "the watcher restarts itself" is a comment, not a behaviour. A tmux pane dies
# with its command, so before the respawn loop this kill took the whole window with it.
kill -9 "$p1" 2>/dev/null
i=0; p2=""
while [ "$i" -lt 25 ]; do
  sleep 1; i=$((i+1)); p2="$(wpid)"
  [ -n "$p2" ] && [ "$p2" != "$p1" ] && kill -0 "$p2" 2>/dev/null && break
  p2=""
done
[ -n "$p2" ] && ok "MUTATION: watcher killed -> respawned by its own pane (pid $p1 -> $p2, ${i}s)" \
             || bad "MUTATION: watcher killed -> respawned by its own pane" "still '$(wpid)' after ${i}s"
tmux list-windows -t "$SESS" -F '#{window_name}' | grep -qx watch \
  && ok "the watch window survived its watcher dying" || bad "the watch window survived its watcher dying" "$(wins)"

# ---- 3c. the watcher reloads itself when the launcher changes -----------------
# bash reads a script lazily, so editing the launcher under a long-running watcher leaves it running
# a mixture of old and new. Measured live on 2026-09-21: the heartbeat was 0s old (that line still
# ran) while the session registry had not been refreshed for 766s (that block had not) — `npm run
# agents` reported a healthy watcher that was half-dead. Now the loop notices and exits, and the
# respawn loop reloads it.
p3="$(wpid)"
touch "$LAUNCHER"
i=0; p4=""
while [ "$i" -lt 40 ]; do
  sleep 1; i=$((i+1)); p4="$(wpid)"
  [ -n "$p4" ] && [ "$p4" != "$p3" ] && kill -0 "$p4" 2>/dev/null && break
  p4=""
done
[ -n "$p4" ] && ok "launcher edited -> watcher reloaded itself (pid $p3 -> $p4, ${i}s)" \
             || bad "launcher edited -> watcher reloaded itself" "still $p3 after ${i}s"
grep -q "changed on disk" "$WATCHLOG" 2>/dev/null && ok "and it says why in the log" \
                                                  || bad "and it says why in the log" "$(tail -2 "$WATCHLOG" 2>/dev/null)"

# ---- 4. the operator is a real session in this grid ---------------------------
run --start operator >/dev/null
sleep 2
n="$(tmux list-panes -t "$SESS:operator" -F '#{pane_current_command}' 2>/dev/null | grep -c '^claude$')"
[ "$n" -eq 1 ] && ok "operator starts one running session (no auditor pane)" \
               || bad "operator starts one running session (no auditor pane)" "saw $n"
[ -f "$STATE/operator.live" ] && ok "operator is marked live, so --restore brings it back" \
                              || bad "operator is marked live, so --restore brings it back"
case "$(cat "$T/argv" 2>/dev/null)" in
  *"You are the OPERATOR session"*) ok "the operator prompt reached the launched process argv" ;;
  *) bad "the operator prompt reached the launched process argv" "$(head -c 200 "$T/argv" 2>/dev/null)" ;;
esac
case "$(cat "$T/argv" 2>/dev/null)" in
  *"You are the LEAD for main"*) bad "operator must not be launched with the LEAD prompt" ;;
  *) ok "operator is not launched with the LEAD prompt" ;;
esac

# ---- 5. dashboard-ui is audited like every other branch -----------------------
have_aud="$(tmux list-panes -t "$SESS:dashboard-ui" -F '#{@role}' 2>/dev/null | grep -c auditor)"
[ "$have_aud" -eq 1 ] && ok "dashboard-ui has an auditor pane" || bad "dashboard-ui has an auditor pane" "saw $have_aud"

# The watcher must now SEE that branch. With a round on the log and no pair started, the hold marker
# is the proof it looked: under the old table (audit "-") watch_role returned before reading the file
# at all, so no dashboard-ui marker could ever exist.
printf '# Audit log — dashboard-ui\n\nROUND 1 · LEAD · 2026-09-21T10:00+03 · test\nTASK: t\nCOMMIT:    test\n' > "$AUD/dashboard-ui.md"
AGENTS_SESSION="$SESS" AGENTS_DEV_ROOT="$DEV" AGENTS_CLAUDE_BIN="$FAKE_BIN" WATCH_SETTLE=0 \
  bash "$LAUNCHER" --watch --once >/dev/null 2>&1
if [ -f "$WATCH/dashboard-ui.held" ]; then
  ok "the watcher now reads dashboard-ui's log: $(cat "$WATCH/dashboard-ui.held" | cut -c1-58)…"
else
  bad "the watcher now reads dashboard-ui's log" "no $WATCH/dashboard-ui.held written"
fi
[ -f "$WATCH/operator.held" ] && bad "operator must stay out of the round protocol" "it wrote a hold marker" \
                              || ok "operator stays out of the round protocol (no auditor, no rounds)"

echo ""
printf '  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
