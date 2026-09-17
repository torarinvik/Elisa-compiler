#!/usr/bin/env bash
# Stage0/stage1 parity: a fallible qualified call returning a struct must keep
# both the hidden error out slot and its explicit source arguments. This also
# guards lexical same-name shielding (Operations::initial vs NetworkOperations::initial).
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
FIXTURE="$ROOT/test/repro/qualified_error_struct_return.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-qualified-error-aggregate.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$STAGE0" -emit llvm -O0 -o "$WORK/stage0.ll" "$FIXTURE" >/dev/null 2>&1
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$FIXTURE" >/dev/null 2>&1

for output in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    ! rg -q '!elisa\.declined' "$output"
    rg -q 'NetworkOperations.*initial.*ptr.*i32' "$output"
done

echo "qualified aggregate error parity OK: explicit arguments survive owner resolution"
