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
    echo "try static type-alias branch smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_noncall_static_type_alias_branch.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
set -e
grep -qF 'try requires a fallible expression' <<< "$stage0_output" \
    || fail "Stage0 lost the selected integer alias's nonfallible fact: $stage0_output"

stage1_output="$("$RPT" < "$FIXTURE")"
grep -qF 'try requires a fallible expression' <<< "$stage1_output" \
    || fail "Stage1 lost the selected integer alias's nonfallible fact: $stage1_output"

echo "try static type-alias branch smoke OK"
