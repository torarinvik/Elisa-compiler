#!/usr/bin/env bash
# Regression for the stage1 machine-expression lifetime bug.
#
# `append_machine_state_block` returns a nested darray of synthesized AST statements. The old
# stage1 implementation built that darray in the helper's short-lived auto region and then
# shallow-copied its header into the caller's `state_blocks`; the helper freed the backing before
# the caller consumed it. The fix is a region-polymorphic darray return, so the caller's auto
# region owns the backing. Compile and RUN the same nested-resource machine through both stages.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
FALLBACK="$ROOT/scripts/pymodule_runtime_fallback.c"
FIXTURE="$ROOT/test/repro/machine_nested_return.elisa"

echo "backend_machine_region_return_smoke: stage1=$STAGE1 stage0=$STAGE0"
[ -x "$STAGE1" ] || { echo "backend_machine_region_return_smoke SKIP: no stage1 seed ($STAGE1)"; exit 0; }
[ -x "$STAGE0" ] || { echo "backend_machine_region_return_smoke SKIP: no stage0 compiler ($STAGE0)"; exit 0; }
[ -f "$RUNTIME_OBJ" ] || { echo "backend_machine_region_return_smoke SKIP: no runtime object ($RUNTIME_OBJ)"; exit 0; }
[ -f "$FIXTURE" ] || { echo "backend_machine_region_return_smoke FAIL: missing fixture ($FIXTURE)" >&2; exit 1; }
command -v clang >/dev/null 2>&1 || { echo "backend_machine_region_return_smoke SKIP: no clang"; exit 0; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/backend-machine-region-return.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

compile_and_run() {
    local label="$1" compiler="$2" obj="$WORK/$1.o" exe="$WORK/$1" log="$WORK/$1.log" rc
    if ! "$compiler" -emit obj -O0 -o "$obj" "$FIXTURE" >"$log" 2>&1; then
        cat "$log" >&2
        echo "backend_machine_region_return_smoke FAIL: $label compiler rejected fixture" >&2
        exit 1
    fi
    [ -s "$obj" ] || { echo "backend_machine_region_return_smoke FAIL: $label emitted no object" >&2; exit 1; }
    if ! clang -fno-builtin -Wl,-dead_strip -o "$exe" "$obj" "$RUNTIME_OBJ" "$FALLBACK" >>"$log" 2>&1; then
        cat "$log" >&2
        echo "backend_machine_region_return_smoke FAIL: $label object did not link" >&2
        exit 1
    fi
    set +e
    "$exe"
    rc=$?
    set -e
    if [ "$rc" -ne 4 ]; then
        cat "$log" >&2
        echo "backend_machine_region_return_smoke FAIL: $label ran with exit $rc (want 4)" >&2
        exit 1
    fi
    echo "  $label: nested machine region return ran with exit 4"
}

compile_and_run stage1 "$STAGE1"
compile_and_run stage0 "$STAGE0"
echo "backend_machine_region_return_smoke OK: stage0/stage1 machine-expression lifetime parity"
