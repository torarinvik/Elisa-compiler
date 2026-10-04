#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:?Set ELISACORE_BIN to the fresh Stage0 compiler}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/packed-bootstrap-pattern.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT INT TERM HUP
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$ROOT/test/parity/run_timeout.sh"
link_flags=()
[[ "$(uname -s)" != Darwin ]] || link_flags=(-Wl,-dead_strip)
for level in -O0 -O2; do
    for fixture in packed_payloadless_or_statement packed_nested_value_match; do
        for compiler in "$STAGE0" "$STAGE1"; do
            "$compiler" -emit obj "$level" -o "$WORK/probe.o" "$ROOT/test/repro/$fixture.elisa" > "$WORK/compile.log" 2>&1 || { cat "$WORK/compile.log" >&2; exit 1; }
            runtime_args=("$ROOT/build/runtime/elisacore_runtime.o")
            clang "${link_flags[@]}" "$WORK/probe.o" "${runtime_args[@]}" "$ROOT/test/parity/profile_hooks.c" -o "$WORK/probe" > "$WORK/link.log" 2>&1 || { cat "$WORK/link.log" >&2; exit 1; }
            result=0
            elisa_run_timeout 20 "$WORK/probe" || result=$?
            [[ "$result" == 42 ]] || { echo "$fixture $level $compiler returned $result, expected 42" >&2; exit 1; }
        done
    done
done
echo 'packed bootstrap pattern smoke OK: both payloadless alternatives, nested binders, and mismatching tags'
