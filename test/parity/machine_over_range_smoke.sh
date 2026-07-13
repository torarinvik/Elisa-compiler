#!/usr/bin/env bash
# docs/122 §5.2 / docs/123: range alternatives in a `machine over` arm header
# (`State, 48..=57:`), stage1 FEATURE parity with stage0 (docs/125 step 13 / Phase-1
# step 1). A `..<` / `..=` range lowers to a `lo <= input and input <(=) hi` bounds test
# OR'd with any equality alternatives; a range counts as an open-domain input (so a
# range-only state still needs a final `_`). Mirrors stage0's machineInputRange lowering.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "machine-over range smoke FAIL: $1" >&2; exit 1; }

# 1. LEGAL: an inclusive range arm plus a final `_` wildcard parses and resolves clean.
out=$(printf 'def s(lx: mutable Lx&) -> i64:\n    n: i64 = 0\n    machine over lx.cur() while not lx.done():\n        state Run\n        start Run\n        Run, 48..=57:\n            -> Run\n        Run, _:\n            -> Run\n    return n\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "inclusive range header rejected: $out"

# 2. LEGAL: a range alternated with an equality literal (`48..=57 | 95`).
out=$(printf 'def s(lx: mutable Lx&) -> i64:\n    n: i64 = 0\n    machine over lx.cur() while not lx.done():\n        state Run\n        start Run\n        Run, 48..=57 | 95:\n            -> Run\n        Run, _:\n            -> Run\n    return n\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "range | literal alternation rejected: $out"

# 3. ILLEGAL: a range is open-domain, so a range-only state without `_` is non-total.
out=$(printf 'def s(lx: mutable Lx&) -> i64:\n    n: i64 = 0\n    machine over lx.cur() while not lx.done():\n        state Run\n        start Run\n        Run, 48..=57:\n            -> Run\n    return n\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "range-only state without wildcard NOT refused: $out"

echo "machine-over range smoke OK: range + range|literal legal; range is open-domain (needs final _)"
