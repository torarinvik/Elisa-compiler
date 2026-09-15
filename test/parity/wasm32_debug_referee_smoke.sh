#!/usr/bin/env bash
# The x86-64 debug-referee sentinels must remain representable and well-defined
# when the runtime is compiled for wasm32 by both stages.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../nw-core/toolchain/elisac-stage0}"
STAGE1_ROOT="${ELISA_STAGE1_ROOT:-$ROOT}"
STAGE1="${ELISA_STAGE1_BIN:-$STAGE1_ROOT/bin/elisac-stage1}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LLVM_BIN_DIR="${ELISA_LLVM_BIN_DIR:-$(dirname -- "$LLVM_CONFIG")}"
CLANG="${ELISA_CLANG:-$LLVM_BIN_DIR/clang}"
FIXTURE="$ROOT/test/repro/wasm32_debug_referee.elisa"

if [[ ! -x "$CLANG" ]]; then CLANG="$(command -v clang || true)"; fi
for tool in "$STAGE0" "$STAGE1" "$CLANG"; do
    if [[ -z "$tool" || ! -x "$tool" ]]; then
        echo "wasm32_debug_referee FAILED: missing required tool: ${tool:-clang}" >&2
        exit 2
    fi
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-wasm32-debug-referee.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$STAGE0" -emit llvm -O0 -target-triple wasm32-unknown-wasi \
    -o "$WORK/stage0.ll" "$FIXTURE"
ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1" \
    "$STAGE1_ROOT/scripts/elisac_stage1.sh" -emit llvm -O0 \
    -target-triple wasm32-unknown-wasi -o "$WORK/stage1.ll" "$FIXTURE"

# LLVM's reader/verifier rejects the malformed comparison and oversized shift
# that the old pointer-width constants produced; verify both stages explicitly.
"$CLANG" --target=wasm32-unknown-wasi -c "$WORK/stage0.ll" -o "$WORK/stage0.o"
"$CLANG" --target=wasm32-unknown-wasi -c "$WORK/stage1.ll" -o "$WORK/stage1.o"

grep -Eq 'lshr i64 .* 48' "$WORK/stage0.ll"
grep -Eq 'lshr i64 .* 48' "$WORK/stage1.ll"
grep -Eq 'icmp eq i64 .*140737488355328' "$WORK/stage0.ll"
grep -Eq 'icmp eq i64 .*140737488355328' "$WORK/stage1.ll"

echo "wasm32 debug-referee pointer-width smoke OK (stage0 and stage1 LLVM verified)"
