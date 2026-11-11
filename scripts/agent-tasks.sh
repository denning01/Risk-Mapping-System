#!/usr/bin/env bash
# The cross-branch backlog. One file per role in ../rms-audit/tasks/, never one shared file —
# five leads editing one backlog is the roster conflict this repo already had.
#
#   npm run tasks                 every role
#   npm run tasks -- <role>       one role
#   npm run tasks -- --check      exit 1 if anything is unfinished (the report gate uses this)
#   npm run tasks -- --blocked    only what is waiting, and on what
#
# A task line is:  <id> | <state> | <round-or-"-"> | <title>
# States: TODO  WIP  AUDIT  DONE  BLOCKED:<what>
#
# DONE means BOTH: its round carries an AUDITOR ACCEPT, and the branch is merged to main. This
# script verifies the first half itself and refuses to take DONE on trust — a state field a lead
# can type is a claim, and this repo's whole standard is that a claim needs a check that fails.
set -uo pipefail

DEV_ROOT="${AGENTS_DEV_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
TASK_DIR="$DEV_ROOT/rms-audit/tasks"
LOG_DIR="$DEV_ROOT/rms-audit"
ROLES="model exposure"

ONLY=""; CHECK=0; BLOCKED_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK=1 ;;
    --blocked) BLOCKED_ONLY=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) ONLY="$1" ;;
  esac
  shift
done

# Does <role>'s <round> carry an AUDITOR ACCEPT? This is what makes DONE checkable rather than typed.
round_accepted() {  # $1=role $2=round-number
  local f="$LOG_DIR/$1.md" n="$2"
  [ -f "$f" ] && [ -n "$n" ] && [ "$n" != "-" ] || return 1
  awk -v n="$n" '
    $0 ~ "^ROUND "n" · AUDITOR " { inblock=1; next }
    /^ROUND [0-9]+ · (LEAD|AUDITOR) / { inblock=0 }
    inblock && /^VERDICT:[[:space:]]*ACCEPT/ { found=1 }
    END { exit(found ? 0 : 1) }' "$f"
}

unfinished=0; total=0
for role in $ROLES; do
  [ -n "$ONLY" ] && [ "$ONLY" != "$role" ] && continue
  f="$TASK_DIR/$role.md"
  [ -f "$f" ] || { printf '  %-14s (no task file)\n' "$role"; continue; }
  printf '\n\033[1m%s\033[0m\n' "$role"
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    case "$line" in *'|'*) ;; *) continue ;; esac
    id="$(printf '%s' "$line" | cut -d'|' -f1 | tr -d ' ')"
    state="$(printf '%s' "$line" | cut -d'|' -f2 | tr -d ' ')"
    round="$(printf '%s' "$line" | cut -d'|' -f3 | tr -d ' ' | sed 's/^ROUND//')"
    title="$(printf '%s' "$line" | cut -d'|' -f4- | sed 's/^ *//')"
    total=$((total + 1))
    note=""; colour="0"
    case "$state" in
      DONE)
        if round_accepted "$role" "$round"; then colour="32"
        else colour="31"; note="  <- DONE but ROUND ${round:--} has no AUDITOR ACCEPT"; unfinished=$((unfinished + 1)); fi ;;
      AUDIT)
        colour="33"; unfinished=$((unfinished + 1))
        round_accepted "$role" "$round" && note="  <- ACCEPTed: mark DONE and merge (npm run merge:accepted $role)" ;;
      BLOCKED:*) colour="35"; unfinished=$((unfinished + 1)) ;;
      *) unfinished=$((unfinished + 1)) ;;
    esac
    [ "$BLOCKED_ONLY" = "1" ] && case "$state" in BLOCKED:*) ;; *) continue ;; esac
    printf '  \033[%sm%-10s %-22s\033[0m %s%s\n' "$colour" "$id" "$state" "$title" "$note"
  done < "$f"
done

printf '\n  %s task(s), %s unfinished\n' "$total" "$unfinished"
if [ "$CHECK" = "1" ] && [ "$unfinished" -gt 0 ]; then
  echo "  (--check) work is outstanding" >&2
  exit 1
fi
exit 0
