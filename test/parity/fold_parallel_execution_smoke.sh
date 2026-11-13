#!/usr/bin/env bash
# Exercise the parallel fold's map/reduce callbacks with the full source runtime.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/scripts/platform.sh"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
work="$(mktemp -d "${TMPDIR:-/tmp}/elisa-fold-parallel.XXXXXX")"
trap 'rm -rf "$work"' EXIT INT TERM HUP
bash "$REPO_ROOT/scripts/write_profiler_hook_fallbacks.sh" --host-callbacks > "$work/hooks.c"
link_flags=()
[[ "$(uname -s)" == Darwin ]] && link_flags=(-Wl,-undefined,dynamic_lookup)
for compiler in stage0 stage1; do
    for opt in -O0 -O2; do
        output="$work/$compiler-$opt"
        if [[ "$compiler" == stage0 ]]; then
            "$ELISACORE_BIN" "$opt" -emit obj -o "$output.o" "$REPO_ROOT/test/fixtures/fold_parallel.elisa" >"$output.log" 2>&1
        else
            bash "$REPO_ROOT/scripts/elisac_stage1.sh" "$opt" -emit obj -o "$output.o" "$REPO_ROOT/test/fixtures/fold_parallel.elisa" >"$output.log" 2>&1
        fi
        clang -fno-builtin $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS "${link_flags[@]}" "$output.o" "$work/hooks.c" -o "$output" >>"$output.log" 2>&1
        "$output" || { rc=$?; printf '%s %s parallel fold exited %s\n' "$compiler" "$opt" "$rc" >&2; exit 1; }
    done
done
printf 'parallel fold execution parity OK at -O0 and -O2\n'
