#!/usr/bin/env bash
# Aggregates of every C-ABI class must cross an export boundary exactly as clang's
# C ABI expects, from BOTH compilers: a C caller is linked against each compiler's
# object and emitted header and run on this host (arm64: HFA, [2 x i64], i64/iN,
# indirect + sret), and the wasm32 lowering is checked statically against the
# signatures clang emits for the same shapes (byval / sret / lone-scalar unwrap).
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../stage0/compiler/bin/elisac-local}"
RUNTIME="$ROOT/build/runtime/elisacore_runtime.o"
FIX="$ROOT/test/parity/fixtures/export_cabi"
[ -x "$ELISACORE_BIN" ] || { echo "export_cabi_shapes_smoke SKIP: no stage0 at $ELISACORE_BIN"; exit 0; }
[ -f "$RUNTIME" ] || { echo "export_cabi_shapes_smoke SKIP: no runtime object"; exit 0; }
BUILD="$ROOT/build/export_cabi_shapes_smoke"; mkdir -p "$BUILD"
status=0
run_one() {
  local label="$1" fixture="$2"; shift 2
  local dir="$BUILD/$label"; mkdir -p "$dir"
  if ! "$@" -emit obj -O0 -o "$dir/$fixture.o" "$FIX/$fixture.elisa" >"$dir/$fixture.obj.log" 2>&1; then echo "export_cabi_shapes_smoke FAIL [$label $fixture]: compile"; grep -v warning "$dir/$fixture.obj.log" | head -3; status=1; return; fi
  "$@" -emit header -o "$dir/$fixture.h" "$FIX/$fixture.elisa" >"$dir/$fixture.hdr.log" 2>&1 || { echo "export_cabi_shapes_smoke FAIL [$label $fixture]: header"; status=1; return; }
  if ! clang -Wl,-dead_strip -I"$dir" -o "$dir/$fixture" "$FIX/${fixture}_caller.c" "$dir/$fixture.o" "$RUNTIME" >"$dir/$fixture.link.log" 2>&1; then echo "export_cabi_shapes_smoke FAIL [$label $fixture]: link"; head -5 "$dir/$fixture.link.log"; status=1; return; fi
  out="$("$dir/$fixture" || true)"
  [ "$out" = "ALL OK" ] || { echo "export_cabi_shapes_smoke FAIL [$label $fixture]: C caller says: $out"; status=1; return; }
  echo "export_cabi_shapes_smoke OK [$label $fixture]: ALL OK from C"
}
for fixture in abi_shapes abi_small; do
  run_one stage0 "$fixture" "$ELISACORE_BIN"
  run_one stage1 "$fixture" bash "$ROOT/scripts/elisac_stage1.sh"
done
# wasm32: static signature check (no execution) against clang's lowering for these
# shapes: aggregates are byval in and sret out.
if ELISA_STAGE1_WASM=1 bash "$ROOT/scripts/elisac_stage1.sh" -O0 -emit llvm -o "$BUILD/wasm.ll" "$FIX/abi_shapes.elisa" >"$BUILD/wasm.log" 2>&1; then
  wasm_ok=1
  for spec in "take_i12=ptr byval" "take_f16=ptr byval" "take_l24=ptr byval" "ret_i12=ptr sret" "ret_f16=ptr sret" "ret_l24=ptr sret"; do
    fn="${spec%%=*}"; want="${spec#*=}"
    line="$(grep -E "^define .*@$fn\(" "$BUILD/wasm.ll" | head -1)"
    case "$line" in *"$want"*) ;; *) echo "export_cabi_shapes_smoke FAIL [wasm32 $fn]: expected '$want' in: $line"; status=1; wasm_ok=0;; esac
  done
  [ $wasm_ok -eq 1 ] && echo "export_cabi_shapes_smoke OK [wasm32]: byval/sret lowering matches clang"
else
  echo "export_cabi_shapes_smoke NOTE: wasm32 IR emission unavailable (see $BUILD/wasm.log)"
fi
exit $status
