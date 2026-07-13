#!/usr/bin/env bash
# docs/125 §4 R3 (the `when` restricted arm grammar), stage1-OWNED (docs/125 step 13): a
# `when` arm column atom is restricted to the forms whose disjointness is DECIDABLE at
# parse time — a literal, a range, a payload-less enum tag, `_`, or an or-group of those.
# A binding, a payload destructure, a struct pattern, or a computed guard is REFUSED BY
# STAGE1 (P >= 1) rather than deferred to stage0. Mirrors stage0's parser/when.go
# classifyWhenAtom + the guard refusal in parseWhenRow.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "when arm-law smoke FAIL: $1" >&2; exit 1; }

# 1. LEGAL: literals, an or-group, a range, a two-column row, and the `_` default row.
out=$(printf 'def kind(n: i64, s: sview) -> i64:\n    when n, s:\n        0 | 1, "a": 10\n        2..<9, "b": 20\n        _: 0\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "legal literal/or/range/default when flagged: $out"

# 2. ILLEGAL: a binding arm (`v`) — bindings need `match`.
out=$(printf 'def kind(n: i64) -> i64:\n    when n:\n        v: 10\n        _: 0\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "binding arm NOT refused: $out"

# 3. ILLEGAL: a computed guard (`0 if n > 0:`) — a guard needs `match`.
out=$(printf 'def kind(n: i64) -> i64:\n    when n:\n        0 if n > 0: 10\n        _: 0\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "guard arm NOT refused: $out"

# 4. ILLEGAL: a payload destructure (`Tok.Int(x)`) — destructuring needs `match`.
out=$(printf 'def kind(t: Tok) -> i64:\n    when t:\n        Tok.Int(x): 10\n        _: 0\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "payload destructure NOT refused: $out"

# --- docs/125 §4 R1 (disjointness), stage1-OWNED ---
# `when` DECLARES its arms order-independent; stage1 proves it. Overlapping non-default
# rows and a duplicate `_` default are REFUSED (P >= 1); provably-disjoint tables pass.
# Soundness note: a Lit's integer reading is used only against a Range (a range implies a
# numeric-scrutinee column), and two Lits overlap only on byte-equal raw text — so string
# columns like `"a"` vs `"b"` are correctly disjoint (regression: they once collapsed to 0).

# 5. LEGAL: two-column rows disjoint by their SECOND column ("a" vs "b").
out=$(printf 'def k(n: i64, s: sview) -> i64:\n    when n, s:\n        0, "a": 10\n        0, "b": 20\n        _: 0\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "disjoint 2-column rows flagged: $out"

# 6. LEGAL: distinct string arms stay disjoint (no false collapse to integer 0).
out=$(printf 'def k(s: sview) -> i64:\n    when s:\n        "a": 10\n        "b": 20\n        _: 0\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "distinct string arms flagged as overlap: $out"

# 7. ILLEGAL: an integer value appears in two arms (`1` in `0 | 1` and `1`).
out=$(printf 'def k(n: i64) -> i64:\n    when n:\n        0 | 1: 10\n        1: 20\n        _: 0\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "overlapping integer arms NOT refused: $out"

# 8. ILLEGAL: two ranges that share `3` (`0..<5` and `3..<9`).
out=$(printf 'def k(n: i64) -> i64:\n    when n:\n        0..<5: 10\n        3..<9: 20\n        _: 0\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "overlapping ranges NOT refused: $out"

# 9. ILLEGAL: a range and a literal inside it (`0..<5` and `3`).
out=$(printf 'def k(n: i64) -> i64:\n    when n:\n        0..<5: 10\n        3: 20\n        _: 0\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "range-covers-literal overlap NOT refused: $out"

# 10. ILLEGAL: a duplicate `_` default row.
out=$(printf 'def k(n: i64) -> i64:\n    when n:\n        0: 10\n        _: 1\n        _: 2\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "duplicate default row NOT refused: $out"

# 11. ILLEGAL: same tag two ways (`Tk.A` and `.A`) overlap on the final segment.
out=$(printf 'def k(t: Tk) -> i64:\n    when t:\n        Tk.A: 10\n        .A: 20\n        _: 0\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "duplicate tag arm NOT refused: $out"

echo "when arm-law smoke OK: R3 grammar (binding/guard/destructure) + R1 disjointness (overlap/dup-default) refused by stage1"
