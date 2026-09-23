#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
source "$ROOT/test/parity/run_timeout.sh"

[[ -x "$STAGE1" ]] || { echo "arena runtime lifecycle smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
[[ -x "$STAGE0" ]] || { echo "arena runtime lifecycle smoke: missing stage0 compiler: $STAGE0" >&2; exit 2; }
command -v clang >/dev/null 2>&1 || { echo "arena runtime lifecycle smoke: clang is required to link the stage0 runtime" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-arena-lifecycle.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

for case_name in arena_lifetime_evidence arena_reuse_identity arena_rewind_lifecycle arena_tail_capacity arena_adopt_reuse_indices arena_free_hint_lifecycle; do
    source_file="$ROOT/test/repro/$case_name.elisa"
    stage1_executable="$WORK/$case_name.stage1"
    stage0_archive="$WORK/$case_name.stage0.a"
    stage0_executable="$WORK/$case_name.stage0"
    log="$WORK/$case_name.log"

    if ! "$STAGE1" -emit exe -O2 -o "$stage1_executable" "$source_file" >"$log" 2>&1; then
        echo "arena runtime lifecycle smoke: stage1 failed to compile $case_name" >&2
        cat "$log" >&2
        exit 1
    fi
    if ! "$STAGE0" -emit c-archive -O2 -o "$stage0_archive" "$source_file" >"$log" 2>&1; then
        echo "arena runtime lifecycle smoke: stage0 failed to compile $case_name" >&2
        cat "$log" >&2
        exit 1
    fi
    # The full arena source includes unused varargs entry points whose host macros
    # are not linkable functions. Keep those unrelated sections out of this fixture.
    if ! clang -Wl,-dead_strip -o "$stage0_executable" "$stage0_archive" >"$log" 2>&1; then
        echo "arena runtime lifecycle smoke: failed to link stage0 $case_name" >&2
        cat "$log" >&2
        exit 1
    fi

    if ! elisa_run_timeout 10 "$stage1_executable" >"$WORK/$case_name.stage1.run.log" 2>&1; then
        echo "arena runtime lifecycle smoke: $case_name failed on stage1" >&2
        cat "$WORK/$case_name.stage1.run.log" >&2
        exit 1
    fi
    if ! elisa_run_timeout 10 "$stage0_executable" >"$WORK/$case_name.stage0.run.log" 2>&1; then
        echo "arena runtime lifecycle smoke: $case_name failed on stage0" >&2
        cat "$WORK/$case_name.stage0.run.log" >&2
        exit 1
    fi
done

echo "arena runtime lifecycle smoke OK: adoption, trim, rewind, reuse, tail growth, and free-hint lifecycle pass on stage0/stage1"
