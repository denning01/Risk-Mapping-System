#!/usr/bin/env bash
# Open auditor findings — the ones a lead still owes work on.
#
#   npm run audit:findings           every role
#   npm run audit:findings <role>    one role
#   npm run audit:findings --check   exit 1 if any finding is open (used by the pre-commit hook)
#
# An auditor finding is not a note to the operator. It is a task. This parses the handoff logs for
# findings tagged MUST or SHOULD and reports the ones with no matching CLOSED/DECLINED line, so
# "the auditor mentioned it and nobody did it" is a state the system can see rather than something
# discovered by re-reading prose months later.
#
# Format (see rms-audit/README.md):
#   FINDINGS:
#     F2.1 INFO   — confirmation only, NO change recommended. A recommendation is never INFO.
#     F2.2 MUST   — defect or gap; the auditor does not ACCEPT while it is open
#     F2.3 SHOULD — suggestion; IMPLEMENTED, exactly like a MUST. The auditor may ACCEPT the round
#                   with it open, but the lead starts NO next round until it is done and confirmed.
#   REMEDIATION · ROUND 2 · <ts> · <session id>
#     F2.2 CLOSED — what was done, with evidence
#
# WHAT COUNTS AS CLOSED, set by the human 2026-10-02 (AGENTS.md § Only the auditor closes a round):
#   * a `CLOSED` line, AND
#   * an auditor `VERDICT: ACCEPT` written AFTER it, in an AUDITOR block for the SAME round (2026-11-07). A lead's CLOSED is a claim; the
#     auditor's later ACCEPT is what confirms it. A CLOSED with no ACCEPT after it is still OPEN.
#   * NOT `DECLINED`. Declining is no longer an option — every recommendation is implemented.
#   * NOT a CLOSED that says it was "routed" or "routing". Handing a finding to someone else is how
#     three findings sat undone across four branches until this was found on 2026-10-02.
set -uo pipefail
# AGENTS_DEV_ROOT exists so this is testable against a fixture tree instead of the live logs. An
# earlier attempt to test it passed that variable and silently read the REAL logs, so the test
# proved nothing in either direction (CLAUDE.md rule 12).
AUDIT_DIR="${AGENTS_DEV_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}/rms-audit"
ROLES="model exposure"
CHECK=0; ONLY=""
for a in "$@"; do case "$a" in --check) CHECK=1 ;; --*) ;; *) ONLY="$a" ;; esac; done

total_open=0
for role in $ROLES; do
  [ -n "$ONLY" ] && [ "$ONLY" != "$role" ] && continue
  f="$AUDIT_DIR/$role.md"; [ -f "$f" ] || continue

  # Declared actionable findings, and closures. An ID may be referenced in prose, so anchor on the
  # tag that follows it rather than the bare ID.
  # A finding is a LINE that STARTS with its id — `  F3.4  MUST  <what>` — not the string "F3.4 MUST"
  # appearing anywhere. On 2026-09-19 this hook refused a commit because the auditor's round PROSE
  # described its own test fixture ("a log containing `F9.1 MUST ... / F9.2 MUST ...`"). The document
  # describing findings is not a finding, exactly as the charter describing a secret is not a secret.
  declared="$(grep -oE '^[[:space:]]*F[0-9]+\.[0-9]+[[:space:]]+(MUST|SHOULD)\b' "$f" 2>/dev/null | awk '{print $1}' | sort -u)"
  # A CLOSED Fn.k is confirmed only by a `VERDICT: ACCEPT` that (a) comes AFTER it and (b) sits in an
  # AUDITOR block for the SAME round n (a `ROUND n · AUDITOR ...` header naming round n). Until 2026-11-07 any later ACCEPT
  # anywhere in the log confirmed it: exposure's ROUND 5 re-audit ACCEPT (10:01) "confirmed" ROUND 8's
  # F8.5-F8.7 CLOSED lines, which no auditor had re-audited, and the tracker printed "exposure clear"
  # while ROUND 8 stood REJECTED. VERDICT lines are written at column 0 by the auditor; a lead quoting
  # one in prose indents it, so anchoring at ^ keeps a quotation from confirming anything. A LEAD or
  # REMEDIATION header ends the auditor block, so an ACCEPT can never be attributed across one.
  closed="$(awk '
    # The block covers every "ROUND n" its header names: a combined re-audit is headed
    # "ROUND 1 · AUDITOR ... (re-audit of REMEDIATION · ROUND 1 + ROUND 2 ...)" and confirms both.
    /^ROUND [0-9]+ · AUDITOR/ {
      cur = " "; t = $0
      while (match(t, /ROUND [0-9]+/)) { cur = cur substr(t, RSTART + 6, RLENGTH - 6) " "; t = substr(t, RSTART + RLENGTH) }
      next
    }
    /^ROUND [0-9]+ · LEAD/ || /^REMEDIATION/ { cur = ""; next }
    /^VERDICT:[[:space:]]+ACCEPT([^A-Za-z]|$)/ {
      if (cur != "") { k = split(cur, rr, " "); for (j = 1; j <= k; j++) last[rr[j]] = NR }
      next
    }
    /^[[:space:]]*F[0-9]+\.[0-9]+[[:space:]]+CLOSED([^A-Za-z]|$)/ {
      if (tolower($0) ~ /rout(ed|ing)/) next
      id = $1; r = id; sub(/^F/, "", r); sub(/\..*/, "", r)
      n++; cid[n] = id; crd[n] = r; cln[n] = NR
    }
    END { for (i = 1; i <= n; i++) if ((crd[i] in last) && last[crd[i]] > cln[i]) print cid[i] }
  ' "$f" 2>/dev/null | sort -u)"
  open="$(comm -23 <(echo "$declared") <(echo "$closed") 2>/dev/null | grep -E '^F' || true)"

  legacy=0
  [ -z "$declared" ] && grep -qE '^FINDINGS:' "$f" && legacy=1

  if [ -n "$open" ]; then
    n=$(echo "$open" | wc -l | tr -d ' '); total_open=$((total_open+n))
    printf '\033[31m%-14s %s open finding(s)\033[0m\n' "$role" "$n"
    for id in $open; do
      tag="$(grep -oE "\b$id[[:space:]]+(MUST|SHOULD)\b" "$f" | head -1 | awk '{print $2}')"
      # ONE line, the line the id is declared on. An earlier version used `grep -A2 | tr '\n' ' '`
      # and a greedy `.*(MUST|SHOULD)` — which skipped past the NEXT finding's tag and printed the
      # wrong finding's text next to this id. A tracker that mislabels which finding is open is
      # worse than no tracker.
      txt="$(grep -m1 -E "\b$id[[:space:]]+(MUST|SHOULD)\b" "$f" | sed -E "s/^.*$id[[:space:]]+(MUST|SHOULD)[[:space:]]*[—-]*[[:space:]]*//" | cut -c1-92)"
      printf '  \033[31m%-8s %-7s\033[0m %s…\n' "$id" "$tag" "$txt"
    done
  elif [ "$legacy" = "1" ]; then
    printf '%-14s no tagged findings (legacy prose rounds — untracked)\n' "$role"
  else
    printf '\033[32m%-14s clear\033[0m\n' "$role"
  fi
done

if [ "$total_open" -gt 0 ]; then
  echo ""
  echo "$total_open finding(s) still owed. Closing them IS the lead's current task — SHOULD exactly like" >&2
  echo "MUST — and no next round starts until they are confirmed. Append a" >&2
  echo "REMEDIATION block naming each ID as CLOSED with evidence, then wait for the auditor's ACCEPT." >&2
  echo "A CLOSED is confirmed only by an auditor ACCEPT written after it. DECLINED and routing do not close." >&2
  [ "$CHECK" = "1" ] && exit 1
fi
exit 0
