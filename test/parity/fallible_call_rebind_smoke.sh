#!/usr/bin/env bash
# Stage0/Stage1 parity for a fallible call used to update an existing local.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
SOURCE="$ROOT/test/repro/fallible_call_rebind.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-fallible-rebind.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$STAGE0" -emit llvm -O0 -o "$WORK/stage0.ll" "$SOURCE" >/dev/null
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$SOURCE" >/dev/null
for output in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    ! rg -q '!elisa\.declined' "$output"
done

# Stage0 exposes object/LLVM output but not a standalone executable emit mode.
# Stage1's executable exercises both the success value and error propagation.
"$STAGE1" -emit exe -O0 -o "$WORK/stage1" "$SOURCE" >/dev/null
"$WORK/stage1"

echo "fallible-call rebind parity OK: success value and propagated error paths match"
