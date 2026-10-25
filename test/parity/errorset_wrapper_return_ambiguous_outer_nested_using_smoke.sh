#!/usr/bin/env bash
# Ambiguous wildcard callback names must not feed EWR an arbitrary ErrorSet family.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "errorset wrapper ambiguous-using smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_ambiguous_outer_nested_using.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted two distinct wildcard callback targets"
grep -qF 'ambiguous reference "origin"' <<< "$stage0_output" \
    || fail "Stage0 did not report the ambiguous callback name: $stage0_output"
if grep -qF 'cannot propagate' <<< "$stage0_output"; then
    fail "Stage0 emitted an unrelated propagation cascade: $stage0_output"
fi

stage1_output="$("$RPT" < "$FIXTURE")"
grep -qF 'ambiguous reference "origin"' <<< "$stage1_output" \
    || fail "Stage1 did not report the ambiguous callback name: $stage1_output"
if grep -qF 'cannot propagate' <<< "$stage1_output"; then
    fail "Stage1 let one wildcard target supply an arbitrary ErrorSet to EWR: $stage1_output"
fi

echo "errorset wrapper ambiguous-using smoke OK: EWR declines ambiguous callbacks"
