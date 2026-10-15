#!/usr/bin/env bash
# Qualification requires actual compilation and execution; declines/crashes fail.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:?set ELISACORE_BIN to the qualified stage0 product}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-packed-qualified-is.XXXXXX")"
qualified=0
cleanup() {
    status=$?
    trap - EXIT
    if [[ "$status" == 0 && "$qualified" == 1 ]]; then
        rm -rf "$WORK"
    else
        echo "packed qualified Is evidence retained: $WORK (exit=$status)" >&2
    fi
    return "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
# Cross-root semantics are still provisional until the oracle has been inspected.
# Set this to its reviewed semantic diagnostic text; arbitrary backend declines
# are not evidence that the language rejects a cross-root pattern.
SEMANTIC_DIAGNOSTIC="${ELISA_PACKED_IS_CROSS_ROOT_DIAGNOSTIC:-}"
{
    echo "source_head=$(git -C "$ROOT" rev-parse HEAD)"
    echo "stage0=$STAGE0"
    echo "stage1=$STAGE1"
    echo "runtime=$RUNTIME_OBJ"
    echo "cross_root_semantic_diagnostic=$SEMANTIC_DIAGNOSTIC"
} >"$WORK/tuple.txt"
for level in O0 O2; do
    for name in local_store_helper packed_qualified_is_sibling packed_qualified_is_module_collision; do
        source="$ROOT/test/repro/$name.elisa"
        [[ "$name" != local_store_helper ]] || source="$ROOT/test/differential/cases/local_store_helper.elisa"
        for stage in 0 1; do
            compiler="$STAGE0"; [[ "$stage" == 0 ]] || compiler="$STAGE1"
            object="$WORK/$name-$level-$stage.o"
            ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" "$compiler" -emit obj "-$level" -o "$object" "$source" >"$WORK/$name-$level-$stage.log" 2>&1
            executable="$WORK/$name-$level-$stage"
            cc -fno-builtin "$object" "$RUNTIME_OBJ" "$ROOT/scripts/pymodule_runtime_fallback.c" "$ROOT/test/parity/profile_hooks.c" -o "$executable" >"$WORK/$name-$level-$stage.link.log" 2>&1
            "$executable" >"$WORK/$name-$level-$stage.run.log" 2>&1
        done
    done
    for stage in 0 1; do
        compiler="$STAGE0"; [[ "$stage" == 0 ]] || compiler="$STAGE1"
        object="$WORK/cross-root-$level-$stage.o"
        log="$WORK/cross-root-$level-$stage.log"
        set +e
        ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" "$compiler" -emit obj "-$level" -o "$object" "$ROOT/test/repro/packed_qualified_is_cross_root.neg.elisa" >"$log" 2>&1
        status=$?
        set -e
        [[ "$status" -gt 0 && "$status" -lt 128 && ! -e "$object" ]] || { echo "cross-root rejection inconclusive/failed: exit=$status" >&2; cat "$log" >&2; exit 1; }
        if rg -qi 'segmentation|bus error|stack overflow|runtime error:|out of memory|panic:|panic at|abort trap' "$log"; then
            echo 'cross-root rejection inconclusive: compiler runtime failure' >&2; cat "$log" >&2; exit 1
        fi
        # Refuse to classify generic backend coverage or syntax/file failures as
        # semantic root compatibility evidence, even with a structured error label.
        if rg -qi 'backend could not|backend decline|declined [0-9]|syntax error|could not open|cannot open|LLVM ERROR' "$log"; then
            echo 'cross-root rejection inconclusive: non-semantic compiler failure' >&2; cat "$log" >&2; exit 2
        fi
        if [[ -z "$SEMANTIC_DIAGNOSTIC" ]]; then
            echo 'cross-root semantics provisional: inspect retained Stage0 diagnostic and set ELISA_PACKED_IS_CROSS_ROOT_DIAGNOSTIC to its reviewed semantic text' >&2
            cat "$log" >&2
            exit 2
        fi
        rg -Fq -- "$SEMANTIC_DIAGNOSTIC" "$log" || { echo 'missing oracle-validated semantic rejection diagnostic' >&2; cat "$log" >&2; exit 1; }
    done
done
qualified=1
echo 'qualified packed Is O0/O2: local stores, sibling false, module identity and cross-root rejection PASS'
