#!/usr/bin/env bash
# Stage0/Stage1 lifetime regression: a view-returning call must retain the short-lived
# backing region among its source arguments, even when that source is the second argument.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac-stage0}"
SOURCE="$ROOT/test/repro/sview_region_multiple_arguments.elisa"

fail() { echo "sview multi-argument region smoke FAIL: $1" >&2; exit 1; }
[[ -x "$STAGE1" ]] || fail "missing Stage1 compiler: $STAGE1"
[[ -x "$STAGE0" ]] || fail "missing Stage0 compiler: $STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-sview-region.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

for stage in stage0 stage1; do
    if [[ "$stage" == stage0 ]]; then compiler="$STAGE0"; else compiler="$STAGE1"; fi
    if "$compiler" -emit llvm -O0 -o "$WORK/$stage.ll" "$SOURCE" >"$WORK/$stage.log" 2>&1; then
        fail "$stage accepted a shorter-lived second-argument view stored in the outer region"
    fi
    grep -Fq 'value in region "inner" is stored into longer-lived region "outer"' "$WORK/$stage.log" \
        || fail "$stage rejection did not identify the inner-to-outer lifetime escape: $(tail -n 8 "$WORK/$stage.log")"
done

echo "sview multi-argument region smoke OK: Stage0/Stage1 retain the short-lived returned argument"
