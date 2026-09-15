#!/usr/bin/env bash
# A 64-bit range counter with a wasm32 `usize` struct-field bound must emit a
# well-typed comparison and keep stage0/stage1 behavior identical.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../nw-core/toolchain/elisac-stage0}"
STAGE1_ROOT="${ELISA_STAGE1_ROOT:-$ROOT}"
STAGE1="${ELISA_STAGE1_BIN:-$STAGE1_ROOT/bin/elisac-stage1}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LLVM_BIN_DIR="${ELISA_LLVM_BIN_DIR:-$(dirname -- "$LLVM_CONFIG")}"
CLANG="${ELISA_CLANG:-$LLVM_BIN_DIR/clang}"
FIXTURE="$ROOT/test/repro/wasm32_for_bounds_width.elisa"

if [[ ! -x "$CLANG" ]]; then CLANG="$(command -v clang || true)"; fi
for tool in "$STAGE0" "$STAGE1" "$CLANG"; do
    if [[ -z "$tool" || ! -x "$tool" ]]; then
        echo "wasm32_for_bounds_width FAILED: missing required tool: ${tool:-clang}" >&2
        exit 2
    fi
done
for tool in node wasm-ld; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "wasm32_for_bounds_width FAILED: missing required command: $tool" >&2
        exit 2
    fi
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-wasm32-for-bounds.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$STAGE0" -emit llvm -O0 -target-triple wasm32-unknown-wasi \
    -o "$WORK/stage0.ll" "$FIXTURE"
ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1" \
    "$STAGE1_ROOT/scripts/elisac_stage1.sh" -emit llvm -O0 \
    -target-triple wasm32-unknown-wasi -o "$WORK/stage1.ll" "$FIXTURE"
"$CLANG" --target=wasm32-unknown-wasi -c "$WORK/stage0.ll" -o "$WORK/stage0-ir.o"
"$CLANG" --target=wasm32-unknown-wasi -c "$WORK/stage1.ll" -o "$WORK/stage1-ir.o"

ELISA_WASM_NO_CACHE=1 python3 "$ROOT/scripts/wasm_build.py" \
    --root "$ROOT" --compiler "$STAGE0" --source "$FIXTURE" \
    --output "$WORK/stage0.wasm" --target wasm32-unknown-wasi
ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1" \
    "$STAGE1_ROOT/scripts/elisac_stage1.sh" -emit wasm \
    -o "$WORK/stage1.wasm" "$FIXTURE"

node --input-type=module - "$WORK/stage0.mjs" "$WORK/stage1.mjs" <<'NODE'
for (const path of process.argv.slice(2)) {
  const load = (await import(path)).default;
  const wasm = await load();
  const actual = Number(wasm.wasm32_for_bounds_width());
  if (actual !== 6) throw new Error(`${path}: got ${actual}, expected 6`);
}
console.log("wasm32 mixed-width range bounds parity OK (stage0 == stage1 == 6)");
NODE
