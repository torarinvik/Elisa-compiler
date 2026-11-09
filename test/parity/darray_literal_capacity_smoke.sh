#!/usr/bin/env bash
# Literal capacity is observable; frame-backed literals must not exhaust the arena.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/platform.sh"
source "$ROOT/test/parity/run_timeout.sh"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-darray-capacity.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
for level in 0 2; do
    for compiler in "$STAGE0" "$STAGE1"; do
        for fixture in darray_literal_capacity_parity amm_return_after_arena_free; do
            "$compiler" -emit obj "-O$level" -o "$WORK/case.o" "$ROOT/test/differential/cases/$fixture.elisa" >"$WORK/compile.log" 2>&1 || { cat "$WORK/compile.log" >&2; exit 1; }
            clang $ELISA_LINK_EXE_FLAGS -o "$WORK/case" "$WORK/case.o" "${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}" "$ROOT/test/parity/profile_hooks.c" >"$WORK/link.log" 2>&1 || { cat "$WORK/link.log" >&2; exit 1; }
            elisa_run_timeout 10 "$WORK/case" || { echo "$fixture failed at -O$level with $compiler" >&2; exit 1; }
        done
    done
done
"$STAGE1" -emit llvm -O0 -o "$WORK/stack.ll" "$ROOT/test/differential/cases/amm_return_after_arena_free.elisa"
grep -q 'arena_init_stack_block' "$WORK/stack.ll" || { echo 'frame-block optimization was not exercised' >&2; exit 1; }
echo 'darray literal capacity and frame-backed arena parity OK'
