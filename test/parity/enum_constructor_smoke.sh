#!/usr/bin/env bash
# Behavioral smoke for named enum-constructor argument checks.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() { echo "enum-constructor smoke FAIL: $1" >&2; exit 1; }

# 1. Named payload fields may be supplied out of declaration order.
out=$(printf 'enum E:\n    A(x: i64, y: i64)\n\ndef f() -> E:\n    return E.A(y: 2, x: 1)\n' | "$RPT")
echo "$out" | grep -q "enum constructor \"A\"" && fail "false positive on valid named enum constructor: $out"

# 2. Positional and named payload arguments may not be mixed.
out=$(printf 'enum E:\n    A(x: i64, y: i64)\n\ndef f() -> E:\n    return E.A(1, y: 2)\n' | "$RPT")
echo "$out" | grep -q "cannot mix positional and named arguments" || fail "mixed enum args not flagged: $out"

# 3. Named construction requires named payload fields.
out=$(printf 'enum E:\n    A(i64, i64)\n\ndef f() -> E:\n    return E.A(x: 1, y: 2)\n' | "$RPT")
echo "$out" | grep -q "does not declare named payload fields" || fail "unnamed enum payload accepted named args: $out"

out=$(printf 'enum MaybeInt:\n    Some(int)\ndef unwrap(value: MaybeInt) -> int:\n    match value:\n        MaybeInt.Some(value: inner):\n            return inner\n    return 0\n' | "$RPT")
echo "$out" | grep -Fq 'match arm "MaybeInt.Some" does not declare named payload fields' || fail "unnamed payload accepted named pattern: $out"

out=$(printf 'error BackendError:\n    UnsupportedType(span: i64, code: i32)\ndef fail() -> i64 error[BackendError]:\n    raise BackendError.UnsupportedType("bad".cast[u8&], 7)\n' | "$RPT")
echo "$out" | grep -Fq 'error constructor argument 1 to "BackendError.UnsupportedType" expects i64' || fail "bad error payload argument accepted: $out"

# 4. Unknown payload labels are rejected.
out=$(printf 'enum E:\n    A(x: i64)\n\ndef f() -> E:\n    return E.A(y: 1)\n' | "$RPT")
echo "$out" | grep -q "has no payload field \"y\"" || fail "unknown enum payload field not flagged: $out"

# 5. A payload field may not be supplied twice.
out=$(printf 'enum E:\n    A(x: i64, y: i64)\n\ndef f() -> E:\n    return E.A(x: 1, x: 2)\n' | "$RPT")
echo "$out" | grep -q "payload field \"x\" is specified more than once" || fail "duplicate enum payload field not flagged: $out"

# 6. All named payload fields must be supplied.
out=$(printf 'enum E:\n    A(x: i64, y: i64)\n\ndef f() -> E:\n    return E.A(x: 1)\n' | "$RPT")
echo "$out" | grep -q "missing payload field \"y\"" || fail "missing enum payload field not flagged: $out"

echo "enum-constructor smoke OK: named payload args accepted/rejected with stage0-style checks"
