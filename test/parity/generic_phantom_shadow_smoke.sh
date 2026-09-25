#!/usr/bin/env bash
# An unmodeled generic argument is still a binding and must shadow a user declaration.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
SOURCE="$ROOT/test/fixtures/diagnostics/darray_struct_element.neg.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-phantom-shadow.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

{ printf 'include "%s/elisacore_std/elisacore_runtime.elisa"\n\n' "$ROOT"; cat "$SOURCE"; } > "$WORK/probe.elisa"
"$STAGE0" -emit obj -O0 -o "$WORK/stage0.o" "$WORK/probe.elisa" >/dev/null 2>&1
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$WORK/probe.elisa" >/dev/null 2>&1
! rg -q '!elisa\.declined' "$WORK/stage1.ll"
/opt/homebrew/opt/llvm/bin/opt -passes=verify -disable-output "$WORK/stage1.ll"

echo "generic phantom shadow smoke OK: both stages compile struct S with the runtime generic types"
