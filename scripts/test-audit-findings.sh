#!/usr/bin/env bash
# Fixture test for scripts/audit-findings.sh: a CLOSED is confirmed only by a LATER auditor ACCEPT for
# the SAME round. Pins the 2026-11-07 false-clear (exposure ROUND 5's ACCEPT "confirmed" ROUND 8's
# CLOSED lines). Runs against a temp AGENTS_DEV_ROOT, never the live logs.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/rms-audit"
fail=0
run() { AGENTS_DEV_ROOT="$tmp" bash "$here/audit-findings.sh" exposure 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g'; }
expect() { # $1 name, $2 expected open ids (space-separated, sorted), log on stdin
  cat > "$tmp/rms-audit/exposure.md"
  got="$(run | grep -oE '^  F[0-9]+\.[0-9]+' | tr -d ' ' | sort | tr '\n' ' ' | sed 's/ $//')"
  if [ "$got" = "$2" ]; then echo "ok   $1"; else echo "FAIL $1: expected [$2] got [$got]"; fail=1; fi
}

expect "other round's later ACCEPT does not confirm" "F8.5" <<'L'
ROUND 8 · AUDITOR · t
  F8.5  MUST  x
VERDICT: REJECT — x
REMEDIATION · ROUND 8 · t
  F8.5  CLOSED  fixed
ROUND 5 · AUDITOR · t  (re-audit)
VERDICT: ACCEPT — R5 fine
L

expect "same round's later ACCEPT confirms" "" <<'L'
ROUND 8 · AUDITOR · t
  F8.5  MUST  x
VERDICT: REJECT — x
REMEDIATION · ROUND 8 · t
  F8.5  CLOSED  fixed
ROUND 8 · AUDITOR · t  (re-audit)
VERDICT: ACCEPT — closed
L

expect "same-round ACCEPT BEFORE the CLOSED does not confirm" "F8.6" <<'L'
ROUND 8 · AUDITOR · t
  F8.6  SHOULD  x
VERDICT: ACCEPT — with F8.6 open
REMEDIATION · ROUND 8 · t
  F8.6  CLOSED  fixed
L

expect "combined re-audit header confirms both rounds" "" <<'L'
ROUND 2 · AUDITOR · t
  F2.2  SHOULD  x
VERDICT: ACCEPT — with F2.2 open
REMEDIATION · ROUND 1 + ROUND 2 · t
  F2.2  CLOSED  fixed
ROUND 1 · AUDITOR · t  (re-audit of REMEDIATION · ROUND 1 + ROUND 2)
VERDICT: ACCEPT — closed
L

expect "indented (quoted) ACCEPT and routed CLOSED do not confirm" "F3.1 F3.2" <<'L'
ROUND 3 · AUDITOR · t
  F3.1  MUST  x
  F3.2  SHOULD  y
VERDICT: REJECT — x
REMEDIATION · ROUND 3 · t
  F3.1  CLOSED  fixed
  F3.2  CLOSED  routed to model
ROUND 3 · AUDITOR · t
  VERDICT: ACCEPT — quoted, not real
L

[ "$fail" = 0 ] && echo "audit-findings: all fixture cases pass" || { echo "audit-findings: FAILED" >&2; exit 1; }
