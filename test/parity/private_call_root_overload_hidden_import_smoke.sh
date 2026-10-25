#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "private call root/local-overload visibility smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/private_call_root_overload_hidden_import.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_rc=$?
set -e
[[ "$stage0_rc" == 0 ]] \
    || fail "Stage0 rejected a visible root overload winner: $stage0_output"
if grep -qF 'is private to module' <<< "$stage0_output"; then
    fail "Stage0 reported access to a private overload that loses to a root candidate: $stage0_output"
fi

stage1_output="$("$RPT" < "$FIXTURE")"
grep -q '^P 0$' <<< "$stage1_output" \
    || fail "Stage1 returned a nonzero process status: $stage1_output"
if grep -qF 'is private to module' <<< "$stage1_output"; then
    fail "Stage1 reported access to a private overload that loses to a root candidate: $stage1_output"
fi

echo "private call root/local-overload visibility smoke OK"
