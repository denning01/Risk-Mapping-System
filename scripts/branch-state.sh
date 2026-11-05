#!/usr/bin/env bash
# What another branch actually contains — from git, never from a screen.
#
#   npm run branch:state                 every branch
#   npm run branch:state -- <role>       one
#   npm run branch:state -- <role> <pattern>   ...and whether its TRACKED code contains <pattern>
#
# Why this exists, precisely: on 2026-09-19 this branch told the operator that payments was "building
# writeIndexOnly against a column its branch does not have". It was false. `writeIndexOnly` existed
# in exactly one place — a throwaway probe file that payments had created and deleted in the same
# command two rounds earlier, to prove one of its own guards fired. What produced the claim was a
# `tmux capture-pane` of the payments pane: terminal scrollback showing a deleted file's contents.
#
# Scrollback is not repository state. It holds probes, deleted code, quoted text from other agents,
# hypotheticals a lead typed out and rejected, and output from commands that were rolled back. A
# claim about what a branch contains must come from the repository.
#
# So this uses `git grep`, which searches TRACKED CONTENT ONLY — the exact thing that would have
# returned zero for writeIndexOnly and stopped a false alarm that cost a full round.
set -uo pipefail

DEV_ROOT="${AGENTS_DEV_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
ROLES="model exposure"

wt_for() {
  case "$1" in
    model) echo "$DEV_ROOT/rms-model" ;; exposure) echo "$DEV_ROOT/rms-exposure" ;; *) echo "" ;;
  esac
}

ONLY="${1:-}"; PATTERN="${2:-}"
[ -n "$ONLY" ] && ROLES="$ONLY"

for role in $ROLES; do
  wt="$(wt_for "$role")"
  [ -n "$wt" ] && [ -d "$wt" ] || { printf '%-14s (no worktree)\n' "$role"; continue; }
  branch="$(git -C "$wt" branch --show-current 2>/dev/null || echo '(detached)')"
  head="$(git -C "$wt" rev-parse --short HEAD 2>/dev/null)"
  dirty="$(git -C "$wt" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  ahead="$(git -C "$wt" rev-list --count data..HEAD 2>/dev/null || echo '?')"
  behind="$(git -C "$wt" rev-list --count HEAD..data 2>/dev/null || echo '?')"
  printf '%-14s %-20s %s  ahead_of_main=%-3s behind=%-3s uncommitted=%s\n' \
    "$role" "$branch" "$head" "$ahead" "$behind" "$dirty"
  if [ -n "$PATTERN" ]; then
    # TRACKED content only. An untracked scratch file is not what the branch "contains", and that
    # distinction is the whole point of this script.
    n="$(git -C "$wt" grep -l -- "$PATTERN" 2>/dev/null | wc -l | tr -d ' ')"
    if [ "$n" = "0" ]; then
      printf '               tracked files containing %s: \033[32mNONE\033[0m\n' "$PATTERN"
    else
      printf '               tracked files containing %s: %s\n' "$PATTERN" "$n"
      git -C "$wt" grep -l -- "$PATTERN" 2>/dev/null | sed 's/^/                 /'
    fi
    # Untracked matches are reported SEPARATELY and never counted as what the branch contains.
    u="$(git -C "$wt" ls-files --others --exclude-standard 2>/dev/null | xargs grep -l -- "$PATTERN" 2>/dev/null | wc -l | tr -d ' ')"
    [ "$u" != "0" ] && printf '               \033[33m%s UNTRACKED file(s) also match — scratch/probe files, NOT branch content\033[0m\n' "$u"
  fi
done
