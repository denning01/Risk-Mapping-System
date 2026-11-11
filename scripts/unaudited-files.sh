#!/usr/bin/env bash
# Which files a branch changed that an existing ACCEPT does NOT cover.
#
# Extracted from merge-accepted.sh gate 2 on 2026-09-27 to close F18.1. It was inline, and a gate
# that decides what reaches `main` had no automated test anywhere — the one property this repo has
# built a guard for four times over (rls-role-guard, scan-secrets-patterns, rls-models-single-source,
# docs-match-config) and had not built for the gate itself. Extracted rather than re-implemented in
# the test, because a test that reimplements the pipeline proves agreement between a method and
# itself. __tests__/merge-gate-filter.test.ts drives THIS file against fixture repositories.
#
#   unaudited-files.sh <worktree> <audited-sha> <branch-or-ref> [mainline-ref]
#
# Prints one path per line; empty output means the ACCEPT still covers the tip. Exit is 0 either
# way — emptiness is the answer, not the status, so a caller must test the output and not $?.
#
# THE TWO FILTERS, both load-bearing, measured 2026-09-27 across four live branches:
#
#   --not <mainline>   Drops commits the mainline already has. Merging main in and back out adds
#                      nothing to main, so those commits are not this branch's to be audited for.
#                      Without it all four branches blocked, including the one that legitimately
#                      rode — proven on dashboard-ui's ec885f2 and 77d3465, real commits that touch
#                      scripts/ and are genuinely on main.
#
#   grep -Ev '\.md$'   Exempts documentation, by KIND. This is what lets a docs-only branch ride at
#                      all; removing it makes docs count and causes OVER-refusal, never an unsafe
#                      merge. (T-SEC-12's spec stated the opposite; measured, it is backwards.)
#                      It was `\.md$|^docs/` until the operator spotted that `^docs/` exempts by
#                      LOCATION — a .ts under docs/ would have been waved through. `^docs/.*\.md$`
#                      would close that, but is wholly subsumed by `\.md$`, so the alternative was
#                      deleted rather than narrowed. Same disease as the deny-list this replaced:
#                      an exemption that ignores what the file actually is.
#
# Everything that is not documentation is reviewable, including this file and verify-all.sh, so the
# gate cannot exempt an edit to itself. That is the only safe direction for an allow-list.
set -uo pipefail

wt="${1:?worktree required}"
sha="${2:?audited sha required}"
branch="${3:?branch or ref required}"
mainline="${4:-main}"
log="${5:-}"      # optional: the role's handoff log
round="${6:-}"    # optional: the round number being merged

# REMEDIATION COMMITS ARE PART OF THEIR ROUND. Operator spec 2026-09-28c.
#
# The deadlock the tip-merge fix did NOT resolve, and I was wrong to think it had. Closing a
# finding needs no go-ahead — it FINISHES the round already authorised — so the remediation is part
# of that round. But findings are closed by writing a check (DMAIC Control; CLAUDE.md rule 4: a
# convention with no failing check is not enforcement), a check is a test file, and a test file is
# never documentation. So every remediation that adds a test made its own round unmergeable, and
# four branches plus two of dashboard-ui's rounds were caught by it.
#
# The gate and the protocol held different models of what a round IS: the protocol says a round
# includes its remediation, the gate said a round is one sha. This reconciles them.
#
# TWO CONDITIONS, both required. The second is the narrowing, and it is mandatory rather than
# advisory because the first alone is trivially satisfiable by writing an id into any message:
#   1. the commit message names a finding id belonging to THIS round (F<round>.<n>) — already
#      enforced at write time by .githooks/commit-msg, so the gate reads what the hook guarantees;
#   2. the commit's sha appears in the handoff log — i.e. the round NAMED its remediation commits,
#      so a reader can check the bundle rather than take it on trust.
#
# WHAT THIS DOES NOT DO, labelled here rather than papered over: it does NOT stop a lead bundling
# unrelated work into a commit that names a finding id and is listed in the log. That is CONVENTION,
# not enforcement. Making it enforcement would need the gate to diff the commit against the finding,
# which it cannot do. Condition 2 exists so the bundle is at least VISIBLE to whoever reads the log.
#
# WHY A REMEDIATION COMMIT MAY RIDE — the exact claim, because someone will reason from this in six
# months. It is SOLICITED AND DESTINED FOR REVIEW by the same auditor in the same round. It is NOT
# already reviewed, and this gate must not be built as though it were.
#
# The first version of this spec said "the auditor demanded it, so the work is reviewed". feat/
# dashboard-ui pushed back and was right: the auditor demanded the REQUIREMENT, not the
# IMPLEMENTATION. It verified that a finding needed closing; it has not seen the code that closed
# it. Measured against this repo's handoff logs, the order is always LEAD -> AUDITOR -> REMEDIATION,
# so at the moment round N merges its remediation is unreviewed and is reviewed in round N+1.
#
# That difference is real and material — solicited-and-destined-for-review is not the same as
# unaudited feature work, which is neither — and it is still not the same as reviewed. Precedent
# that the distinction bites: the 2026-09-19 ruling cites a remediation containing a false positive
# caught only by running it, and ROUND 18's own remediation (db7157e) shipped a mutation harness
# that reported three false negatives until it was re-run. So this is a TRADE against a permanent
# extra audit pass per finding-bearing round, not a free consequence of the protocol.
#
# SCOPE, corrected: this bites only on findings closed WITH A CHECK. A remediation that corrects a
# claim or a method touches docs only and already rode under the .md rule — dashboard-ui's ROUND 1
# remediation (70756cd) is exactly that. Still the common case, because Control asks for a check,
# but narrower than "every remediation".
#
# AND NAMING THE BUNDLE DOES NOT MAKE IT SAFE. Condition 2 makes a bundle VISIBLE to whoever reads
# the log; an auditor still has to look at it. dashboard-ui wrote that in its own addendum while
# volunteering the naming, and it is the standard encoded here — visibility, not assurance.
covered=""
if [ -n "$log" ] && [ -n "$round" ] && [ -f "$log" ]; then
  for c in $(git -C "$wt" rev-list "$sha".."$branch" --not "$mainline" 2>/dev/null); do
    msg="$(git -C "$wt" log -1 --format='%B' "$c" 2>/dev/null)"
    printf '%s' "$msg" | grep -qE "F${round}\\.[0-9]+" || continue      # (1) names a finding of this round
    short="$(git -C "$wt" rev-parse --short "$c" 2>/dev/null)"
    grep -qF "$short" "$log" 2>/dev/null || continue                    # (2) the round named it
    covered=" $covered $c "
  done
fi

# FILTER THE COMMIT LIST, do NOT hand the exclusions back to rev-list.
#
# The first version did `rev-list A..B --not main $covered`, which is WRONG in a way that defeats
# the whole gate: `--not <sha>` excludes that commit AND ALL ITS ANCESTORS. A legitimate remediation
# commit sitting at the tip therefore swallowed every unaudited commit beneath it. Measured on this
# branch at the moment it was found: 3 commits in range, 0 after the exclusion — including
# 9dffe15, which names no finding id and had no business riding.
#
# Found because the operator asked whether the new exemption covered its own commit. It did — for
# entirely the wrong reason. "It rides" and "it rides because it qualifies" are different answers
# and only one of them is the gate working.
#
# So: enumerate, then drop exactly the covered shas, one commit at a time. An exclusion must remove
# ONE commit, never a reachable set.
for c in $(git -C "$wt" rev-list "$sha".."$branch" --not "$mainline" 2>/dev/null); do
  case "$covered" in *" $c "*) continue ;; esac
  git -C "$wt" show --name-only --format= "$c" 2>/dev/null
done \
  | sort -u \
  | grep -Ev '\.md$' \
  | grep -v '^$' || true
