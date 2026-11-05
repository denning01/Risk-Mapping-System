#!/usr/bin/env bash
# What a round's handoff log actually SAYS, for the merge gate: the auditor's FINAL verdict, the
# commit the lead last submitted before it, and the commit that verdict names, if it names one.
#
#   round-verdict.sh <handoff-log> <round>
#   -> one line: <verdict> <lead-sha> <named-sha>     (any field "-" when absent)
#
# Extracted from merge-accepted.sh gates 1 and 2 on 2026-10-03 to close F22.12 (ROUND 22, MUST).
# Both gates used an awk that EXITED ON THE FIRST MATCH:
#   gate 1 took the FIRST `VERDICT:` in the round's AUDITOR blocks. This log is append-only, so an
#     auditor withdraws an ACCEPT by appending a REJECT after it — and the gate kept reading the
#     ACCEPT. Measured: ROUND 22's 00:50 ACCEPT was superseded by a 07:55 REJECT, and the gate still
#     said "gate 1 OK".
#   gate 2 took the FIRST `COMMIT:` in the round's LEAD blocks (9a7a68a), while the watcher and the
#     auditor both use the LAST (097f803, then 8780175). The gate was judging an ACCEPT given at one
#     commit as though it had been given at another.
# A gate that reads a different line from the auditor's is not checking the auditor's decision.
#
# THE RULES, each pinned in __tests__/round-verdict.test.ts:
#   * verdict   = the LAST `VERDICT:` line written at column 0 inside a `ROUND <n> · AUDITOR` block.
#                 Indented quotations in a lead's prose never count; nor does a line without the
#                 colon (ROUND 22's first verdict was missing it, and the gate correctly ignored it).
#   * lead-sha  = the last `COMMIT:` in a LEAD-side block of round <n> — `ROUND <n> · LEAD ...` or
#                 `REMEDIATION · ROUND <n> ...` — written BEFORE that final verdict. That is what the
#                 auditor was looking at when it decided. A COMMIT: written after the verdict is not
#                 audited by it.
#   * named-sha = the `(at <sha>` the final verdict line states, when it states one. The gate
#                 cross-checks it against lead-sha and refuses on disagreement.
set -uo pipefail
log="${1:?usage: round-verdict.sh <log> <round>}"; n="${2:?usage: round-verdict.sh <log> <round>}"
[ -f "$log" ] || { echo "- - -"; exit 0; }
# ANY column-0 heading — upper-case words, then " · " — ENDS the current block. Only the three
# recognised shapes START one. F22.12 (ROUND 22 RE-VERDICT 2): the first version recognised only
# those three as boundaries, so any other heading INHERITED the previous block's state, and the logs
# already use others (CORRECTION · ROUND 11 · LEAD, MERGE ·, ADDENDUM · ROUND 6, REMEDIATION ·
# F12.7, OPERATOR DIRECTIVE ·). Measured by the auditor against this script: a lead heading
# "CORRECTION · ROUND 7 · LEAD" quoting the template line "VERDICT:   ACCEPT" after an auditor's
# REJECT made this print ACCEPT — lead prose deciding the auditor's verdict, no forged header needed.
# The heading pattern is deliberately strict (upper-case words only before the first " · "), so a
# prose line that merely CONTAINS " · " — the real log has "SUPERSEDED-VERDICT (was ACCEPT, ...
# ROUND 22 · LEAD block)" — is not mistaken for one. If a body line ever does look like a heading,
# the block ends early and the gate reads LESS, which fails closed: an older lead sha, or none.
# THE POSITIVE BOUNDARY (F22.12, ROUND 22 RE-VERDICT 3). Recognising headings — first three shapes,
# then "any upper-case heading" — is a BLOCKLIST, and the auditor stepped round it four ways: a
# lower-case heading, a "## " heading, "CORRECTION (ROUND 7, LEAD):", and no heading at all. Each let
# lead text placed after an AUDITOR block decide the verdict. So the AUDITOR block now ends at its OWN
# rule line ("────", which every AUDITOR block in all five role logs ends with, checked mechanically),
# and a VERDICT: only COUNTS once that rule closes the block. A verdict whose block is cut short by a
# heading, or by the end of the file, is discarded: that fails closed. Nothing written after the
# auditor's rule is read as the auditor's, whatever its heading looks like or whether it has one.
awk -v n="$n" '
  /^(─)+[[:space:]]*$/ {
    if (aud && pending) { verdict = pv; audited = pa; named = pn }
    aud = 0; pending = 0
    next
  }
  /^[A-Z][A-Z0-9 ._-]* · / {
    pending = 0
    lead = ($0 ~ ("^ROUND " n " · LEAD ")) || ($0 ~ ("^REMEDIATION · ROUND " n " "))
    aud  = ($0 ~ ("^ROUND " n " · AUDITOR "))
    next
  }
  lead && /^COMMIT:/ {
    c = $0; sub(/^COMMIT:[[:space:]]*/, "", c); split(c, a, /[[:space:]]+/); last_lead = a[1]
  }
  aud && /^VERDICT:/ {
    v = $0; sub(/^VERDICT:[[:space:]]*/, "", v); split(v, b, /[[:space:]]+/)
    pv = b[1]; pa = last_lead; pn = ""; pending = 1
    if (match(v, /\(at [0-9a-f]+/)) pn = substr(v, RSTART + 4, RLENGTH - 4)
  }
  END {
    printf "%s %s %s\n", (verdict == "" ? "-" : verdict), (audited == "" ? "-" : audited), (named == "" ? "-" : named)
  }' "$log"
