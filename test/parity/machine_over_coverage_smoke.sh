#!/usr/bin/env bash
# docs/123 §5 per-state coverage, stage1-OWNED (docs/125 step 13). A `machine over` state
# must handle every input: an open-domain (char/int/float/bool/string) state needs a final unguarded `_`
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

# 5. LEGAL: a payload refinement is retained by the stage1 parser, and the same refined
# payload field can be shared by multiple states.
out=$(printf 'def s(lx: mutable Lx&) -> i64:\n    machine over lx.cur():\n        state Run(depth: usize where depth > 0)\n        state Done(depth: usize where depth > 0)\n        start Run(1)\n        Run(depth), _:\n            -> Done(depth)\n        Done(depth), _:\n            return depth\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "refined machine payload was not accepted: $out"

# 6. ILLEGAL: different predicates on a same-named payload field are not interchangeable.
out=$(printf 'def s(lx: mutable Lx&) -> i64:\n    machine over lx.cur():\n        state Run(depth: usize where depth > 0)\n        state Done(depth: usize where depth > 1)\n        start Run(1)\n        Run(depth), _:\n            -> Done(depth)\n        Done(depth), _:\n            return depth\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "incompatible refined payload fields were accepted: $out"

# 7. ILLEGAL: float, negative, boolean, and string literal inputs use the same open-domain
# rule as stage0, including literals wrapped in unary-minus AST nodes.
out=$(printf 'def s(lx: mutable Lx&) -> i64:\n    machine over lx.cur() while not lx.done():\n        state Run\n        start Run\n        Run, true:\n            -> Run\n        Run, "done":\n            -> Run\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "bool/string open-domain state without wildcard NOT refused: $out"

out=$(printf 'def s(lx: mutable Lx&) -> i64:\n    machine over lx.cur() while not lx.done():\n        state Run\n        start Run\n        Run, 1.0:\n            -> Run\n        Run, -1:\n            -> Run\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "float/negative open-domain state without wildcard NOT refused: $out"

# 7b. LEGAL: a float payload pattern is an equality payload, not a boolean predicate.
out=$(printf 'def s(lx: mutable Lx&) -> i64:\n    machine over lx.cur() while not lx.done():\n        state Run(value: f64)\n        start Run(1.0)\n        Run(1.0), _:\n            return 1\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "float payload equality was not accepted: $out"

# 8. ILLEGAL: parentheses and floating-point literal forms cannot hide an exact duplicate.
out=$(printf 'def s(lx: mutable Lx&) -> i64:\n    machine over lx.cur() while not lx.done():\n        state Run\n        start Run\n        Run, 1.0:\n            -> Run\n        Run, (1.0):\n            -> Run\n        Run, _:\n            -> Run\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "duplicate parenthesized float input NOT refused: $out"

# 9. ILLEGAL: qualified and shorthand enum-tag spellings cannot repeat an exact input.
for tag in TokenKind.A .A; do
  out=$(printf 'def s(lx: mutable Lx&) -> i64:\n    machine over lx.cur() while not lx.done():\n        state Run\n        start Run\n        Run, %s:\n            -> Run\n        Run, %s:\n            -> Run\n        Run, _:\n            -> Run\n    return 0\n' "$tag" "$tag" | "$RPT")
  echo "$out" | grep -q "^P 0$" && fail "duplicate enum tag %s NOT refused: %s" "$tag" "$out"
done

echo "machine-over coverage smoke OK: open+wildcard legal; open-no-wildcard + unreachable-after-wildcard + duplicate literal/enum-tag input + float/negative/bool/string open-domain refused; refined payload retained and checked"
