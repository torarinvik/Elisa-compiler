#!/usr/bin/env bash
# Verify fold scope and the fixed-width floating-point reduction tree on both compilers.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/scripts/platform.sh"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
work="$(mktemp -d "${TMPDIR:-/tmp}/elisa-fold-execution.XXXXXX")"
trap 'rm -rf "$work"' EXIT INT TERM HUP
runtime="${ELISA_RUNTIME_OBJ:-$REPO_ROOT/build/runtime/elisacore_runtime.o}"
fixture="$REPO_ROOT/test/fixtures/comprehensions/fold_reduction.elisa"
for compiler in stage0 stage1; do
    for opt in -O0 -O2; do
        output="$work/$compiler-$opt"
        if [[ "$compiler" == stage0 ]]; then
            "$ELISACORE_BIN" "$opt" -emit obj -o "$output.o" "$fixture" >"$output.log" 2>&1
        else
            bash "$REPO_ROOT/scripts/elisac_stage1.sh" "$opt" -emit obj -o "$output.o" "$fixture" >"$output.log" 2>&1
        fi
        clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS "$output.o" "$runtime" "$REPO_ROOT/test/parity/profile_hooks.c" -o "$output" >>"$output.log" 2>&1
        "$output" || { rc=$?; printf '%s %s fold fixture exited %s\n' "$compiler" "$opt" "$rc" >&2; exit 1; }
    done
done
printf 'fold execution parity OK at -O0 and -O2\n'
