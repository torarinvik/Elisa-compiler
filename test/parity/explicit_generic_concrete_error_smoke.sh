#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
SOURCE="$ROOT/test/repro/explicit_generic_concrete_error_propagation.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-concrete-error.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
"$STAGE0" -emit llvm -O0 -o "$WORK/stage0.ll" "$SOURCE" >/dev/null
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$SOURCE" >/dev/null
for output in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    ! rg -q '!elisa\.declined' "$output"
done
"$STAGE1" -emit exe -O0 -o "$WORK/probe" "$SOURCE" >/dev/null
"$WORK/probe"
echo 'explicit generic concrete-error propagation smoke passed'
