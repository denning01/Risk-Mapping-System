#!/usr/bin/env bash
# Operator -> one pane. The only sanctioned way for the operator session to put a ruling or a
# go-ahead into a lead's own pane (AGENTS.md § Cross-branch information: a ruling goes from the
# operator to the affected lead, in that lead's pane, never relayed through a third agent).
#
#   npm run say -- <pane> <file> [tag]
#   npm run say -- markets:payments.1 /tmp/msg.txt "[operator 20260926]"
#
# WHY THIS EXISTS AS A SCRIPT AND NOT AS THREE TMUX COMMANDS
# On 2026-09-22 the operator delivered four go-aheads by hand. All four arrived SPLIT: the payments
# lead reported "your message reached me truncated. It opens mid-sentence" and refused to guess at
# two constraints it could not read — correctly. Two defects, both fixed here:
#
#   1. Enter was sent one second after paste-buffer, on a timer. A long paste had not finished
#      landing, so Enter submitted a fragment and the tail became a second message.
#   2. The message file ended with a newline, so the paste left the composer in multi-line mode and
#      the first Enter added a line instead of submitting.
#
# So the timer is gone. Delivery is confirmed through THREE states of the input box — a signal the
# receiving session does not control, per CLAUDE.md rule 11 — and the script claims nothing it has
# not observed:
#
#   before   box empty        (no dialog, no unsent human draft)   else REFUSE, send nothing
#   after    box NOT empty    (the paste actually landed)          else REFUSE, nothing was typed
#   after ⏎  box empty again  (it was submitted, not still sitting) + the tag on screen
set -uo pipefail

# Lifted verbatim from tmux-agents.sh pane_accepts(). Duplicated deliberately rather than sourced:
# tmux-agents.sh runs its dispatcher at the bottom, so sourcing it would execute a command.
pane_accepts() {
  tmux capture-pane -p -e -t "$1" 2>/dev/null | LC_ALL=C awk '
    { raw=$0; plain=$0; gsub(/\033\[[0-9;]*m/, "", plain)
      if (plain ~ /^[[:space:]]*$/) next
      n++; R[n]=raw; P[n]=plain }
    END {
      for (i=n; i>1; i--) if (P[i] ~ /^\342\235\257/) break
      if (i<=1 || i>=n) exit 1
      if (P[i-1] !~ /^(\342\224\200)+[[:space:]]*$/ || P[i+1] !~ /^(\342\224\200)+[[:space:]]*$/) exit 1
      # Dim text after the prompt is Claude Code own SUGGESTION, not anyone input, so it is
      # stripped before the emptiness test. Confirmed by the operator 2026-09-27: "no i have
      # nothing pasted in those panes ... a majority are suggestions from claude".
      #
      # This strip was briefly REMOVED earlier the same day on the opposite inference: the
      # suggestions read exactly like real instructions ("reseed the database and fix gate 2"),
      # so they were taken for unsent human drafts. That broke the watcher outright -- every lead
      # pane shows a suggestion, so every delivery was refused. The lesson is the one already in
      # AGENTS.md, turned on its author: plausible-looking evidence is not evidence. Ask whose
      # text it is; do not infer ownership from how it reads.
      # The dim span may END THE LINE with no reset code (seen 2026-10-14 in markets:security.1),
      # so the reset is optional; a dim span is still the only thing stripped.
      s=R[i]; gsub(/\033\[2m[^\033]*(\033\[(0|22)m)?/, "", s); gsub(/\033\[[0-9;]*m/, "", s)
      sub(/^\342\235\257/, "", s); gsub(/\302\240/, "", s); gsub(/[[:space:]]/, "", s)
      exit (s=="" ? 0 : 1) }'
}
pane_busy() { tmux capture-pane -p -t "$1" 2>/dev/null | grep -v '^[[:space:]]*$' | tail -4 | grep -q "esc to interrupt"; }

PANE="${1:?usage: operator-send.sh <pane> <file> [tag]}"
FILE="${2:?usage: operator-send.sh <pane> <file> [tag]}"
TAG="${3:-}"
[ -s "$FILE" ] || { echo "REFUSED: $FILE is missing or empty"; exit 2; }
# TARGET VALIDATION, and it is not paranoia. Measured 2026-09-26: tmux does NOT fail on an unknown
# target — `tmux display -p -t markets:no-such-window.1` returned %10 and exit 0, %10 being whatever
# pane happened to be ACTIVE at the time (markets:dev.1, the dev server). So a single typo in a pane
# name does not error; it silently redirects the message to the focused pane. The first version of
# this script was saved only by pane_accepts() refusing a shell prompt — luck, not design. Had the
# active pane been a Claude session with an empty composer, an operator ruling meant for one branch
# would have been typed into another agent, which is the cross-pane write T-SEC-09 exists to stop.
# So: resolve the target, then require the resolved pane to spell itself back the same way.
RESOLVED="$(tmux display -p -t "$PANE" '#{session_name}:#{window_name}.#{pane_index}' 2>/dev/null)"
if [ "$RESOLVED" != "$PANE" ]; then
  echo "REFUSED: '$PANE' does not name a pane — tmux resolved it to '${RESOLVED:-nothing}', which is the ACTIVE pane, not the one you asked for. Nothing sent."
  exit 2
fi

# STATE 1 — the box must be empty before we touch it. A dialog or an unsent human draft here means
# typing would corrupt someone's input, and the watcher refuses for the same reason.
pane_accepts "$PANE" || { echo "REFUSED $PANE: input box is not empty (permission dialog, or an unsent human draft). Nothing sent."; exit 3; }

# Trailing newlines are stripped: a paste ending in one leaves the composer in multi-line mode, and
# then Enter adds a line rather than submitting. This was defect 2.
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
printf '%s' "$(cat "$FILE")" > "$TMP"

tmux load-buffer -b opsend "$TMP" && tmux paste-buffer -d -b opsend -t "$PANE" || { echo "REFUSED $PANE: paste-buffer failed"; exit 4; }

# STATE 2 — wait for the paste to FINISH, not to START. Measured 2026-09-26, twice, on the payments
# lead: "the composer is no longer empty" fires on the FIRST characters to arrive, and a ~2KB
# paste-buffer into a Claude TUI keeps landing for seconds after that. Pressing Enter a second later
# submitted a fragment and stranded the tail mid-word ("quest to chore/security..."), which is the
# same truncation as the timer it was meant to replace — a new wrong signal, not a fixed one.
# So the condition is STABILITY: the rendered pane must stop changing. A paste still arriving
# redraws the pane, so the hash moves; when it holds still across consecutive samples, the paste is
# done. Non-emptiness is still required, or "stable" would also describe a paste that never landed.
STABLE_NEEDED="${STABLE_NEEDED:-4}"        # consecutive unchanged samples (x0.5s) before submitting
pane_hash() { tmux capture-pane -p -t "$1" 2>/dev/null | cksum; }
i=0; stable=0; prev=""; landed=0
while [ "$i" -lt 120 ]; do                  # 60s ceiling
  cur="$(pane_hash "$PANE")"
  if [ "$cur" = "$prev" ]; then stable=$((stable+1)); else stable=0; fi
  prev="$cur"
  if [ "$stable" -ge "$STABLE_NEEDED" ] && ! pane_accepts "$PANE"; then landed=1; break; fi
  sleep 0.5; i=$((i+1))
done
if [ "$landed" != 1 ]; then
  if pane_accepts "$PANE"; then
    echo "REFUSED $PANE: the paste never reached the input box. Nothing submitted."
  else
    echo "REFUSED $PANE: the input box never stopped changing after 60s — still receiving, or the pane is redrawing. NOT submitted, so the text is sitting in the composer: clear it with C-u before retrying."
  fi
  exit 5
fi
echo "  paste settled after $(echo "$i" | awk '{printf "%.1f", $1/2}')s ($i samples, ${STABLE_NEEDED} stable)"

tmux send-keys -t "$PANE" Enter

# STATE 3 — SUBMITTED, not still sitting in the composer. The signal is the composer EMPTYING, not
# the tag appearing in the transcript.
#
# The tag was the primary check until 2026-09-27 and it produced false NEGATIVES: a 1432-char
# message to markets:security.1 was reported UNCONFIRMED and had in fact arrived — the pane was
# already running `sed -n '59p;61p' scripts/merge-accepted.sh` from its contents. Claude Code
# re-renders and collapses a submitted message, so the literal tag need not survive in the
# scrollback, and the longer the message the likelier that is. "Delivery is more reliable than the
# confirmation" was the interim rule, and an exception every future reader has to remember is
# exactly what gets forgotten under pressure — a real message resent needlessly, or worse, a failed
# one assumed delivered.
#
# The composer has no such ambiguity and the session does not control it: if Enter submitted, the
# box is empty; if Enter only added a newline (the collapsed-paste case), the box still holds the
# text. Busy counts too — a session that started working obviously received it, and while busy the
# prompt line may not render at all. The tag is kept as extra confidence, reported, never required.
# A LONG PASTE NEEDS A SECOND ENTER, and this is why the sender kept reporting failure on messages
# that were fine. Claude Code collapses a large paste into a "[Pasted text #N +M lines]" chip and the
# composer is then in multi-line mode, so the first Enter inserts a newline instead of submitting.
# Measured 2026-09-27: two ~2KB messages to pos and security sat unsent until a second Enter, then
# both submitted immediately and both sessions began working. So one extra Enter is sent partway
# through the wait rather than declaring a failure the operator then has to fix by hand.
#
# Bounded at exactly one retry, deliberately. If two Enters do not submit it, something else is
# wrong and a third keystroke is guessing — which is how a human draft got clobbered earlier that
# same day.
SECOND_ENTER_AT="${SECOND_ENTER_AT:-6}"
i=0; retried=0
while [ "$i" -lt 25 ]; do
  sleep 1; i=$((i+1))
  if [ "$i" -ge "$SECOND_ENTER_AT" ] && [ "$retried" = 0 ] && ! pane_busy "$PANE" && ! pane_accepts "$PANE"; then
    retried=1
    echo "  still in the composer after ${i}s — sending one more Enter (collapsed-paste multi-line case)"
    tmux send-keys -t "$PANE" Enter
  fi
  if pane_busy "$PANE" || pane_accepts "$PANE"; then
    if [ -n "$TAG" ] && tmux capture-pane -p -t "$PANE" -S -400 | grep -qF "$TAG"; then
      echo "DELIVERED $PANE — submitted and confirmed after ${i}s (composer emptied; tag seen)"
    else
      echo "DELIVERED $PANE — submitted and confirmed after ${i}s (composer emptied; tag not in view, which is normal once the session re-renders)"
    fi
    exit 0
  fi
done
echo "UNCONFIRMED $PANE: the composer never emptied in 25s, so the message was NOT submitted — it is still sitting in the input box. Clear it with C-u before retrying; do not just resend."
exit 1
