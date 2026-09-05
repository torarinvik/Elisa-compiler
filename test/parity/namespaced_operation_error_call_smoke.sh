#!/usr/bin/env bash
# Bare initializers must use the same module owner as call emission, even when
# another module declares the same name/arity with a different struct result.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
FIXTURE="$ROOT/test/repro/namespaced_operation_error_call.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-namespaced-operation.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

"$STAGE0" -emit obj -O0 -o "$WORK/stage0.o" "$FIXTURE"
cc "$WORK/stage0.o" -o "$WORK/stage0"
"$STAGE1" -emit exe -O0 -o "$WORK/stage1" "$FIXTURE"
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$FIXTURE"
! rg -q '!elisa\.declined' "$WORK/stage1.ll"
"$WORK/stage0"
"$WORK/stage1"
echo "namespaced operation parity OK: native success and error fallback on both stages"
