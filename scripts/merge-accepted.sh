#!/usr/bin/env bash
# Merge a role's branch into main — but only once its auditor has actually accepted the work.
#
#   npm run merge:accepted -- <role>            do it
#   npm run merge:accepted -- <role> --dry-run  say what it would refuse, change nothing
#
# Five gates, every one of which has a real incident behind it in this repo:
#   1. the LAST round in the handoff log is a LEAD round with a matching AUDITOR ACCEPT
#      — "done when the auditor agrees" (AGENTS.md), not when the lead says so
#   2. the round's COMMIT: sha is an ancestor of the branch tip, so what was audited is what merges
#      — an auditor ACCEPT names a commit; merging a later, unaudited commit under that ACCEPT is
#        the whole loophole
#   3. no open auditor findings for that role (npm run audit:findings --check)
#   4. the lead worktree is clean — uncommitted work is not what was audited
#   5. verify:all passes in the lead worktree, pasted, not summarised
#
# It never force-pushes, never rebases, and leaves main untouched on any refusal.
set -uo pipefail

DEV_ROOT="${AGENTS_DEV_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
LOG_DIR="$DEV_ROOT/rms-audit"
MAIN="$DEV_ROOT/rms"   # Person A integration checkout, on branch data

role="${1:-}"; shift 2>/dev/null || true
DRY=0; for a in "$@"; do [ "$a" = "--dry-run" ] && DRY=1; done
case "$role" in
  model)        branch=a/model;            wt="$DEV_ROOT/rms-model" ;;
  exposure)     branch=a/exposure;         wt="$DEV_ROOT/rms-exposure" ;;
  *) echo "usage: npm run merge:accepted -- <model|exposure> [--dry-run]" >&2; exit 1 ;;
esac

log="$LOG_DIR/$role.md"
refuse() { echo "REFUSED: $*" >&2; exit 1; }
[ -f "$log" ] || refuse "no handoff log at $log"

# ---- gate 1: the last LEAD round must have an AUDITOR ACCEPT --------------------------------
last_lead="$(grep -E '^ROUND [0-9]+ · LEAD ' "$log" | tail -n 1)"
[ -n "$last_lead" ] || refuse "$role has no LEAD rounds"
n="$(printf '%s' "$last_lead" | sed -E 's/^ROUND ([0-9]+) .*/\1/')"
# Gates 1 and 2 read the log through ONE parser, scripts/round-verdict.sh: the auditor's LAST verdict,
# the lead's last COMMIT: before it, and the sha that verdict names. Both used to take the FIRST
# match, so a withdrawn ACCEPT still passed gate 1 and gate 2 bound the round's first commit rather
# than the one audited (F22.12, ROUND 22). Pinned in __tests__/round-verdict.test.ts.
read -r verdict sha named <<<"$(bash "$(dirname "$0")/round-verdict.sh" "$log" "$n")"
[ "$verdict" = "ACCEPT" ] || refuse "ROUND $n has verdict '$( [ "$verdict" = "-" ] && echo "none yet" || echo "$verdict")' — the auditor's LAST verdict is not an ACCEPT"
echo "  gate 1 OK — ROUND $n · AUDITOR · VERDICT ACCEPT (the last verdict in the round)"

# ---- T-SEC-45: resolve the branch ONCE ---------------------------------------------------------
# Every gate below and the merge itself use this sha, never the branch NAME. Before 2026-10-18 the
# gates read "$branch" and the merge re-read it after gate 5. verify:all takes ~10 minutes, and a
# lead committing in that window had its new, unaudited commit merged under the old ACCEPT: pos
# ROUND 54, audited at 2436bca, merged e334799 (T-POS-29). It was caught before the push. Now the
# approved sha is what verify:all must run on (HEAD of the lead worktree), and if the branch moves
# while the gates run, the gate refuses rather than merging either snapshot.
tip_full="$(git -C "$wt" rev-parse --verify -q "$branch^{commit}")" || refuse "no branch $branch in $wt"

# ---- gate 2: merge exactly what was audited --------------------------------------------------
[ "$sha" != "-" ] || sha=""
[ -n "$sha" ] || refuse "ROUND $n names no COMMIT:"
git -C "$wt" cat-file -e "$sha^{commit}" 2>/dev/null || refuse "ROUND $n names commit $sha, which does not exist in $wt"
# If the verdict states which commit it audited, it must be the one the lead submitted. Disagreement
# means the gate and the auditor are talking about different code; refuse rather than pick one.
if [ "$named" != "-" ]; then
  git -C "$wt" cat-file -e "$named^{commit}" 2>/dev/null \
    || refuse "the verdict names commit $named, which does not exist in $wt"
  [ "$(git -C "$wt" rev-parse "$named^{commit}")" = "$(git -C "$wt" rev-parse "$sha^{commit}")" ] \
    || refuse "the verdict says it audited $named, but the lead's last COMMIT: before it is $sha"
fi
git -C "$wt" merge-base --is-ancestor "$sha" "$tip_full" 2>/dev/null \
  || refuse "the audited commit $sha is not an ancestor of $branch — the branch has moved somewhere else"
ahead="$(git -C "$wt" rev-list --count "$sha".."$tip_full")"
if [ "$ahead" -eq 0 ]; then
  echo "  gate 2 OK — branch tip is the audited commit $sha"
else
  # An ACCEPT names one commit, and that is still the rule. AGENTS.md (§ An auditor finding is a
  # task) carves out ONE case: commits that add nothing to main but documentation ride under the
  # existing ACCEPT. Until 2026-09-27 this gate counted commits and nothing else — `git diff`
  # appeared ZERO times in the whole script — so it could not tell a docs merge from real work and
  # refused both, stalling four lanes. A rule was published and never built; the mechanism is what
  # runs.
  #
  # The filter chain moved to scripts/unaudited-files.sh on 2026-09-27 (F18.1). It was inline here,
  # and a gate deciding what reaches `main` had no automated test — the exact property this repo has
  # built a guard for four times elsewhere. It is a separate file so
  # __tests__/merge-gate-filter.test.ts can drive the REAL chain against fixture repositories
  # instead of reimplementing it; the reasoning for each filter lives in that file's header.
  # $log and $n let the chain treat this round's OWN remediation commits as part of the round —
  # operator spec 2026-09-28c. Conditions and the trade are documented in unaudited-files.sh.
  own="$(bash "$(dirname "$0")/unaudited-files.sh" "$wt" "$sha" "$tip_full" data "$log" "$n")"
  if [ -z "$own" ]; then
    echo "  gate 2 OK — $ahead commit(s) after the audited $sha, but they add nothing to data"
    echo "              except documentation, so they ride under ROUND $n's ACCEPT. Covered:"
    git -C "$wt" log --oneline --no-decorate "$sha".."$tip_full" | sed 's/^/                /'
  else
    echo "  NOTE: $ahead commit(s) on $branch after the audited $sha change reviewable files:"
    echo "$own" | sed 's/^/          /'
    refuse "refusing to merge under ROUND $n's ACCEPT — the files above are not documentation and were never audited. Append a round for them."
  fi
fi

# ---- gate 3: no open findings ----------------------------------------------------------------
(cd "$wt" && bash scripts/audit-findings.sh --check "$role" >/dev/null 2>&1) \
  || refuse "$role has open auditor findings — close them first (npm run audit:findings)"
echo "  gate 3 OK — no open findings"

# ---- gate 4: clean tree ----------------------------------------------------------------------
dirty="$(git -C "$wt" status --porcelain | wc -l | tr -d ' ')"
[ "$dirty" = "0" ] || refuse "$wt has $dirty uncommitted change(s) — that is not what was audited"
echo "  gate 4 OK — working tree clean"

# ---- gate 5: the gate itself -----------------------------------------------------------------
if [ "$DRY" = "1" ]; then echo "  gate 5 skipped (--dry-run); would run verify:all in $wt"; echo "DRY RUN: all checkable gates pass; nothing merged."; exit 0; fi
# verify:all tests the WORKTREE, so the worktree must be the approved sha, before and after.
[ "$(git -C "$wt" rev-parse HEAD)" = "$tip_full" ] \
  || refuse "$wt is not checked out at $branch's tip ${tip_full:0:7}, so verify:all would test something else"
echo "  gate 5 — running verify:all in $wt at ${tip_full:0:7} (this is the slow one)"
(cd "$wt" && npm run verify:all) || refuse "verify:all failed in $wt"
# T-SEC-45: did anything move while verify:all ran? Then neither snapshot is safe to merge:
# the new tip was never gated, and the old tip may not be what verify:all saw.
now="$(git -C "$wt" rev-parse --verify -q "$branch^{commit}")"
[ "$now" = "$tip_full" ] \
  || refuse "$branch moved during gate 5 (${tip_full:0:7} -> ${now:0:7}); nothing merged. Re-run once the lead has stopped committing."
[ "$(git -C "$wt" rev-parse HEAD)" = "$tip_full" ] && [ "$(git -C "$wt" status --porcelain | wc -l | tr -d ' ')" = "0" ] \
  || refuse "$wt changed during gate 5 (HEAD or working tree); nothing merged"
echo "  gate 5 OK — verify:all passed"

# ---- merge -----------------------------------------------------------------------------------
[ "$(git -C "$MAIN" status --porcelain | wc -l | tr -d ' ')" = "0" ] || refuse "$MAIN is dirty"
# Merge the BRANCH TIP, not the audited sha. Fixed 2026-09-27; found by feat/dashboard-ui.
#
# This merged "$sha" — the commit the ACCEPT named — which left every commit after it behind on the
# branch. main never caught up, so `ahead` never returned to 0, and the next round inherited the
# same debt plus its own. Four branches were 24-52 commits ahead of main when this was found; the
# refusal recurred every round and never cleared, because merging could not clear it.
#
# Merging the tip is not a loosening: gate 2 above has already decided the tip is mergeable, either
# because it IS the audited sha (ahead == 0) or because everything after it adds nothing to main but
# documentation. Merging less than what was approved is what created the debt.
#
# This also dissolves most of the gate2/gate3 deadlock (an ACCEPT requires ahead == 0, closing a
# finding requires a commit, which makes ahead != 0). With the tip merged, ahead resets to 0 and the
# next round starts clean instead of carrying every previous round's remediation forever. Operator
# ruling 2026-09-27: gate 2 stays strict, this is the fix instead — a remediation is written under
# finding pressure, which is when review matters most.
tip="${tip_full:0:7}"
git -C "$MAIN" merge --no-ff --no-edit -m "Merge $branch @ $tip (auditor ACCEPT of ROUND $n at $sha, verify:all green)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" "$tip_full" \
  || refuse "the merge itself failed — resolve in $MAIN"
echo "MERGED: $branch @ $tip -> data ($(git -C "$MAIN" rev-parse --short HEAD))"
[ "$tip" = "$sha" ] || echo "  (ROUND $n audited $sha; commits $sha..$tip rode under it on the zero-diff rule)"
echo "Now mark the task DONE in $LOG_DIR/tasks/$role.md and record the round number."
