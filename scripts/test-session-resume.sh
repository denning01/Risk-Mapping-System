#!/usr/bin/env bash
# Tests for CONVERSATION SURVIVAL — scripts/tmux-agents.sh. Run: npm run test:session-resume
#
# The claim, added 2026-09-21: a pane that comes back after a reboot comes back INSIDE THE SAME
# CLAUDE CONVERSATION, not a fresh one with a generated brief. That rests on three things, and this
# file refuses to take any of them on trust:
#
#   1. the launcher ASSIGNS the conversation id (--session-id) instead of hoping to find it later
#   2. --restore relaunches with --resume <that id>, and only when the transcript is really on disk
#   3. a session it did not start (the operator's own pane) is ADOPTED by matching the transcript
#      born just after the process started — not by mtime, which is ambiguous when two sessions
#      share a working directory
#
# Case 4 and case 7 are the mutation tests. Delete the transcript and the launcher must fall back to
# a fresh session: a --resume against a missing file leaves a pane sitting at a shell prompt, which
# is the "looks started, is not" failure this whole file exists to prevent. Stop a role and it must
# stay dark, or "--stop is the opt-out" is a sentence rather than a behaviour.
#
# HOME is redirected into the fixture, so the transcripts these tests create are the fixture's own
# and the real ~/.claude/projects is never touched.
set -uo pipefail

LAUNCHER="$(cd "$(dirname "$0")" && pwd)/tmux-agents.sh"
T="$(mktemp -d "${TMPDIR:-/tmp}/srtest.XXXXXX")"
SESS="srtest-$$"
DEV="$T/dev"; AUD="$DEV/rms-audit"
STATE="$AUD/.state"; SESSD="$STATE/sessions"
PASS=0; FAIL=0

cleanup() { tmux kill-session -t "$SESS" 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT

ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$1"; [ -n "${2:-}" ] && printf '        %s\n' "$2"; return 0; }

FAKE_BIN="'$T/bin/claude' '$T/fake.sh' '$T'"
run() { HOME="$T" AGENTS_SESSION="$SESS" AGENTS_DEV_ROOT="$DEV" AGENTS_CLAUDE_BIN="$FAKE_BIN" \
        PATH="$T/bin:$PATH" bash "$LAUNCHER" "$@" 2>&1; }
argv()   { cat "$T/argv" 2>/dev/null; }
uuid_of(){ sed -n 's/^uuid=//p' "$SESSD/$1.session" 2>/dev/null | head -1; }
# Resolved, exactly as Claude Code's own getcwd() would be — the fixture lives under $TMPDIR, which
# on macOS is reached through /private, so the unresolved and resolved forms differ.
proj()   { printf '%s/.claude/projects/%s' "$T" "$(printf '%s' "$(cd "$1" && pwd -P)" | LC_ALL=C sed 's/[^A-Za-z0-9]/-/g')"; }
# Stand in for a Claude transcript. Only its existence and birth time matter to the launcher.
mktranscript() { mkdir -p "$(proj "$2")"; printf '{"type":"user"}\n' > "$(proj "$2")/$1.jsonl"; }
live_panes() { tmux list-panes -t "$SESS:$1" -F '#{pane_current_command}' 2>/dev/null | grep -c '^claude$'; }

# ---- fixture ------------------------------------------------------------------
mkdir -p "$DEV" "$AUD" "$STATE" "$SESSD" "$AUD/.watch" "$T/bin" "$T/.claude/projects"
git init -q "$DEV/markets"
git -C "$DEV/markets" -c user.email=t@t -c user.name=t commit -q --allow-empty -m base
git -C "$DEV/markets" branch -q -M main
git -C "$DEV/markets" branch a/model main
git -C "$DEV/markets" worktree add -q "$DEV/rms-model" a/model
git -C "$DEV/markets" worktree add -q --detach "$DEV/rms-model-audit" a/model
mkdir -p "$DEV/rms-model-audit/node_modules"
printf '# Audit log — security\n' > "$AUD/model.md"

cp /bin/bash "$T/bin/claude"; codesign -f -s - "$T/bin/claude" 2>/dev/null
"$T/bin/claude" -c true || { echo "fixture broken: cannot run the fake claude binary"; exit 1; }
cat > "$T/fake.sh" <<'FAKE'
D="$1"; shift
printf '%s\n' "$*" >> "$D/argv"
while :; do sleep 1; done
FAKE

PATH="$T/bin:$PATH" tmux new-session -d -s "$SESS" -n dev -c "$DEV"

echo "session resume tests — session $SESS"

# ---- 1. a started pane is given its conversation id up front ------------------
run --queue security >/dev/null
run --start security >/dev/null
sleep 2
U_LEAD="$(uuid_of security-lead)"; U_AUD="$(uuid_of security-audit)"
case "$U_LEAD" in
  [0-9a-f]*-*-*-*-*) ok "the lead pane was assigned a conversation id ($U_LEAD)" ;;
  *) bad "the lead pane was assigned a conversation id" "got '$U_LEAD'" ;;
esac
[ -n "$U_AUD" ] && [ "$U_AUD" != "$U_LEAD" ] && ok "the auditor got its own, different id" \
  || bad "the auditor got its own, different id" "lead=$U_LEAD audit=$U_AUD"
case "$(argv)" in *"--session-id $U_LEAD"*) ok "--session-id reached the launched process argv" ;;
                  *) bad "--session-id reached the launched process argv" "$(head -c 200 "$T/argv")" ;; esac

# ---- 2. the power-off ---------------------------------------------------------
# The transcripts Claude would have written, written here instead: the launcher's contract is with
# the file on disk, not with the process that made it.
mktranscript "$U_LEAD" "$DEV/rms-model"
mktranscript "$U_AUD"  "$DEV/rms-model-audit"
tmux kill-session -t "$SESS" 2>/dev/null; sleep 1
PATH="$T/bin:$PATH" tmux new-session -d -s "$SESS" -n dev -c "$DEV"
: > "$T/argv"

# ---- 3. restore RESUMES, it does not start a new conversation -----------------
out="$(run --restore)"; sleep 2
n="$(live_panes security)"
[ "$n" -eq 2 ] && ok "both panes running again after the power-off" || bad "both panes running again after the power-off" "saw $n"
case "$(argv)" in *"--resume $U_LEAD"*) ok "the lead was resumed by id, not restarted fresh" ;;
                  *) bad "the lead was resumed by id, not restarted fresh" "$(head -c 300 "$T/argv")" ;; esac
case "$(argv)" in *"--resume $U_AUD"*) ok "the auditor was resumed by id too" ;;
                  *) bad "the auditor was resumed by id too" ;; esac
case "$(argv)" in *"--session-id"*) bad "a resumed pane must not also be given a new id" ;;
                  *) ok "no new conversation id was minted for a resumed pane" ;; esac
case "$(argv)" in *"resumed"*"TIME HAS PASSED"*) ok "the resumed pane is told it was restarted" ;;
                  *) bad "the resumed pane is told it was restarted" ;; esac
case "$out" in *"resumed the existing conversation"*) ok "restore says it resumed rather than started" ;;
               *) bad "restore says it resumed rather than started" "$out" ;; esac

# ---- 4. MUTATION: no transcript -> fall back to a FRESH session ----------------
# Without this, "--resume only when the conversation is really there" is untested, and a deleted or
# moved transcript would leave a pane at a shell prompt looking exactly like a started one.
run --stop security >/dev/null 2>&1; sleep 1
rm -f "$(proj "$DEV/rms-model")/$U_LEAD.jsonl"
run --start security >/dev/null; sleep 2
NEW_LEAD="$(uuid_of security-lead)"
[ -n "$NEW_LEAD" ] && [ "$NEW_LEAD" != "$U_LEAD" ] && ok "MUTATION: transcript deleted -> a fresh conversation id was minted" \
  || bad "MUTATION: transcript deleted -> a fresh conversation id was minted" "still $NEW_LEAD"
case "$(argv)" in *"--resume $U_LEAD"*"--resume $U_LEAD"*) bad "it must not resume an id whose transcript is gone" ;;
                  *) ok "it did not resume an id whose transcript is gone" ;; esac

# ---- 5. --stop is the opt-out, and it is the ONLY one -------------------------
mktranscript "$NEW_LEAD" "$DEV/rms-model"
run --stop security >/dev/null 2>&1; sleep 1
[ -f "$STATE/security.stopped" ] && ok "--stop records a deliberate switch-off" || bad "--stop records a deliberate switch-off"
tmux kill-session -t "$SESS" 2>/dev/null; sleep 1
PATH="$T/bin:$PATH" tmux new-session -d -s "$SESS" -n dev -c "$DEV"
: > "$T/argv"
out2="$(run --restore)"; sleep 2
[ "$(live_panes security)" -eq 0 ] && ok "MUTATION: a role stopped on purpose stays dark through a restore" \
  || bad "MUTATION: a role stopped on purpose stays dark through a restore" "$out2"
case "$out2" in *"stopped on purpose"*) ok "restore says why it stayed dark" ;; *) bad "restore says why it stayed dark" "$out2" ;; esac

# ---- 6. a conversation with no .live marker still comes back ------------------
# The old rule restored only what --start had marked live. The new one restores anything with a
# conversation, so a pane lost to a crash BEFORE it was ever marked is not abandoned.
run --start security >/dev/null; sleep 2
rm -f "$STATE/security.live"                     # simulate the marker never having been written
tmux kill-session -t "$SESS" 2>/dev/null; sleep 1
PATH="$T/bin:$PATH" tmux new-session -d -s "$SESS" -n dev -c "$DEV"
: > "$T/argv"
run --restore >/dev/null; sleep 2
[ "$(live_panes security)" -eq 2 ] && ok "a conversation with no .live marker is still restored" \
  || bad "a conversation with no .live marker is still restored" "saw $(live_panes security)"

# ---- 6b. ONE pane dies: it is revived beside its live neighbour ---------------
# Found by killing a real pane on 2026-09-21: --restore refused the whole role, because pair_live()
# is true when EITHER pane runs, so a crashed auditor next to a working lead was never brought back.
# The pair is the unit for STARTING; the pane is the unit for RECOVERING.
APID="$(tmux list-panes -t "$SESS:security" -F '#{pane_id}' | tail -1)"
SHELLPID="$(tmux display -p -t "$APID" '#{pane_pid}')"
CPID="$(ps -ax -o pid=,ppid= | awk -v p="$SHELLPID" '$2==p {print $1; exit}')"
kill -9 "$CPID" 2>/dev/null; sleep 2
[ "$(live_panes security)" -eq 1 ] && ok "one pane killed, the other still running" \
  || bad "one pane killed, the other still running" "saw $(live_panes security) live"
: > "$T/argv"
out3="$(run --restore)"; sleep 2
[ "$(live_panes security)" -eq 2 ] && ok "the dead pane was revived beside the live one" \
  || bad "the dead pane was revived beside the live one" "$out3"
case "$(argv)" in *"--resume $(uuid_of security-audit)"*) ok "it was revived into its own conversation" ;;
                  *) bad "it was revived into its own conversation" "$(head -c 200 "$T/argv")" ;; esac
case "$out3" in *"revived"*) ok "restore says which panes it revived" ;; *) bad "restore says which panes it revived" "$out3" ;; esac

# MUTATION: a LIVE pane must never be typed into. Kill nothing, restore again, and the argv must not
# grow — reviving a working session would interrupt it mid-task, which is worse than the crash.
: > "$T/argv"
run --restore >/dev/null; sleep 2
[ -s "$T/argv" ] && bad "MUTATION: a fully live role must not be relaunched" "$(head -c 200 "$T/argv")" \
                 || ok "MUTATION: a fully live role was left completely alone"

# ---- 6c. behind main: a RESUME is let through, a fresh start is not -----------
# Found by destroying a real window: the restore refused it for being 1 commit behind main, so the
# conversation sat on disk unresumed. The gate stops a lead BEGINNING work on a stale base; a resume
# begins nothing. Both halves are asserted, because letting everything through would pass the first.
git -C "$DEV/markets" -c user.email=t@t -c user.name=t commit -q --allow-empty -m "main moves ahead"
run --stop security >/dev/null 2>&1; sleep 1
rm -f "$STATE/security.stopped"                      # the stop is not what is under test here
: > "$T/argv"
out4="$(run --restore)"; sleep 2
[ "$(live_panes security)" -eq 2 ] && ok "behind main: the conversation was still resumed" \
  || bad "behind main: the conversation was still resumed" "$out4"
case "$out4" in *"resuming anyway"*) ok "and it says the branch is behind, rather than staying quiet" ;;
                *) bad "and it says the branch is behind, rather than staying quiet" "$out4" ;; esac
case "$(argv)" in *"BEHIND main"*) ok "the resumed session is told so in its own first message" ;;
                  *) bad "the resumed session is told so in its own first message" "$(head -c 200 "$T/argv")" ;; esac

# MUTATION: with no conversation to resume, the same stale branch must still be REFUSED.
run --stop security >/dev/null 2>&1; sleep 1
rm -f "$STATE/security.stopped"
mv "$(proj "$DEV/rms-model")" "$T/hidden-transcripts"
: > "$T/argv"
out5="$(run --start security 2>&1)"; sleep 2
case "$out5" in *"REFUSED"*"behind main"*) ok "MUTATION: a FRESH start on a stale base is still refused" ;;
                *) bad "MUTATION: a FRESH start on a stale base is still refused" "$out5" ;; esac
mv "$T/hidden-transcripts" "$(proj "$DEV/rms-model")"
git -C "$DEV/rms-model" merge -q --no-edit main 2>/dev/null   # put the fixture back in step

# ---- 7. adoption: a session the launcher never started ------------------------
# The operator's own pane. Nothing tells the launcher which conversation is in it, so it matches the
# transcript born just after the process started — the case where two sessions share one directory
# and mtime cannot tell them apart.
tmux new-window -d -t "$SESS" -n agents -c "$DEV/markets"
APANE="$(tmux list-panes -t "$SESS:agents" -F '#{pane_id}' | head -1)"
tmux send-keys -t "$APANE" "clear; $T/bin/claude $T/fake.sh $T" C-m
sleep 2
U_ADOPT="$(uuidgen | tr 'A-Z' 'a-z')"
mktranscript "$U_ADOPT" "$DEV/markets"           # born AFTER the pane's process started
run --snapshot >/dev/null; sleep 1
[ "$(uuid_of adopt-agents-1)" = "$U_ADOPT" ] && ok "an unstarted pane's conversation was adopted by birth time" \
  || bad "an unstarted pane's conversation was adopted by birth time" "recorded '$(uuid_of adopt-agents-1)', expected $U_ADOPT"

# a decoy born BEFORE the process must never be chosen
U_OLD="$(uuidgen | tr 'A-Z' 'a-z')"
mktranscript "$U_OLD" "$DEV/markets"
touch -t 202001010000 "$(proj "$DEV/markets")/$U_OLD.jsonl"
rm -f "$SESSD/adopt-agents-1.session"
run --snapshot >/dev/null; sleep 1
[ "$(uuid_of adopt-agents-1)" = "$U_OLD" ] && bad "MUTATION: a transcript predating the process must not be adopted" \
  || ok "MUTATION: a transcript predating the process was not adopted"

# A pane with text already TYPED at its prompt — which is exactly how devtmux leaves its agents
# panes, `claude` typed and waiting for Enter. Without clearing that line first the resume arrives as
# `claudeclear; claude --resume …` and the pane runs nothing.
tmux kill-session -t "$SESS" 2>/dev/null; sleep 1
PATH="$T/bin:$PATH" tmux new-session -d -s "$SESS" -n dev -c "$DEV"
run --restore >/dev/null; sleep 2
APANE2="$(tmux list-panes -t "$SESS:agents" -F '#{pane_id}' | head -1)"
tmux send-keys -t "$APANE2" C-c; sleep 1
tmux send-keys -t "$APANE2" "claude"            # typed, NOT run — the devtmux state
: > "$T/argv"
run --restore >/dev/null; sleep 3
case "$(tmux capture-pane -p -t "$APANE2" | tr -d ' \n')" in
  *claudeclear*) bad "MUTATION: pre-typed text on the prompt must not be concatenated" ;;
  *) ok "MUTATION: a pane with text already typed was cleared before the resume" ;;
esac

# and after a power-off the window is rebuilt with its two panes and the conversation put back
tmux kill-session -t "$SESS" 2>/dev/null; sleep 1
PATH="$T/bin:$PATH" tmux new-session -d -s "$SESS" -n dev -c "$DEV"
: > "$T/argv"
run --restore >/dev/null; sleep 2
np="$(tmux list-panes -t "$SESS:agents" -F '#{pane_id}' 2>/dev/null | grep -c .)"
[ "$np" -eq 2 ] && ok "the adopted window came back with exactly 2 panes" || bad "the adopted window came back with exactly 2 panes" "saw $np"
# The id must be non-empty first: `--resume ` with nothing after it matches any resume line, which
# made this case pass while adoption was in fact broken.
# An adopted pane is named after its window, which owns no handoff log. The note must not send it to
# a file that does not exist — observed happening to a real resumed session on 2026-09-24.
case "$(argv)" in *"rms-audit/agents.md"*) bad "an adopted pane must not be told to read a handoff log it has none of" ;;
                  *) ok "an adopted pane is not sent to a handoff log that does not exist" ;; esac
case "$(argv)" in *"$AUD/model.md"*) ok "a role WITH a handoff log is still told to read it" ;;
                  *) bad "a role WITH a handoff log is still told to read it" "$(head -c 200 "$T/argv")" ;; esac

UA="$(uuid_of adopt-agents-1)"
if [ -z "$UA" ]; then bad "the operator's own conversation was resumed into it" "no id was ever recorded"
else
  case "$(argv)" in *"--resume $UA"*) ok "the operator's own conversation was resumed into it" ;;
                    *) bad "the operator's own conversation was resumed into it" "$(head -c 300 "$T/argv")" ;; esac
fi

echo ""
printf '  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
