#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/header_function_pointer.elisa"

[[ -x "$STAGE0" ]] || { echo "header_function_pointer_smoke SKIP: no stage0 at $STAGE0"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "header_function_pointer_smoke SKIP: no stage1 at $STAGE1"; exit 0; }

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
