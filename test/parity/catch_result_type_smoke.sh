#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
RUNTIME="$ROOT/build/runtime/elisacore_runtime.o"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-catch-result.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$BIN" ]] || { echo "catch_result_type_smoke FAIL: missing stage1 product $BIN" >&2; exit 1; }
[[ -x "$WRAPPER" ]] || { echo "catch_result_type_smoke FAIL: missing wrapper $WRAPPER" >&2; exit 1; }
[[ -f "$RUNTIME" ]] || { echo "catch_result_type_smoke FAIL: missing runtime object $RUNTIME" >&2; exit 1; }

ELISA_STAGE1_BIN="$BIN" "$WRAPPER" -o "$WORK/catch.o" "$ROOT/test/repro/catch_result_type.elisa"
clang -Wl,-dead_strip -o "$WORK/catch" "$WORK/catch.o" "$RUNTIME"

set +e
"$WORK/catch"
got=$?
set -e
[[ "$got" -eq 84 ]] || { echo "catch_result_type_smoke FAIL: exit $got want 84" >&2; exit 1; }

echo "catch result type smoke OK: inline and stored struct payload catches returned i64 84"
