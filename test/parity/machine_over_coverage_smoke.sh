#!/usr/bin/env bash
# docs/123 §5 per-state coverage, stage1-OWNED (docs/125 step 13). A `machine over` state
# must handle every input: an open-domain (char/int) state needs a final unguarded `_`
# arm, an irrefutable arm makes any later arm for that state unreachable, and a state with
# no arms is an error. All three are parser-decidable (no types), 0-FP, and REFUSED BY
# STAGE1 (P >= 1). Mirrors stage0's parser/machine.go per-state coverage loop.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "machine-over coverage smoke FAIL: $1" >&2; exit 1; }

# 1. LEGAL: an open-domain arm (`48`) plus a final `_` wildcard is total.
out=$(printf 'def s(lx: mutable Lx&) -> i64:\n    n: i64 = 0\n    machine over lx.cur() while not lx.done():\n        state Run\n        start Run\n        Run, 48:\n            -> Run\n        Run, _:\n            -> Run\n    return n\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "legal open+wildcard machine flagged: $out"

# 2. ILLEGAL: an open-domain state (`48`) with no `_` wildcard cannot be exhaustive.
out=$(printf 'def s(lx: mutable Lx&) -> i64:\n    n: i64 = 0\n    machine over lx.cur() while not lx.done():\n        state Run\n        start Run\n        Run, 48:\n            -> Run\n    return n\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "open-domain state without wildcard NOT refused: $out"

# 3. ILLEGAL: an arm after an irrefutable (`_`) arm is unreachable.
out=$(printf 'def s(lx: mutable Lx&) -> i64:\n    n: i64 = 0\n    machine over lx.cur() while not lx.done():\n        state Run\n        start Run\n        Run, _:\n            -> Run\n        Run, 48:\n            -> Run\n    return n\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "arm after irrefutable arm NOT refused as unreachable: $out"

# 4. ILLEGAL: the same literal input (`48`) handled by two arms of one state.
out=$(printf 'def s(lx: mutable Lx&) -> i64:\n    n: i64 = 0\n    machine over lx.cur() while not lx.done():\n        state Run\n        start Run\n        Run, 48:\n            -> Run\n        Run, 48:\n            -> Run\n        Run, _:\n            -> Run\n    return n\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "duplicate literal input NOT refused: $out"

echo "machine-over coverage smoke OK: open+wildcard legal; open-no-wildcard + unreachable-after-wildcard + duplicate-input refused by stage1"
