#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac-stage0}"
FIXTURE="$ROOT/test/parity/fixtures/darray_sview_empty_backing.elisa"

fail() { echo "darray sview backing smoke FAIL: $1" >&2; exit 1; }
[[ -x "$STAGE0" ]] || fail "missing Stage0 compiler: $STAGE0"
[[ -x "$STAGE1" ]] || fail "missing Stage1 compiler: $STAGE1"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-sview-backing.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

for stage in stage0 stage1; do
    compiler="$STAGE0"
    [[ "$stage" != stage1 ]] || compiler="$STAGE1"
    executable="$WORK/$stage"
    log="$WORK/$stage.log"
    if [[ "$stage" == stage0 ]]; then
        object="$WORK/$stage.o"
        "$compiler" -emit obj -O0 -o "$object" "$FIXTURE" >"$log" 2>&1 \
            || fail "$stage rejected borrowed or empty sview construction: $(tail -n 12 "$log")"
        clang -o "$executable" "$object" "$ROOT/test/parity/support/arena_free_noop.c" >>"$log" 2>&1 \
            || fail "$stage object did not link: $(tail -n 12 "$log")"
    else
        "$compiler" -emit exe -O0 -o "$executable" "$FIXTURE" >"$log" 2>&1 \
            || fail "$stage rejected borrowed or empty sview construction: $(tail -n 12 "$log")"
    fi
    set +e
    "$executable"
    status=$?
    set -e
    [[ "$status" -eq 42 ]] \
        || fail "$stage returned $status; expected a readable NUL backing for an empty darray view"
done

echo "darray sview backing smoke OK: borrowed receivers lower and empty views retain valid backing"
