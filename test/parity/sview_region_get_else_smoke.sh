#!/usr/bin/env bash
# Stage0/Stage1 lifetime regression: unwrapping an optional view with a terminating
# GetElse recovery must preserve the success value's short-lived region provenance.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
SOURCE="$ROOT/test/repro/sview_region_get_else.neg.elisa"

fail() { echo "sview GetElse region smoke FAIL: $1" >&2; exit 1; }
[[ -x "$STAGE1" ]] || fail "missing Stage1 compiler: $STAGE1"
[[ -x "$STAGE0" ]] || fail "missing Stage0 compiler: $STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-sview-get-else.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

for stage in stage0 stage1; do
    if [[ "$stage" == stage0 ]]; then compiler="$STAGE0"; else compiler="$STAGE1"; fi
    if "$compiler" -emit llvm -O0 -o "$WORK/$stage.ll" "$SOURCE" >"$WORK/$stage.log" 2>&1; then
        fail "$stage accepted a short-lived view stored into the outer region through GetElse"
    fi
    grep -Fq 'value in region "inner" is stored into longer-lived region "outer"' "$WORK/$stage.log" \
        || fail "$stage rejection did not identify the inner-to-outer lifetime escape: $(tail -n 8 "$WORK/$stage.log")"
done

echo "sview GetElse region smoke OK: both stages retain success-value provenance"
