#!/usr/bin/env bash
# The function-invariant check (`invariant P` reading a GHOST local), which had NO coverage.
#
# It is judged only when the invariant READS A GHOST local — stage0 proves real-local
# invariants by flow reasoning this tier does not model, so restricting to ghost reads keeps
# stage1 a strict subset of stage0's warnings. That gate is now also a fast path: a function
# with no `invariant` contract, or none reading a ghost, returns before building any of the
# five lists the proof attempt needs. Without a test, nothing would notice if the early exit
# swallowed the diagnostic entirely.
#
# Uses `parse_report` (frontend only) rather than a diagnostics FIXTURE on purpose: the
# backend declines `ghost`/`invariant` in bare mode, so a fixture would show up as a
# REJECT-GAP in driver_acceptance_smoke's bare sweep and break its ratchet. This is a
# stage1-supplemental diagnostic — stage0 accepts both programs below.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
RPT="$REPO_ROOT/build/parse_report"
[ -x "$RPT" ] || { echo "function_invariant SKIP: no parse_report"; exit 0; }

fail() { echo "function_invariant FAILED: $1" >&2; exit 1; }

# Reads a ghost local: MUST be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    ghost total: i64 = n * 2\n    invariant total >= 0\n    return n\n' | "$RPT")
echo "$out" | grep -q "invariant could not be proven statically" \
  || fail "ghost-reading invariant not flagged: $out"

# The SAME invariant over a real local: must stay silent (stage0 proves these).
out=$(printf 'def f(n: i64) -> i64:\n    total: i64 = n * 2\n    invariant total >= 0\n    return n\n' | "$RPT")
echo "$out" | grep -q "invariant could not be proven statically" \
  && fail "non-ghost invariant flagged — stage0 proves these, so this is a false positive: $out"

# No `invariant` at all: the cheapest early exit, and it must not change anything.
out=$(printf 'def f(n: i64) -> i64:\n    ghost total: i64 = n * 2\n    return n\n' | "$RPT")
echo "$out" | grep -q "invariant could not be proven statically" \
  && fail "invariant reported for a function that has none: $out"

echo "function_invariant OK: ghost-reading invariant flagged, real-local and absent forms silent"
