#!/usr/bin/env bash
# An exact root error-set name takes precedence over a same-suffix relative type.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
FIXTURE="$REPO_ROOT/test/repro/catch_relative_family_root_precedence.elisa"
set +e
stage0="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
status=$?
set -e
[[ "$status" -ne 0 && "$stage0" == *'missing Provider.Fault.RootOnly'* && "$stage0" == *'catch arm "Provider.Fault.LocalOnly" does not match'* ]] || {
    printf 'Stage0 did not select the root error family:\n%s\n' "$stage0" >&2
    exit 1
}
stage1="$("$RPT" < "$FIXTURE")"
[[ "$stage1" == *$'P 0\nD 2\n'* && "$stage1" == *'missing Fault.RootOnly'* && "$stage1" == *'does not match the caught call'* ]] || {
    printf 'Stage1 did not select the root error family:\n%s\n' "$stage1" >&2
    exit 1
}
echo 'catch root error-family precedence smoke OK'
