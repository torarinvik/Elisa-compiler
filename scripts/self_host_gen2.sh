#!/usr/bin/env bash
# Attempt gen1 → gen2 product rebuild without stage0.
#
# Requires a seed product binary (scripts/elisac_stage1.sh --seed).
# Compiles src/driver/elisac.elisa with the stage1 product and links gen2.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT/build/self_host_gen2}"
mkdir -p "$OUT_DIR"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LIBDIR="$("$LLVM_CONFIG" --libdir)"

[[ -x "$BIN" ]] || { echo "missing product binary $BIN" >&2; exit 2; }
[[ -f "$RUNTIME_OBJ" ]] || { echo "missing runtime object $RUNTIME_OBJ (run scripts/build_runtime_object.sh)" >&2; exit 2; }
unset ELISACORE_BIN || true
export ELISA_STAGE1_BIN="$BIN"
export PATH="/usr/bin:/bin:/opt/homebrew/bin:/opt/homebrew/opt/llvm/bin"

echo "gen1=$BIN"
file "$BIN"
bash "$ROOT/scripts/elisac_stage1.sh" -o "$OUT_DIR/elisac_stage1_gen2.o" "$ROOT/src/driver/elisac.elisa"
clang -Wl,-dead_strip -o "$OUT_DIR/elisac-stage1-gen2" "$OUT_DIR/elisac_stage1_gen2.o" "$RUNTIME_OBJ" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR"
echo "wrote $OUT_DIR/elisac-stage1-gen2"
# Fixture parity with gen2
printf 'def main() -> i64:\n    return 42\n' >"$OUT_DIR/fix.elisa"
export ELISA_STAGE1_BIN="$OUT_DIR/elisac-stage1-gen2"
bash "$ROOT/scripts/elisac_stage1.sh" -o "$OUT_DIR/fix.o" "$OUT_DIR/fix.elisa"
clang -Wl,-dead_strip -o "$OUT_DIR/fix" "$OUT_DIR/fix.o" "$RUNTIME_OBJ"
set +e
"$OUT_DIR/fix"
rc=$?
set -e
[[ "$rc" -eq 42 ]] || { echo "gen2 fixture exit $rc want 42" >&2; exit 1; }
echo "self_host_gen2 OK"
