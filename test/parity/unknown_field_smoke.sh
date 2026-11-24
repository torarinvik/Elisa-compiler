#!/usr/bin/env bash
# Behavioral smoke for the stage1 UnknownField diagnostic (parity with stage0's
# `struct literal "S" has no field "f"`). Asserts it FIRES on a `Name{label: v}`
# construction naming an undeclared field, and STAYS SILENT on valid fields,
# positional (unlabeled) construction, generic/qualified type exprs, structs with
# an anonymous member (partial field set), and across the whole frontend + stdlib
# (every corpus file compiles on stage0, so ANY finding there is a false positive).
#
# Usage: test/parity/unknown_field_smoke.sh
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() { echo "unknown-field smoke FAIL: $1" >&2; exit 1; }

P2='struct Point:\n    x: i64\n    y: i64\n\n'

# 1. a labeled field the struct does not declare MUST be flagged (and name the struct).
out=$(printf "${P2}def f() -> Point:\n    return Point{x: 1, z: 3}\n" | "$RPT")
grep -q "struct literal \"Point\" has no field \"z\"" <<< "$out" || fail "unknown field not flagged: $out"

# 2. an all-valid construction must NOT be flagged.
out=$(printf "${P2}def g() -> Point:\n    return Point{x: 1, y: 2}\n" | "$RPT")
grep -q "has no field" <<< "$out" && fail "false positive on valid construction: $out"

# 3. positional (unlabeled) construction bails (no label to check).
out=$(printf "${P2}def h() -> Point:\n    return Point{1, 2}\n" | "$RPT")
grep -q "has no field" <<< "$out" && fail "false positive on positional construction: $out"

# 4. an unknown/other type name (not a registered struct) bails.
out=$(printf "def k() -> i64:\n    v = Widget{nope: 1}\n    return 0\n" | "$RPT")
grep -q "has no field" <<< "$out" && fail "false positive on non-struct type: $out"

# 5. a generic/index type expr (Box[i64]{...}) is not a bare identifier -> bails.
out=$(printf "struct Box:\n    v: i64\n\ndef m() -> i64:\n    b = Box[i64]{bad: 1}\n    return 0\n" | "$RPT")
grep -q "has no field" <<< "$out" && fail "false positive on generic type expr: $out"

# 6. a field label given twice MUST be flagged (DuplicateFieldInit, same code path).
out=$(printf "${P2}def d() -> Point:\n    return Point{x: 1, x: 2, y: 3}\n" | "$RPT")
grep -q "struct literal \"Point\" field \"x\" is specified more than once" <<< "$out" || fail "duplicate field label not flagged: $out"

# 7. a valid all-distinct construction must NOT be flagged as duplicate.
out=$(printf "${P2}def e() -> Point:\n    return Point{x: 1, y: 2}\n" | "$RPT")
grep -q "more than once" <<< "$out" && fail "false positive on distinct fields: $out"

# 8. a by-label construction omitting a REQUIRED field MUST be flagged (MissingField).
out=$(printf "${P2}def mf() -> Point:\n    return Point{x: 1}\n" | "$RPT")
grep -q "struct literal \"Point\" is missing field \"y\"" <<< "$out" || fail "missing required field not flagged: $out"

# 9. empty `{}` and positional construction bail (no missing-field report).
out=$(printf "${P2}def em() -> Point:\n    return Point{}\n" | "$RPT")
grep -q "is missing field" <<< "$out" && fail "false positive on empty construction: $out"
out=$(printf "${P2}def po() -> Point:\n    return Point{1, 2}\n" | "$RPT")
grep -q "is missing field" <<< "$out" && fail "false positive on positional construction: $out"

# 10. optional (`z?: T`) and defaulted (`w: T = v`) fields are omittable — NOT missing.
POM='struct Q:\n    x: i64\n    y: i64 = 5\n    z?: i64\n\n'
out=$(printf "${POM}def op() -> Q:\n    return Q{x: 1}\n" | "$RPT")
grep -q "is missing field" <<< "$out" && fail "false positive on omittable (default/optional) fields: $out"

# 11. a record update naming an absent field gets the record-update-specific finding.
out=$(printf "${P2}def ru(point: Point) -> Point:\n    return point{z = 3}\n" | "$RPT")
grep -q "record update has no field \"z\"" <<< "$out" || fail "unknown record-update field not flagged: $out"

# 12. valid record updates stay silent.
out=$(printf "${P2}def rv(point: Point) -> Point:\n    return point{x = 3}\n" | "$RPT")
grep -q "record update has no field" <<< "$out" && fail "false positive on valid record update: $out"

# 13. the whole frontend + stdlib must produce ZERO findings for any field check.
# Anonymous let destructuring preserves selectors separately from binders.
out=$(printf "${P2}def ld(point: Point) -> i64:\n    let {z} = point\n    return 0\n" | "$RPT")
grep -q 'struct "Point" has no field "z"' <<< "$out" || fail "unknown let-destructure field not flagged: $out"
out=$(printf "${P2}def lr(point: Point) -> i64:\n    let {x: renamed} = point\n    return renamed\n" | "$RPT")
grep -q 'has no field "renamed"' <<< "$out" && fail "binder was confused with let field selector: $out"

# Field access on a struct reached through a module-qualified type. stage0 names the
# struct by its dotted module path; a bare name only for a top-level struct.
out=$(printf "${P2}def fa(point: Point) -> i64:\n    point.z\n" | "$RPT")
grep -q 'struct "Point" has no field "z"' <<< "$out" || fail "top-level field access not flagged bare: $out"
out=$(printf "module Outer:\n    struct Thing:\n        a: i64\nmodule Other:\n    def fq(t: Outer::Thing) -> i64:\n        t.missing\n" | "$RPT")
grep -q 'struct "Outer.Thing" has no field "missing"' <<< "$out" || fail "qualified parameter field not flagged: $out"
out=$(printf "module Outer:\n    module Inner:\n        struct Thing:\n            a: i64\nmodule Other:\n    struct Box:\n        thing: Outer::Inner::Thing\n    def fc(b: Box) -> i64:\n        b.thing.missing\n" | "$RPT")
grep -q 'struct "Outer.Inner.Thing" has no field "missing"' <<< "$out" || fail "qualified field-chain field not flagged: $out"
# Two modules declaring `Thing`: each access is checked against the struct it names, not
# the union of both field lists.
SAME='module Left:\n    struct Thing:\n        a: i64\nmodule Right:\n    struct Thing:\n        b: i64\n'
out=$(printf "${SAME}    def fl(t: Left::Thing) -> i64:\n        t.b\n    def fr(t: Thing) -> i64:\n        t.a\n" | "$RPT")
grep -q 'struct "Left.Thing" has no field "b"' <<< "$out" || fail "field of the other same-named struct not flagged: $out"
grep -q 'struct "Right.Thing" has no field "a"' <<< "$out" || fail "bare same-named struct not resolved to its module: $out"
out=$(printf "${SAME}    def fv(t: Left::Thing, u: Thing) -> i64:\n        t.a + u.b\n" | "$RPT")
grep -q "has no field" <<< "$out" && fail "false positive on valid same-named struct fields: $out"
# A loop binder shadows only inside its loop.
out=$(printf "module Outer:\n    struct Thing:\n        a: i64\n    def fs(t: Thing) -> i64:\n        inner: Thing = t\n        for t in 0..<3:\n            pass\n        inner.missing\n" | "$RPT")
grep -q 'struct "Outer.Thing" has no field "missing"' <<< "$out" || fail "local in a module not flagged with its module: $out"

n=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE "has no field|more than once|is missing field" || true)
  n=$((n + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$n" -eq 0 ] || fail "$n struct-literal field false positives across frontend+stdlib"

echo "unknown-field smoke OK: flags construction/update field errors, silent on valid/positional/empty/generic/omittable, 0 false positives across frontend+stdlib"
