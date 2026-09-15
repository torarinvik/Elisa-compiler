#!/usr/bin/env bash
# A module's Run.answer field type must not come from another module's Run.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
NW_CORE="${NW_CORE:-$ROOT/../../nw-core}"
STAGE0="${ELISACORE_BIN:-$NW_CORE/toolchain/elisac-stage0}"
STAGE1_ROOT="${ELISA_STAGE1_ROOT:-$ROOT}"
STAGE1_BIN="${ELISA_STAGE1_BIN:-$STAGE1_ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/module_struct_field_type_collision.elisa"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

for tool in "$STAGE0" "$STAGE1_BIN"; do
    if [[ ! -x "$tool" ]]; then
        echo "module struct field type collision: missing compiler: $tool" >&2
        exit 2
    fi
done

"$STAGE0" -emit obj -O0 -o "$TMP_DIR/stage0.o" "$FIXTURE"
clang -o "$TMP_DIR/stage0" "$TMP_DIR/stage0.o"
ELISA_STAGE1_ROOT="$STAGE1_ROOT" ELISA_STAGE1_BIN="$STAGE1_BIN" \
    "$STAGE1_ROOT/scripts/elisac_stage1.sh" -emit exe -O0 \
    -o "$TMP_DIR/stage1" "$FIXTURE"

set +e
"$TMP_DIR/stage0"
stage0_rc=$?
"$TMP_DIR/stage1"
stage1_rc=$?
set -e

if [[ "$stage0_rc" -ne 42 || "$stage1_rc" -ne 42 ]]; then
    echo "field collision smoke FAILED: stage0=$stage0_rc stage1=$stage1_rc expected=42" >&2
    exit 1
fi

echo "module struct field type collision smoke OK"
