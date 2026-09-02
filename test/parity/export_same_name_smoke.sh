#!/usr/bin/env bash
# Same-name exports must be reachable from C under their own names, with the C
# ABI, from BOTH compilers: a scalar export is the implementation itself, an
# 8-byte aggregate export is a wrapper (implementation renamed `.impl`), a
# same-name type and global register nothing new. Links a C caller against
# each compiler's object and the emitted header and runs it.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../stage0/compiler/bin/elisac-local}"
RUNTIME="$ROOT/build/runtime/elisacore_runtime.o"
[ -x "$ELISACORE_BIN" ] || { echo "export_same_name_smoke SKIP: no stage0 at $ELISACORE_BIN"; exit 0; }
[ -f "$RUNTIME" ] || { echo "export_same_name_smoke SKIP: no runtime object"; exit 0; }
BUILD="$ROOT/build/export_same_name_smoke"; mkdir -p "$BUILD"
cat > "$BUILD/mod.elisa" <<'ELISA'
struct Vec2 layout(c):
    x: i32
    y: i32
export type Vec2 as Vec2
global MAGIC: i32 = 1337
export global MAGIC as MAGIC
def add(a: i32, b: i32) -> i32:
    return a + b
export fn add(a: i32, b: i32) -> i32 = add
def vec2_sum(v: Vec2) -> i32:
    return v.x + v.y
export fn vec2_sum(v: Vec2) -> i32 = vec2_sum
def make_vec2(x: i32, y: i32) -> Vec2:
    return Vec2{x: x, y: y}
export fn make_vec2(x: i32, y: i32) -> Vec2 = make_vec2
def mul_impl(a: i32, b: i32) -> i32:
    return a * b
export fn mul(a: i32, b: i32) -> i32 = mul_impl
def uses_internally() -> i32:
    v: Vec2 = Vec2{x: 3, y: 4}
    return add(vec2_sum(v), MAGIC)
export fn uses_internally() -> i32 = uses_internally
ELISA
cat > "$BUILD/caller.c" <<'C'
#include <stdio.h>
#include "mod.h"
int main(void) {
    Vec2 v = { 20, 22 };
    int ok = 1;
    ok &= add(1, 2) == 3;
    ok &= vec2_sum(v) == 42;
    ok &= mul(6, 7) == 42;
    ok &= MAGIC == 1337;
    ok &= uses_internally() == 1344;
    Vec2 m = make_vec2(5, 6);
    ok &= m.x == 5 && m.y == 6;
    ok &= vec2_sum(make_vec2(8, 9)) == 17;
    printf("%s\n", ok ? "ALL OK" : "FAILED");
    return ok ? 0 : 1;
}
C
status=0
run_one() {
  local label="$1"; shift
  local dir="$BUILD/$label"; mkdir -p "$dir"
  if ! "$@" -emit obj -O0 -o "$dir/mod.o" "$BUILD/mod.elisa" >"$dir/obj.log" 2>&1; then echo "export_same_name_smoke FAIL [$label]: compile"; head -3 "$dir/obj.log"; status=1; return; fi
  if ! "$@" -emit header -o "$dir/mod.h" "$BUILD/mod.elisa" >"$dir/hdr.log" 2>&1; then echo "export_same_name_smoke FAIL [$label]: header"; head -3 "$dir/hdr.log"; status=1; return; fi
  for sym in _add _vec2_sum _mul _uses_internally _make_vec2; do
    nm "$dir/mod.o" | grep -q " T $sym\$" || { echo "export_same_name_smoke FAIL [$label]: $sym is not an external symbol"; nm "$dir/mod.o" | grep -i "$sym" || true; status=1; return; }
  done
  if ! clang -Wl,-dead_strip -I"$dir" -o "$dir/caller" "$BUILD/caller.c" "$dir/mod.o" "$RUNTIME" >"$dir/link.log" 2>&1; then echo "export_same_name_smoke FAIL [$label]: link"; head -5 "$dir/link.log"; status=1; return; fi
  out="$("$dir/caller" || true)"
  if [ "$out" != "ALL OK" ]; then echo "export_same_name_smoke FAIL [$label]: C caller says: $out"; status=1; return; fi
  echo "export_same_name_smoke OK [$label]: ALL OK from C"
}
run_one stage0 "$ELISACORE_BIN"
run_one stage1 bash "$ROOT/scripts/elisac_stage1.sh"
exit $status
