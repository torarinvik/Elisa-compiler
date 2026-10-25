#!/usr/bin/env bash
# A nested import marker must select its enclosing condition in the condition's module.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
python3 "$REPO_ROOT/test/proofs/check_errorset_wrapper_return_lexical_module.py"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
  echo "errorset wrapper static-if lexical-module smoke FAIL: $1" >&2
  exit 1
}

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_static_if_lexical_module.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the active ProviderA family despite the mismatched return set"
grep -q 'return type expects' <<< "$stage0_output" \
  || fail "Stage0 did not report the active nested provider family: $stage0_output"

stage1_output="$("$RPT" < "$FIXTURE")"
grep -q 'cannot propagate.*FaultA' <<< "$stage1_output" \
  || fail "Stage1 did not select App::ProviderA through the nested Client import: $stage1_output"
[[ $(grep -cF 'cannot propagate' <<< "$stage1_output") == 1 ]] \
  || fail "Stage1 emitted an unexpected ErrorSet diagnostic: $stage1_output"

echo "errorset wrapper static-if lexical-module smoke OK"
