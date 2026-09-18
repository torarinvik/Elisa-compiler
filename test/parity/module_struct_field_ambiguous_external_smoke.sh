#!/usr/bin/env bash
# COMP-010: ambiguous external bare-name field rows must stay unknown, not guessed.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
NW_CORE="${NW_CORE:-$ROOT/../../nw-core}"
STAGE0="${ELISACORE_BIN:-$NW_CORE/toolchain/elisac-stage0}"
STAGE1_ROOT="${ELISA_STAGE1_ROOT:-$ROOT}"
STAGE1_BIN="${ELISA_STAGE1_BIN:-$STAGE1_ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/module_struct_field_ambiguous_external.elisa"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

for tool in "$STAGE0" "$STAGE1_BIN"; do
    if [[ ! -x "$tool" ]]; then
        echo "module struct field ambiguous external: missing compiler: $tool" >&2
        exit 2
    fi
done

"$STAGE0" -emit obj -O0 -o "$TMP_DIR/stage0.o" "$FIXTURE"
cc -o "$TMP_DIR/stage0" "$TMP_DIR/stage0.o"
ELISA_STAGE1_ROOT="$STAGE1_ROOT" ELISA_STAGE1_BIN="$STAGE1_BIN" \
    "$STAGE1_ROOT/scripts/elisac_stage1.sh" -emit exe -O0 \
    -o "$TMP_DIR/stage1" "$FIXTURE"

ELISA_STAGE1_ROOT="$STAGE1_ROOT" ELISA_STAGE1_BIN="$STAGE1_BIN" \
    "$STAGE1_ROOT/scripts/elisac_stage1.sh" -emit llvm -O0 \
    -o "$TMP_DIR/stage1.ll" "$FIXTURE"
! rg -q '!elisa\.declined' "$TMP_DIR/stage1.ll"

set +e
"$TMP_DIR/stage0"
stage0_rc=$?
"$TMP_DIR/stage1"
stage1_rc=$?
set -e

if [[ "$stage0_rc" -ne 0 || "$stage1_rc" -ne 0 ]]; then
    echo "module struct field ambiguous external FAILED: stage0=$stage0_rc stage1=$stage1_rc expected=0" >&2
    exit 1
fi

echo "module struct field ambiguous external OK"
