#!/usr/bin/env bash
# Stage0/stage1 regression: field type lookup must respect a struct's module.
# The same `Run.answer` key has incompatible types in Dynamic and Scalar.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
NW_CORE="${NW_CORE:-$ROOT/../../nw-core}"
STAGE0="${ELISACORE_BIN:-$NW_CORE/toolchain/elisac-stage0}"
STAGE1_BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE1_ROOT="${ELISA_STAGE1_ROOT:-$ROOT}"
FIXTURE="$ROOT/test/repro/stage1_struct_field_module_collision.elisa"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

for tool in "$STAGE0" "$STAGE1_BIN"; do
    if [[ ! -x "$tool" ]]; then
        echo "module struct field type collision smoke: missing compiler: $tool" >&2
        exit 2
    fi
done

if ! "$STAGE0" -emit obj -O0 -o "$TMP_DIR/stage0.o" "$FIXTURE" >"$TMP_DIR/stage0.log" 2>&1; then
    echo "module struct field type collision smoke: stage0 compile failed" >&2
    sed -n '1,80p' "$TMP_DIR/stage0.log" >&2
    exit 1
fi
if ! clang -o "$TMP_DIR/stage0" "$TMP_DIR/stage0.o" >"$TMP_DIR/stage0-link.log" 2>&1; then
    echo "module struct field type collision smoke: stage0 link failed" >&2
    sed -n '1,80p' "$TMP_DIR/stage0-link.log" >&2
    exit 1
fi

if ! ELISA_STAGE1_ROOT="$STAGE1_ROOT" ELISA_STAGE1_BIN="$STAGE1_BIN" \
    "$STAGE1_ROOT/scripts/elisac_stage1.sh" -emit exe -O0 \
    -o "$TMP_DIR/stage1" "$FIXTURE" >"$TMP_DIR/stage1.log" 2>&1; then
    echo "module struct field type collision smoke: stage1 compile failed" >&2
    sed -n '1,80p' "$TMP_DIR/stage1.log" >&2
    exit 1
fi

set +e
"$TMP_DIR/stage0"
stage0_status=$?
"$TMP_DIR/stage1"
stage1_status=$?
set -e

if [[ "$stage0_status" -ne 42 || "$stage1_status" -ne 42 ]]; then
    echo "module struct field type collision smoke FAILED: stage0=$stage0_status stage1=$stage1_status expected=42" >&2
    exit 1
fi

echo "module struct field type collision smoke OK: both stages return 42"
