#!/usr/bin/env bash
# Fresh array overloads may discard argument provenance; borrow-carrying results may not.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:?Set ELISACORE_BIN to the fresh Stage0 compiler}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/owned-overload-storage.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT INT TERM HUP
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
for opt in -O0 -O2; do
    for mode in bare runtime; do
        for fixture in storage_dependency_owned_return_global.neg storage_dependency_owned_return.neg storage_dependency_owned_return_global.pos storage_dependency_owned_return.pos; do
            source="$ROOT/test/fixtures/diagnostics/$fixture.elisa"
            probe="$WORK/probe.elisa"
            if [[ "$mode" == runtime ]]; then
                printf 'include "%s/elisacore_std/elisacore_runtime.elisa"\n' "$ROOT" > "$probe"
                cat "$source" >> "$probe"
            else
                cp "$source" "$probe"
            fi
            status=0
            "$STAGE1" -emit obj "$opt" -o "$WORK/probe.o" "$probe" > "$WORK/check.log" 2>&1 || status=$?
            if [[ "$fixture" == *.neg ]]; then
                [[ "$status" == 0 ]] || { cat "$WORK/check.log" >&2; exit 1; }
                "$STAGE0" -emit obj "$opt" -o "$WORK/oracle.o" "$probe" > "$WORK/oracle.log" 2>&1 || { cat "$WORK/oracle.log" >&2; exit 1; }
            else
                [[ "$status" != 0 ]] || { echo "Unexpected acceptance: $opt $mode $fixture" >&2; exit 1; }
                grep -q 'storage dependency' "$WORK/check.log" || { cat "$WORK/check.log" >&2; exit 1; }
            fi
        done
    done
done
echo 'owned overload storage smoke OK: fresh results accepted, global/view payload dependencies retained'
