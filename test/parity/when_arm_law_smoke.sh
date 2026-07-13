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

echo "when arm-law smoke OK: literal/or/range/default legal; binding + guard + destructure refused by stage1"
