#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$BIN" || exit $?
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
FIXTURE="$ROOT/test/repro/index_overload_generic_field.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$BIN" ]] || { echo "index_overload_generic_field_smoke FAIL: missing stage1 product $BIN" >&2; exit 1; }
[[ -f "$RUNTIME" ]] || { echo "index_overload_generic_field_smoke FAIL: missing runtime object $RUNTIME" >&2; exit 1; }

ELISA_STAGE1_BIN="$BIN" ELISA_RUNTIME_OBJ="$RUNTIME" \
  bash "$WRAPPER" -emit exe -O0 -o "$WORK/index_overload_generic_field" "$FIXTURE"
"$WORK/index_overload_generic_field"

echo "index_overload_generic_field_smoke OK"
