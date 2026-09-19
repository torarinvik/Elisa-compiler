#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="$ROOT/test/repro/match_arm_final_if.elisa"
OUT="${TMPDIR:-/tmp}/elisa-match-arm-final-if-$$"
trap 'rm -rf "$OUT"' EXIT
mkdir -p "$OUT"

STAGE0="${ELISA_STAGE0_BIN:-$ROOT/../Elisa-core/bin/elisacore}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/scripts/elisac_stage1.sh}"

"$STAGE0" -emit obj -O0 -o "$OUT/stage0.o" "$SOURCE"
"$STAGE1" -emit obj -O0 -o "$OUT/stage1.o" "$SOURCE"

echo "match-arm-final-if smoke OK"
