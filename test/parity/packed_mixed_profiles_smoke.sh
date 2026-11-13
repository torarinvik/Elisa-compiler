#!/usr/bin/env bash
# Both stores must remain usable when their enums select different packed layouts.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$ROOT/test/parity/run_timeout.sh"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-packed-mixed.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
FIXTURE="$ROOT/test/parity/fixtures/packed_mixed_profiles.elisa"
"$STAGE1" -emit llvm -O0 -o "$WORK/mixed.ll" "$FIXTURE"
grep -q 'call.*@ctx_packed_store_state_new_with_prefix_words' "$WORK/mixed.ll"
grep -q 'call.*@ctx_packed_store_state_new_variant_sparse' "$WORK/mixed.ll"
grep -q 'call.*@ctx_packed_store_read_index_word' "$WORK/mixed.ll"
grep -q 'call.*@ctx_packed_store_read_variant_sparse_word' "$WORK/mixed.ll"
"$STAGE1" -emit llvm -O0 -o "$WORK/side.ll" "$ROOT/test/parity/fixtures/packed_mixed_profile_side_common.elisa"
grep -q 'call.*@ctx_packed_store_state_new_with_prefix_and_side_words' "$WORK/side.ll"
for case_name in profiles side_common inline_common module_common three_modes; do
    FIXTURE="$ROOT/test/parity/fixtures/packed_mixed_profile_$case_name.elisa"
    expected=47
    if [[ "$case_name" == profiles ]]; then
        FIXTURE="$ROOT/test/parity/fixtures/packed_mixed_profiles.elisa"
        expected=42
    fi
    [[ "$case_name" == module_common ]] && expected=0
    [[ "$case_name" == three_modes ]] && expected=84
    "$STAGE0" -emit packed "$FIXTURE" > "$WORK/stage0.report"
    "$STAGE1" -emit packed -o "$WORK/stage1.report" "$FIXTURE"
    diff -u "$WORK/stage0.report" "$WORK/stage1.report"
    for level in 0 2; do
        "$STAGE0" -emit c-archive "-O$level" -o "$WORK/stage0.a" "$FIXTURE"
        clang -o "$WORK/stage0" "$WORK/stage0.a"
        "$STAGE1" -emit exe "-O$level" -o "$WORK/stage1" "$FIXTURE"
        for stage in stage0 stage1; do
            set +e
            elisa_run_timeout 10 "$WORK/$stage"
            status=$?
            set -e
            if [[ "$status" -ne "$expected" ]]; then
                echo "mixed packed profiles: $case_name $stage -O$level returned $status, expected $expected" >&2
                exit 1
            fi
        done
    done
done
for nested_source in "$ROOT/test/repro/packed_nested_value_match.elisa" "$ROOT/test/parity/fixtures/packed_deep_nested_patterns.elisa"; do
  for profile in canonical retained_reads build_heavy; do
    sed "s/@packed_profile(build_heavy)/@packed_profile($profile)/" "$nested_source" > "$WORK/nested.elisa"
    for level in 0 2; do
        "$STAGE0" -emit c-archive "-O$level" -o "$WORK/stage0.a" "$WORK/nested.elisa"
        clang -o "$WORK/stage0" "$WORK/stage0.a"
        "$STAGE1" -emit exe "-O$level" -o "$WORK/stage1" "$WORK/nested.elisa"
        for stage in stage0 stage1; do
            set +e
            elisa_run_timeout 10 "$WORK/$stage"
            status=$?
            set -e
            if [[ "$status" -ne 42 ]]; then
                echo "nested packed patterns: $profile $stage -O$level returned $status, expected 42" >&2
                exit 1
            fi
        done
    done
  done
done
echo "mixed packed profiles: matching reports and execution at O0 and O2"
