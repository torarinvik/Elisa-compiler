#!/usr/bin/env bash
# Qualified generic calls must bind to the requested module, not a same-named
# top-level generic. Covers inferred type arguments, explicit one-/two-argument
# type application, and a monomorphic module function shadowed by a top-level
# generic. Every path is checked by running stage0 and stage1 output.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../nw-core/toolchain/elisac-stage0}"
STAGE1_ROOT="${ELISA_STAGE1_ROOT:-$ROOT}"
STAGE1_BIN="${ELISA_STAGE1_BIN:-$STAGE1_ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/../../nw-core/toolchain/elisacore_runtime.o}"
FIXTURE="$ROOT/test/repro/qualified_generic_scope_shadow.elisa"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

for tool in "$STAGE0" "$STAGE1_BIN" "$RUNTIME_OBJ"; do
    if [[ ! -e "$tool" ]]; then
        echo "qualified generic scope smoke: missing required tool/artifact: $tool" >&2
        exit 2
    fi
done

if ! "$STAGE0" -emit obj -O0 -o "$TMP_DIR/stage0.o" "$FIXTURE" >"$TMP_DIR/stage0.log" 2>&1; then
    echo "qualified generic scope smoke: stage0 compile failed" >&2
    sed -n '1,80p' "$TMP_DIR/stage0.log" >&2
    exit 1
fi
if ! clang -o "$TMP_DIR/stage0" "$TMP_DIR/stage0.o" >"$TMP_DIR/stage0-link.log" 2>&1; then
    echo "qualified generic scope smoke: stage0 link failed" >&2
    sed -n '1,80p' "$TMP_DIR/stage0-link.log" >&2
    exit 1
fi

if ! ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1_BIN" ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" \
    "$STAGE1_ROOT/scripts/elisac_stage1.sh" -emit exe -O0 -o "$TMP_DIR/stage1" "$FIXTURE" \
    >"$TMP_DIR/stage1.log" 2>&1; then
    echo "qualified generic scope smoke: stage1 compile failed" >&2
    sed -n '1,80p' "$TMP_DIR/stage1.log" >&2
    exit 1
fi

set +e
"$TMP_DIR/stage0"
stage0_rc=$?
"$TMP_DIR/stage1"
stage1_rc=$?
set -e

if [[ "$stage0_rc" -ne 168 || "$stage1_rc" -ne "$stage0_rc" ]]; then
    echo "qualified generic scope smoke FAILED: stage0=$stage0_rc stage1=$stage1_rc expected=168" >&2
    exit 1
fi

echo "qualified generic scope smoke OK: inferred/explicit module generics and shadowed direct call return 168"

# Selecting Target::identity must not change the lexical scope of pick(10).
ARGUMENT_FIXTURE="$ROOT/test/repro/qualified_generic_argument_scope.elisa"
"$STAGE0" -emit obj -O0 -o "$TMP_DIR/argument-stage0.o" "$ARGUMENT_FIXTURE"
clang -o "$TMP_DIR/argument-stage0" "$TMP_DIR/argument-stage0.o"
ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1_BIN" ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" \
    "$STAGE1_ROOT/scripts/elisac_stage1.sh" -emit exe -O0 -o "$TMP_DIR/argument-stage1" "$ARGUMENT_FIXTURE"
set +e
"$TMP_DIR/argument-stage0"
stage0_rc=$?
"$TMP_DIR/argument-stage1"
stage1_rc=$?
set -e
if [[ "$stage0_rc" -ne 1 || "$stage1_rc" -ne 1 ]]; then
    echo "qualified argument scope FAILED: stage0=$stage0_rc stage1=$stage1_rc expected=1" >&2
    exit 1
fi
echo "qualified generic argument scope OK: both stages resolve the caller's pick"
