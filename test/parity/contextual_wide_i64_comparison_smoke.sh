#!/usr/bin/env bash
# Stage0/stage1 regression: a wide unsuffixed integer comparison bound must
# preserve the contextual i64 value instead of truncating it through `int`.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
NW_CORE="${NW_CORE:-$ROOT/../../nw-core}"
STAGE0="${ELISACORE_BIN:-$NW_CORE/toolchain/elisac-stage0}"
STAGE1_BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1_BIN" || exit $?
STAGE1_ROOT="${ELISA_STAGE1_ROOT:-$ROOT}"
FIXTURE="$ROOT/test/repro/contextual_wide_i64_comparison.elisa"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

for tool in "$STAGE0" "$STAGE1_BIN"; do
    if [[ ! -x "$tool" ]]; then
        echo "contextual wide i64 comparison smoke: missing compiler: $tool" >&2
        exit 2
    fi
done

if ! "$STAGE0" -emit llvm -O0 -target-triple wasm32-unknown-wasi \
    -o "$TMP_DIR/stage0.ll" "$FIXTURE" >"$TMP_DIR/stage0.log" 2>&1; then
    echo "contextual wide i64 comparison smoke: stage0 compile failed" >&2
    sed -n '1,80p' "$TMP_DIR/stage0.log" >&2
    exit 1
fi
if ! ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1_BIN" \
    "$STAGE1_ROOT/scripts/elisac_stage1.sh" -emit llvm -O0 \
    -target-triple wasm32-unknown-wasi \
    -o "$TMP_DIR/stage1.ll" "$FIXTURE" >"$TMP_DIR/stage1.log" 2>&1; then
    echo "contextual wide i64 comparison smoke: stage1 compile failed" >&2
    sed -n '1,80p' "$TMP_DIR/stage1.log" >&2
    exit 1
fi

for stage in stage0 stage1; do
    if ! grep -Eq 'icmp slt i64 .*9223372036854775806' "$TMP_DIR/$stage.ll"; then
        echo "contextual wide i64 comparison smoke FAILED: $stage did not emit the full positive i64 bound" >&2
        rg -n -C 2 'icmp slt' "$TMP_DIR/$stage.ll" >&2 || true
        exit 1
    fi
done

if grep -Eq 'icmp slt i64 .*[, ]-2([[:space:]]|$)' "$TMP_DIR/stage0.ll"; then
    echo "contextual wide i64 comparison smoke FAILED: stage0 truncated the bound to -2" >&2
    exit 1
fi

echo "contextual wide i64 comparison smoke OK: both stages preserve the full positive i64 bound"
