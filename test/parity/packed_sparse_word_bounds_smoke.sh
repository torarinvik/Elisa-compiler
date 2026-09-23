#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
source "$ROOT/test/parity/run_timeout.sh"

[[ -x "$STAGE1" ]] || { echo "packed sparse word bounds smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
[[ -x "$STAGE0" ]] || { echo "packed sparse word bounds smoke: missing stage0 compiler: $STAGE0" >&2; exit 2; }
command -v clang >/dev/null 2>&1 || { echo "packed sparse word bounds smoke: clang is required to link the stage0 runtime" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-packed-sparse-bounds.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

for case_name in valid oob; do
    source_file="$ROOT/test/parity/fixtures/packed_sparse_word_bounds_${case_name}.elisa"
    executable="$WORK/$case_name"
    stage0_archive="$WORK/$case_name.stage0.a"
    stage0_executable="$WORK/$case_name.stage0"
    log="$WORK/$case_name.log"
    if ! "$STAGE1" -emit exe -o "$executable" "$source_file" >"$log" 2>&1; then
        echo "packed sparse word bounds smoke: failed to compile $case_name case" >&2
        cat "$log" >&2
        exit 1
    fi
    if ! "$STAGE0" -emit c-archive -o "$stage0_archive" "$source_file" >"$log" 2>&1; then
        echo "packed sparse word bounds smoke: stage0 failed to compile $case_name case" >&2
        cat "$log" >&2
        exit 1
    fi
    if ! clang -o "$stage0_executable" "$stage0_archive" >"$log" 2>&1; then
        echo "packed sparse word bounds smoke: failed to link stage0 $case_name case" >&2
        cat "$log" >&2
        exit 1
    fi
done

set +e
elisa_run_timeout 10 "$WORK/valid" >"$WORK/valid.run.log" 2>&1
valid_status=$?
elisa_run_timeout 10 "$WORK/oob" >"$WORK/oob.run.log" 2>&1
oob_status=$?
elisa_run_timeout 10 "$WORK/valid.stage0" >"$WORK/valid.stage0.run.log" 2>&1
stage0_valid_status=$?
elisa_run_timeout 10 "$WORK/oob.stage0" >"$WORK/oob.stage0.run.log" 2>&1
stage0_oob_status=$?
set -e

[[ "$valid_status" -eq 0 ]] || { echo "packed sparse word bounds smoke: valid final word failed (status $valid_status)" >&2; exit 1; }
[[ "$oob_status" -ne 0 ]] || { echo "packed sparse word bounds smoke: out-of-range row read returned normally" >&2; exit 1; }
[[ "$stage0_valid_status" -eq 0 ]] || { echo "packed sparse word bounds smoke: stage0 valid final word failed (status $stage0_valid_status)" >&2; exit 1; }
[[ "$stage0_oob_status" -ne 0 ]] || { echo "packed sparse word bounds smoke: stage0 out-of-range row read returned normally" >&2; exit 1; }

echo "packed sparse word bounds smoke OK: stage0/stage1 valid row reads; out-of-range reads trap"
