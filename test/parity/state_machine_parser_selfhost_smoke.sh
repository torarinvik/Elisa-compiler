#!/usr/bin/env bash
# The parser's bit-group scan must remain a real `machine over` after lowering.
# This compiles the native emitter with the stage1 product itself; that source includes
# parse_bit_group_members, so a broken state-transition capture is observed before any
# user program is compiled.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PRODUCT="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"

[[ -x "$PRODUCT" ]] || { echo "state-machine parser self-host smoke SKIP: no stage1 product at $PRODUCT"; exit 0; }
[[ -f "$RUNTIME" ]] || { echo "state-machine parser self-host smoke SKIP: no runtime object at $RUNTIME"; exit 0; }
[[ -x "$LLVM_CONFIG" ]] || { echo "state-machine parser self-host smoke SKIP: no llvm-config at $LLVM_CONFIG"; exit 0; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-state-machine-parser.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

unset ELISACORE_BIN || true
export ELISA_STAGE1_BIN="$PRODUCT"
export PATH="/usr/bin:/bin:/opt/homebrew/bin:/opt/homebrew/opt/llvm/bin"

ELISA_DBG_DECLINE=1 bash "$ROOT/scripts/elisac_stage1.sh" -O0 \
  -o "$WORK/emit_native.o" "$ROOT/test/breadth/emit_native.elisa" \
  >"$WORK/build.log" 2>&1

if grep -q 'DROPPED parse_bit_group_members' "$WORK/build.log"; then
  echo "state-machine parser self-host smoke FAIL: parse_bit_group_members was declined" >&2
  exit 1
fi

LIBDIR="$($LLVM_CONFIG --libdir)"
LLC="$(dirname -- "$LLVM_CONFIG")/llc"
clang -Wl,-dead_strip -o "$WORK/emit_native" "$WORK/emit_native.o" "$RUNTIME" \
  -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR"

printf '%b' 'struct Flags:\n    bits: bitset:\n        Read\n        Write\n\ndef main() -> i64:\n    return 42\n' \
  | "$WORK/emit_native" >"$WORK/bitset.ll"
"$LLC" -filetype=obj "$WORK/bitset.ll" -o "$WORK/bitset.o"
clang -Wl,-dead_strip -o "$WORK/bitset" "$WORK/bitset.o" "$RUNTIME"
set +e
"$WORK/bitset"
status=$?
set -e
[[ "$status" -eq 42 ]] || { echo "state-machine parser self-host smoke FAIL: bit-group input returned $status" >&2; exit 1; }

echo "state-machine parser self-host smoke OK: machine lowering and bit-group parsing survive stage1 product"
