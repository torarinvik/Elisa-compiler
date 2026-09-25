#!/usr/bin/env bash
# Value-position struct patterns must use the same destructuring path as slot matches.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
VALID="$ROOT/test/fixtures/diagnostics/struct_pattern_type_mismatch.neg.elisa"
INVALID="$ROOT/test/fixtures/diagnostics/struct_pattern_type_mismatch.pos.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-struct-pattern-value.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

# P{a: x} against P is valid and binds x; the similar Q{b: x} against P is invalid.
"$STAGE0" -emit obj -O0 -o "$WORK/stage0-valid.o" "$VALID" >/dev/null 2>&1
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1-valid.ll" "$VALID" >/dev/null 2>&1
! rg -q '!elisa\.declined' "$WORK/stage1-valid.ll"
/opt/homebrew/opt/llvm/bin/opt -passes=verify -disable-output "$WORK/stage1-valid.ll"

set +e
"$STAGE0" -emit obj -O0 -o "$WORK/stage0-invalid.o" "$INVALID" >/dev/null 2>&1
stage0_invalid=$?
"$STAGE1" -emit obj -O0 -o "$WORK/stage1-invalid.o" "$INVALID" >/dev/null 2>&1
stage1_invalid=$?
set -e
test "$stage0_invalid" -ne 0
test "$stage1_invalid" -ne 0
test ! -e "$WORK/stage0-invalid.o"
test ! -e "$WORK/stage1-invalid.o"

echo "struct pattern value smoke OK: valid destructure accepted; mismatched struct rejected by both stages"
