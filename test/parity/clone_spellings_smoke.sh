#!/usr/bin/env bash
# `x.clone()`, `clone(x)` and `clone[T](x)` are the builtin deep copy. The inferred spellings
# take the owned type from the source, every spelling reads through a reference, and structs
# clone field by field with no opt-in. A user function named clone keeps the plain spelling;
# the method stays the builtin unless that function takes the receiver's type. Affine and
# linear values are refused, as are structs that hold one.
#
# Usage: test/parity/clone_spellings_smoke.sh   (ELISAC overrides bin/elisac-stage1)
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISAC="${ELISAC:-$REPO_ROOT/bin/elisac-stage1}"
RUNTIME="${ELISA_RUNTIME_OBJECT:-$REPO_ROOT/build/runtime/elisacore_runtime.o}"
work="$(mktemp -d "${TMPDIR:-/tmp}/clone-spellings.XXXXXX")"
trap 'rm -rf "$work"' EXIT
fail() { echo "clone spellings smoke FAIL: $1" >&2; exit 1; }
run_program() {
  local name="$1" expected="$2"
  "$ELISAC" -emit obj -o "$work/$name.o" "$work/$name.elisa" > "$work/$name.log" 2>&1 || fail "$name: rejected: $(grep -v warning "$work/$name.log" | head -1)"
  clang -o "$work/$name" "$work/$name.o" "$RUNTIME" > /dev/null 2>&1 || fail "$name: link failed"
  local status=0
  "$work/$name" || status=$?
  [ "$status" = "$expected" ] || fail "$name: exit $status, expected $expected"
}
cat > "$work/spellings.elisa" <<'PROGRAM'
struct Point:
    x: i64
    tags: darray[i64]

def method_form(path: darray[u8]&) -> i64:
    copy: mutable darray[u8] = path.clone()
    copy.push(9)
    return copy.count.i64() * 100 + path.count.i64()

def function_form(path: darray[u8]&) -> i64:
    copy: darray[u8] = clone(path)
    return copy.count.i64()

def explicit_through_reference(path: darray[u8]&) -> i64:
    copy: darray[u8] = clone[darray[u8]](path)
    return copy.count.i64()

def struct_form(point: Point&) -> i64:
    other = point.clone()
    return other.tags[0] * 10 + other.x

def inferred_binding(path: darray[u8]&) -> i64:
    copy = path.clone()
    return copy.count.i64()

def main() -> i32:
    bytes: darray[u8] = [1, 2, 3]
    point: Point = Point{x: 1, tags: [7]}
    total: i64 = method_form(&bytes) + function_form(&bytes) + explicit_through_reference(&bytes) + struct_form(&point) + inferred_binding(&bytes)
    return (total - 400).i32()
PROGRAM
# 403 + 3 + 3 + 71 + 3 - 400
run_program spellings 83
cat > "$work/shadowed.elisa" <<'PROGRAM'
def clone(value: i64) -> i64:
    return value + 1

def use_both(path: darray[u8]&) -> i64:
    copy: darray[u8] = path.clone()
    return clone(copy.count.i64())

def main() -> i32:
    bytes: darray[u8] = [1, 2]
    return use_both(&bytes).i32()
PROGRAM
run_program shadowed 3
cat > "$work/affine.elisa" <<'PROGRAM'
affine struct Handle:
    id: i64

struct Holder:
    handle: Handle

def copy_handle(handle: Handle&) -> i64:
    other = handle.clone()
    return other.id

def copy_holder(holder: Holder) -> i64:
    other = clone(holder)
    return other.handle.id

def main() -> i32:
    return 0
PROGRAM
if "$ELISAC" -emit obj -o "$work/affine.o" "$work/affine.elisa" > "$work/affine.log" 2>&1; then
  fail "affine: cloning an affine value was accepted"
fi
grep -qF "clone cannot clone Handle& into Handle in v1" "$work/affine.log" || fail "affine: missing the reference rejection: $(grep -v warning "$work/affine.log" | head -1)"
grep -qF "clone cannot clone Holder into Holder in v1" "$work/affine.log" || fail "affine: missing the holder rejection: $(grep -v warning "$work/affine.log" | head -1)"
echo "clone spellings smoke OK: method, inferred and explicit clones through references, struct field-by-field copy, user clone kept, affine refused"
