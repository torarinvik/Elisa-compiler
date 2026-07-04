#!/usr/bin/env bash
# Behavioral smoke for the per-scope, per-namespace DuplicateDecl check. It must
# FIRE on a genuine redefinition (identical-signature function, redeclared type)
# and STAY SILENT on the legal repeats stage0 permits: function overloads
# (different signature), a struct and a function sharing a name (separate
# namespaces), a method implemented for two types across impls, a name declared
# in different `static if` branches, and reopened modules. 0 FP across the
# frontend + stdlib (every file compiles on stage0).
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }
RPT="$REPO_ROOT/build/parse_report"
mkdir -p "$REPO_ROOT/build"
"$ELISACORE_BIN" -emit obj -O2 -permissive -o "$REPO_ROOT/build/parse_report.o" "$REPO_ROOT/test/breadth/parse_report.elisa" >/dev/null 2>&1
clang -O2 "$REPO_ROOT/build/parse_report.o" -o "$RPT" 2>/dev/null
fail() { echo "duplicate-decl smoke FAIL: $1" >&2; exit 1; }
# Both wordings: `duplicate declaration` (functions) and `duplicate type` (struct/enum).
dups() { "$RPT" | grep -cE "duplicate declaration|duplicate type"; }

# 1. identical-signature function redefinition MUST be flagged.
n=$(printf 'def f(a: i64) -> i64:\n    return a\ndef f(b: i64) -> i64:\n    return b\n' | dups)
[ "$n" -eq 1 ] || fail "identical-sig function dup not flagged (got $n)"

# 2. function OVERLOAD (different signature) must NOT be flagged.
n=$(printf 'def f(a: i64) -> i64:\n    return a\ndef f(a: f64) -> i64:\n    return 0\n' | dups)
[ "$n" -eq 0 ] || fail "overload wrongly flagged (got $n)"
n=$(printf 'def f() -> i64:\n    return 0\ndef f(a: i64) -> i64:\n    return a\n' | dups)
[ "$n" -eq 0 ] || fail "arity overload wrongly flagged (got $n)"

# 3. redeclared TYPE MUST be flagged; struct+function sharing a name must NOT.
n=$(printf 'struct P:\n    x: i64\nstruct P:\n    y: i64\n' | dups)
[ "$n" -eq 1 ] || fail "duplicate type not flagged (got $n)"
n=$(printf 'struct P:\n    x: i64\ndef P() -> i64:\n    return 1\n' | dups)
[ "$n" -eq 0 ] || fail "struct+function same name wrongly flagged (got $n)"

# 4. a method implemented for two types across impls must NOT collide.
n=$(printf 'struct A:\n    x: i64\nstruct B:\n    y: i64\nimpl Thing for A:\n    def m(self: Self) -> i64:\n        return 1\nimpl Thing for B:\n    def m(self: Self) -> i64:\n        return 2\n' | dups)
[ "$n" -eq 0 ] || fail "cross-impl same-signature method wrongly flagged (got $n)"

# 5. a name in different `static if` branches must NOT collide.
n=$(printf 'static if X:\n    def g() -> i64:\n        return 1\nstatic else:\n    def g() -> i64:\n        return 2\n' | dups)
[ "$n" -eq 0 ] || fail "static-if per-branch same name wrongly flagged (got $n)"

# 6. 0 FP across the whole frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE "duplicate declaration|duplicate type" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t duplicate-declaration false positives across frontend+stdlib"

echo "duplicate-decl smoke OK: flags identical-sig func + redeclared type; silent on overloads, struct+fn, cross-impl methods, static-if branches; 0 FP across frontend+stdlib"
