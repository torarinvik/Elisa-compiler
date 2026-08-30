#!/usr/bin/env bash
# docs/125 §6b — postfix statement guard on MULTI-PLACE `<-` assignment:
# `a, b <- call() if COND` is do-or-skip (parses P 0, resolves D 0), including the
# lmut thread-claim form `parser, x <- parser.method() if COND`. The `=` declare
# form stays unconditional (a conditionally-declared binding would be unusable).
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "multi-place guard smoke FAIL: $1" >&2; exit 1; }

# 1. Pure value form: both places written iff the guard holds.
out=$(printf 'def two(x: i64) -> (p: i64, q: i64):\n    return x + 1, x + 2\ndef t1() -> void:\n    a: mutable i64 = 0\n    b: mutable i64 = 0\n    a, b <- two(10) if a == 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "value form had parse errors: $out"
echo "$out" | grep -q "^D 0$" || fail "value form had diagnostics: $out"

# 2. Thread-claim discard form (the parser idiom): `parser, _ <- call() if COND`.
out=$(printf 'struct P:\n    n: mutable i64\ndef step(p: lmut P) -> i64:\n    p.n <- p.n + 1\n    return p.n\ndef t2(flag: bool) -> void:\n    p: mutable P = P{n: 0}\n    p, _ <- p.step() if flag\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "thread-claim form had parse errors: $out"
echo "$out" | grep -q "^D 0$" || fail "thread-claim form had diagnostics: $out"

# 3. Runtime semantics via stage0 -emit test: skipped guard leaves both places untouched.
tmp="$(mktemp -t mpguard).elisa"
printf 'def two(x: i64) -> (p: i64, q: i64):\n    return x + 1, x + 2\n\n@test\ndef guard_semantics() -> void:\n    can Abort.Panic:\n        a: mutable i64 = 0\n        b: mutable i64 = 0\n        a, b <- two(10) if a == 0\n        assert(a == 11 and b == 12)\n        a, b <- two(100) if a == 0\n        assert(a == 11 and b == 12)\n' > "$tmp"
"$ELISACORE_BIN" -emit test "$tmp" >/dev/null 2>&1 || fail "runtime semantics test failed"
rm -f "$tmp"

echo "multi-place guard smoke OK: value + thread-claim forms parse P0 D0, do-or-skip semantics verified"
