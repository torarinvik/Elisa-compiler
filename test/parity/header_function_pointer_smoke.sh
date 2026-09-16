#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0" || exit $?
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
FIXTURE="$ROOT/test/repro/header_function_pointer.elisa"

[[ -x "$STAGE0" ]] || { echo "header_function_pointer_smoke FAIL: no stage0 at $STAGE0" >&2; exit 1; }
[[ -x "$STAGE1" ]] || { echo "header_function_pointer_smoke FAIL: no stage1 at $STAGE1" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$STAGE0" -emit header -o "$WORK/stage0.h" "$FIXTURE"
ELISA_STAGE1_BIN="$STAGE1" "$ROOT/scripts/elisac_stage1.sh" \
  -emit header -o "$WORK/stage1.h" "$FIXTURE"
cmp "$WORK/stage0.h" "$WORK/stage1.h"
grep -q 'void (\*callback)(void \*arg0, int32_t arg1);' "$WORK/stage1.h"
cc -x c -fsyntax-only "$WORK/stage1.h"
c++ -x c++ -fsyntax-only "$WORK/stage1.h"
echo "header_function_pointer_smoke OK: stage0/stage1 C ABI headers agree"
