#!/usr/bin/env bash
# The region-owner-leak check (`region NAME` declared and never consumed), which had NO
# coverage — no diagnostics fixture, no smoke.
#
# `rol_check_function` now returns before allocating anything unless the body actually
# declares an owner (`rol_has_owner`). That fast path matters because the scan it skips pushes
# EVERY identifier of every condition, scrutinee, return, assignment and initializer into a
# `refs` list, all of it thrown away for the overwhelming majority of functions, which declare
# no owner at all. Without a test, an early exit that swallowed the diagnostic would pass
# every other check in the gate.
#
# parse_report (frontend only) rather than a diagnostics FIXTURE, for the same reason as
# function_invariant_smoke: a fixture is compiled by driver_acceptance_smoke in BARE mode too,
# where the backend's handling of these constructs is a separate matter from the diagnostic.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
RPT="$REPO_ROOT/build/parse_report"
[ -x "$RPT" ] || { echo "region_owner_leak SKIP: no parse_report"; exit 0; }

fail() { echo "region_owner_leak FAILED: $1" >&2; exit 1; }

# An owner nothing ever mentions: MUST be flagged.
out=$(printf 'def f() -> i64:\n    region scratch\n    return 1\n' | "$RPT")
echo "$out" | grep -q 'region owner "scratch" must be consumed' \
  || fail "unreferenced region owner not flagged: $out"

# The same owner, referenced: must stay silent.
out=$(printf 'def g(n: i64) -> i64:\n    region scratch\n    total: i64 = n + scratch\n    return total\n' | "$RPT")
echo "$out" | grep -q 'region owner' \
  && fail "referenced region owner flagged — false positive: $out"

# A function with no owner at all — the early exit. Must stay silent, and must not disturb
# the other diagnostics the same body produces.
out=$(printf 'def h(n: i64) -> i64:\n    total: i64 = n * 2\n    return total\n' | "$RPT")
echo "$out" | grep -q 'region owner' \
  && fail "region-owner diagnostic reported for a function with no region: $out"

echo "region_owner_leak OK: unreferenced owner flagged, referenced and owner-free forms silent"
