#!/usr/bin/env bash
# Scalar constraints nested in packed AST patterns must retain their comparisons.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/platform.sh"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
[[ -x "$STAGE1" ]]
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-nested-scalar.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/fixtures/backend/nested_scalar_enum_match.elisa"
for level in O0 O2; do
    "$STAGE1" -emit llvm "-$level" -o "$WORK/$level.ll" "$SOURCE" >"$WORK/$level-ir.log" 2>&1
    "$ELISA_LLVM_BIN_DIR/opt" -passes=verify -disable-output "$WORK/$level.ll"
    "$STAGE1" -emit exe "-$level" -o "$WORK/$level" "$SOURCE" >"$WORK/$level-exe.log" 2>&1
    "$WORK/$level"
done
echo 'nested scalar enum pattern Stage1 O0/O2 verifier and positive/negative execution OK'
