#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
source "$ROOT/test/parity/run_timeout.sh"

[[ -x "$STAGE1" ]] || { echo "JSON opaque DOM smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
[[ -x "$STAGE0" ]] || { echo "JSON opaque DOM smoke: missing stage0 compiler: $STAGE0" >&2; exit 2; }
command -v clang >/dev/null 2>&1 || { echo "JSON opaque DOM smoke: clang is required to link the stage0 runtime" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-json-opaque.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

POSITIVE="$ROOT/test/repro/json_safe_api.elisa"

for optimization in 0 2; do
    stage1="$WORK/stage1-O$optimization"
    stage0_archive="$WORK/stage0-O$optimization.a"
    stage0="$WORK/stage0-O$optimization"

    if ! "$STAGE1" -emit exe "-O$optimization" -o "$stage1" "$POSITIVE" >"$stage1.compile.log" 2>&1; then
        echo "JSON opaque DOM smoke: stage1 failed to compile safe API at O$optimization" >&2
        cat "$stage1.compile.log" >&2
        exit 1
    fi
    if ! "$STAGE0" -emit c-archive "-O$optimization" -o "$stage0_archive" "$POSITIVE" >"$stage0.compile.log" 2>&1; then
        echo "JSON opaque DOM smoke: stage0 failed to compile safe API at O$optimization" >&2
        cat "$stage0.compile.log" >&2
        exit 1
    fi
    if ! clang -Wl,-dead_strip -o "$stage0" "$stage0_archive" >"$stage0.link.log" 2>&1; then
        echo "JSON opaque DOM smoke: failed to link stage0 at O$optimization" >&2
        cat "$stage0.link.log" >&2
        exit 1
    fi

    for executable in "$stage1" "$stage0"; do
        log="$executable.run.log"
        set +e
        elisa_run_timeout 10 "$executable" >"$log" 2>&1
        run_status=$?
        set -e
        [[ "$run_status" -eq 0 ]] || { echo "JSON opaque DOM smoke: valid parse/access/write failed (status $run_status): $executable" >&2; cat "$log" >&2; exit 1; }
    done
done

for fixture in json_forge_private json_raw_pointer_helper; do
    source="$ROOT/test/repro/$fixture.elisa"
    for stage in stage0 stage1; do
        compiler="$STAGE0"
        if [[ "$stage" == stage1 ]]; then compiler="$STAGE1"; fi
        log="$WORK/$stage-$fixture.log"
        if "$compiler" -emit llvm -o "$WORK/$stage-$fixture.ll" "$source" >"$log" 2>&1; then
            echo "JSON opaque DOM smoke: $stage accepted forbidden raw DOM access in $fixture" >&2
            exit 1
        fi
        rg -Fq 'is private to module' "$log" || { echo "JSON opaque DOM smoke: $stage rejected $fixture without the expected privacy diagnostic" >&2; cat "$log" >&2; exit 1; }
    done
done

echo "JSON opaque DOM smoke OK: parser-produced values remain usable; forged variants and raw pointer helpers are private on Stage0/Stage1 at O0/O2"
