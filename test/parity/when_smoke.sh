#!/usr/bin/env bash
# docs/125 §4 — `when` decision tables parse (P 0) and desugar to a resolvable Match:
# multi-column string×bool tables, integer ranges, or-groups within a column, the `_`
# default row, expression form, and indented block bodies all resolve; and `when`
# stays a legal identifier (the construct is contextual, gated on the next token).
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "when smoke FAIL: $1" >&2; exit 1; }

# 1. The flagship multi-column table (string × bool columns, an or-group column, a `_`
#    default row) parses with zero parse errors and resolves cleanly.
out=$(printf 'def literal_fits(value: i64, negated: bool, type_name: sview) -> bool:\n    return when type_name, negated:\n        "u8",  false -> value <= 255\n        "u16", false -> value <= 65535\n        "u8" | "u16", true -> false\n        _ -> true\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "multi-column table had parse errors: $out"
echo "$out" | grep -q "^D 0$" || fail "multi-column table had diagnostics: $out"

# 2. Integer ranges + `_` default, expression form bound to a local.
out=$(printf 'def classify(n: i64) -> i64:\n    x: i64 = when n:\n        0 -> 100\n        1..<10 -> 200\n        10..=99 -> 300\n        _ -> 400\n    return x\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "range table had parse errors: $out"
echo "$out" | grep -q "^D 0$" || fail "range table had diagnostics: $out"

# 3. Statement form with indented block arm bodies (bindings/values resolve inside).
out=$(printf 'def hit(n: i64) -> i64:\n    return n\ndef stmt_form(n: i64) -> i64:\n    total: mutable i64 = 0\n    when n:\n        0 ->\n            total <- hit(0)\n        _ ->\n            total <- hit(n)\n    return total\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "statement form had parse errors: $out"
echo "$out" | grep -q "^D 0$" || fail "statement form had diagnostics: $out"

# 4. when remains a legal identifier (contextual gate): a parameter/local named `when`
#    parses and resolves (no parse error, no undefined-name finding).
out=$(printf 'def use_when(when: i64) -> i64:\n    return when + 1\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "when-as-identifier had parse errors: $out"
echo "$out" | grep -q "^D 0$" || fail "when-as-identifier had diagnostics: $out"

echo "when smoke OK: multi-column/range/or-group/default/expr/block-body tables parse P0 D0; when stays an identifier"
