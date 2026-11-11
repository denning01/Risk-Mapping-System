#!/usr/bin/env bash
# Warm-start brief — what was in flight when a pane's session ended.
#
#   npm run agents -- --brief <role>     print it (and write it for the next --start)
#   bash scripts/agent-brief.sh <role>   same
#
# WHY THIS EXISTS, and why it is not `claude --resume`.
#
# AGENTS.md makes the charter and the handoff log the memory that survives a terminated session; the
# transcript is explicitly NOT. That is a deliberate choice and this does not reverse it — panes are
# still launched fresh. What it fixes is a different problem, measured on 2026-09-20: after a
# power-off, "fresh" was indistinguishable from "green". A restarted pos lead would have had to
# rediscover, by reading 93KB of handoff log, that its own ROUND 8 was appended and never audited.
#
# So the brief is GENERATED, never authored: every line below comes from git or from the handoff log,
# both of which outlive the tmux server. It can be regenerated at any time, it holds no state of its
# own, and the prompt that carries it labels it as a claim to verify rather than as fact. Deleting
# every .brief file loses nothing.
#
# It is capped deliberately. A brief long enough to need skimming is one a lead will skim.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEV_ROOT="${AGENTS_DEV_ROOT:-$(cd "$ROOT/.." && pwd)}"
AUDIT_DIR="$DEV_ROOT/rms-audit"
STATE_DIR="$AUDIT_DIR/.state"
MEM_DIR="$STATE_DIR/memory"
mkdir -p "$STATE_DIR" "$MEM_DIR"

ROLE="${1:-}"
[ -n "$ROLE" ] || { echo "usage: $(basename "$0") <operator|model|exposure>" >&2; exit 1; }

# role -> worktree, mirroring the TIERS table in tmux-agents.sh. Kept as a lookup rather than sourced
# so this script stays runnable on its own, which is what makes it testable without touching tmux.
case "$ROLE" in
  operator)     LEAD_DIR="$DEV_ROOT/rms";           AUDIT_WT="-" ;;
  model)        LEAD_DIR="$DEV_ROOT/rms-model";     AUDIT_WT="$DEV_ROOT/rms-model-audit" ;;
  exposure)     LEAD_DIR="$DEV_ROOT/rms-exposure";  AUDIT_WT="$DEV_ROOT/rms-exposure-audit" ;;
  *) echo "unknown role '$ROLE'" >&2; exit 1 ;;
esac

LOG="$AUDIT_DIR/$ROLE.md"

# ---- handoff log: where the round protocol actually stands -------------------
# Line numbers are quoted so the lead can jump straight there instead of re-reading the whole file.
last_of() { grep -n -E "$1" "$LOG" 2>/dev/null | tail -1; }
LAST_LEAD="$(last_of '^ROUND [0-9]+ · LEAD')"
LAST_AUD="$(last_of '^ROUND [0-9]+ · AUDITOR')"
LAST_VERDICT="$(last_of '^VERDICT:')"

round_no() { echo "$1" | sed -n 's/.*ROUND \([0-9][0-9]*\).*/\1/p'; }
line_no()  { echo "$1" | cut -d: -f1; }

LEAD_N="$(round_no "$LAST_LEAD")"; AUD_N="$(round_no "$LAST_AUD")"

# The one fact that decides what a restarted lead does first.
if [ "$ROLE" = "operator" ]; then
  # The operator runs no ROUND protocol of its own: its log is a record of what it routed, ruled and
  # merged. Reporting "no rounds yet" here would be true of the file and false about the session.
  PROTOCOL="You are the operator. There is no ROUND protocol for this session; $LOG is your own record of what you routed, ruled and merged. Run npm run agents and npm run audit:findings before anything else — they describe the grid now, this brief describes when it stopped."
elif [ -z "${LEAD_N:-}" ]; then
  PROTOCOL="No ROUND entries in $ROLE.md yet. Nothing was in flight."
elif [ -z "${AUD_N:-}" ] || [ "${LEAD_N:-0}" -gt "${AUD_N:-0}" ]; then
  PROTOCOL="ROUND $LEAD_N (LEAD) is appended at $LOG:$(line_no "$LAST_LEAD") and has NO auditor round. It was awaiting audit when the session ended."
elif [ "${LEAD_N:-0}" -eq "${AUD_N:-0}" ]; then
  PROTOCOL="ROUND $AUD_N is complete on both sides; the last verdict is at $LOG:$(line_no "$LAST_VERDICT") — $(echo "$LAST_VERDICT" | sed 's/^[0-9]*://')."
else
  PROTOCOL="The auditor is ahead of the lead (lead $LEAD_N, auditor $AUD_N) — read $LOG before acting; that should not happen."
fi

# Strip ANSI. audit-findings colours its output for a terminal, and this text becomes a command-line
# argument to `claude` — raw escape codes there are noise the model has to parse around.
# The operator owes no findings of its own, and asking for "operator" would print nothing at all —
# a blank section reading as "all clear" when four branches might owe work. It gets the whole board.
FINDINGS_ARG="$ROLE"; [ "$ROLE" = "operator" ] && FINDINGS_ARG=""
OPEN_FINDINGS="$(bash "$ROOT/scripts/audit-findings.sh" $FINDINGS_ARG 2>/dev/null \
  | LC_ALL=C sed -e 's/'$'\033''\[[0-9;]*m//g' -e '/^[[:space:]]*$/d')"
[ -n "$OPEN_FINDINGS" ] || OPEN_FINDINGS="(audit-findings reported nothing)"

# ---- git: what is on disk that no commit records yet -------------------------
git_state() { # $1=dir $2=label
  local d="$1"
  [ -d "$d" ] || { echo "$2: worktree missing at $d"; return 0; }
  local head branch dirty ahead behind
  head="$(git -C "$d" rev-parse --short HEAD 2>/dev/null)"
  branch="$(git -C "$d" branch --show-current 2>/dev/null)"; [ -n "$branch" ] || branch="detached"
  dirty="$(git -C "$d" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  ahead="$(git -C "$d" rev-list --count data..HEAD 2>/dev/null || echo ?)"
  behind="$(git -C "$d" rev-list --count HEAD..data 2>/dev/null || echo ?)"
  echo "$2: $branch @ $head — $ahead ahead of data, $behind behind, $dirty uncommitted file(s)"
  # Uncommitted work is the part most likely to be a surprise after a crash: it is invisible in the
  # log, invisible to the auditor's detached checkout, and it is what "where I left off" usually means.
  if [ "$dirty" -gt 0 ]; then
    git -C "$d" status --porcelain 2>/dev/null | sed 's/^/    /'
  fi
}

# ---- pane memory: the only record of work since the last round ---------------
mem_tail() { # $1=slug $2=label
  local f="$MEM_DIR/$1.log"
  [ -s "$f" ] || { echo "$2 pane memory: none captured."; return 0; }
  local when; when="$(date -r "$f" '+%Y-%m-%d %H:%M' 2>/dev/null || echo unknown)"
  echo "$2 pane memory: $MEM_DIR/$1.log, last changed $when. Its final lines were:"
  # Blank rows dropped first: a pane is `clear`ed at launch, so capture-pane returns the full pane
  # height and a raw tail can be entirely empty while the real last words sit higher up. Same
  # correction the stop-path footer detection needed.
  grep -v '^[[:space:]]*$' "$f" | tail -12 | sed 's/^/    | /'
}

# Written with TOP-LEVEL heredocs, redirected straight to the file. The obvious form —
# BRIEF="$(cat <<EOF … EOF)" — parses on bash 5 and fails on macOS's bash 3.2, which loses track of
# an apostrophe inside a heredoc nested in a command substitution ("unexpected EOF while looking for
# matching `''". The launcher runs under /usr/bin/env bash, so the 3.2 case is the real one.
GENERATED_AT="$(date '+%Y-%m-%d %H:%M %Z')"
cat > "$STATE_DIR/$ROLE.brief" <<EOF
Generated $GENERATED_AT from git and the handoff log.
Protocol state: $PROTOCOL

$([ "$ROLE" = operator ] && echo "Open findings across every branch (npm run audit:findings):" || echo "Open findings you still owe (npm run audit:findings $ROLE):")
$(echo "$OPEN_FINDINGS" | sed 's/^/  /')

$(git_state "$LEAD_DIR" "Your worktree")

$(mem_tail "$ROLE-lead" "Your")

$([ "$ROLE" = operator ] && echo "Your own log is $LOG. Anything in this block that git, the grid or the logs do not" || echo "Read $LOG from the line above, not from the top. Anything in this block that the log or git does not")
confirm is wrong: say so rather than working around it.
EOF

if [ "$AUDIT_WT" != "-" ]; then
cat > "$STATE_DIR/$ROLE-audit.brief" <<EOF
Generated $GENERATED_AT from git and the handoff log.
Protocol state: $PROTOCOL

$(git_state "$AUDIT_WT" "Your checkout")

$(mem_tail "$ROLE-audit" "Your")

If the latest lead round is unaudited, that round is your task. If it is already audited, say so and
stop rather than re-auditing it.
EOF
fi

echo "=== $ROLE · $([ "$ROLE" = operator ] && echo OPERATOR || echo LEAD) brief ($STATE_DIR/$ROLE.brief) ==="
cat "$STATE_DIR/$ROLE.brief"
if [ "$AUDIT_WT" != "-" ]; then
  echo ""
  echo "=== $ROLE · AUDITOR brief ($STATE_DIR/$ROLE-audit.brief) ==="
  cat "$STATE_DIR/$ROLE-audit.brief"
fi
