#!/usr/bin/env bash
# Component string-view equality must call the freestanding runtime helper,
# never introduce an unsupported `env::memcmp` import.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WIT="$ROOT/test/fixtures/wasm/component_bounded_sview.wit"
SOURCE="$ROOT/test/fixtures/wasm/component_bounded_sview.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-component-sview-equality.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
[[ -x "$STAGE1" ]] || { echo "component sview equality smoke FAIL: stage1 unavailable" >&2; exit 1; }

ELISA_WASM_NO_CACHE=1 \
ELISA_COMPILER_ROOT="$ROOT" \
ELISA_STAGE1_BIN="$STAGE1" \
  bash "$ROOT/scripts/elisac_stage1.sh" \
    -emit wasm \
    --wasm-only \
    --component-type "$WIT" \
    -o "$WORK/component.wasm" \
    "$SOURCE" >"$WORK/build.log" 2>&1 || {
      cat "$WORK/build.log" >&2
      exit 1
    }

[[ -s "$WORK/component.wasm" ]] || { echo "component output is empty" >&2; exit 1; }
echo "component sview equality smoke OK: counted equality validates without env::memcmp"
