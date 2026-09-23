#!/usr/bin/env bash
# Stage1 lifetime regression: a view-returning call must retain the deepest lifetime of
# every candidate source argument, independent of argument order.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac-stage0}"
SOURCE="$ROOT/test/repro/sview_region_multiple_arguments.elisa"

fail() { echo "sview multi-argument region smoke FAIL: $1" >&2; exit 1; }
[[ -x "$STAGE1" ]] || fail "missing Stage1 compiler: $STAGE1"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-sview-region.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

if "$STAGE1" -emit llvm -O0 -o "$WORK/rejected.ll" "$SOURCE" >"$WORK/log" 2>&1; then
    fail "Stage1 accepted a shorter-lived second-argument view stored in the outer region"
fi
grep -Fq 'value in region "inner" is stored into longer-lived region "outer"' "$WORK/log" \
    || fail "rejection did not identify the inner-to-outer lifetime escape: $(tail -n 8 "$WORK/log")"

echo "sview multi-argument region smoke OK: deepest argument lifetime is retained"
