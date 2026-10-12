#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$BIN"
[[ -x "$BIN" ]] || { echo "backend_name_chain_smoke FAIL: missing Stage1 product $BIN" >&2; exit 1; }
[[ -s "$RUNTIME" ]] || { echo "backend_name_chain_smoke FAIL: missing runtime object $RUNTIME" >&2; exit 1; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/backend-name-chain.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ELISA_STAGE1_BIN="$BIN" ELISA_RUNTIME_OBJ="$RUNTIME" \
  bash "$ROOT/scripts/elisac_stage1.sh" -emit exe -O0 \
    -o "$WORK/backend_name_chain_smoke" "$ROOT/test/parity/backend_name_chain_smoke.elisa"
"$WORK/backend_name_chain_smoke"

echo "backend_name_chain_smoke OK"
