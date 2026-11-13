#!/usr/bin/env bash
# A sibling-only private alias must not enter another module’s overload set.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "cross-module Try private-winner smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_overload_cross_module_private_cached_winner.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_rc=$?
set -e
[[ "$stage0_rc" -ne 0 ]] || fail "Stage0 accepted the mismatched generic error family"
stage1_output="$("$RPT" < "$FIXTURE")"
grep -q '^D 4$' <<< "$stage1_output" || fail "Stage1 reported an unexpected diagnostic count: $stage1_output"
for line in 30 34 37 41; do
    grep -Eq ":${line}:[0-9]+[^:]*: cannot propagate LibA\.GenericFault from a function returning App\.Destination" <<< "$stage0_output" \
        || fail "Stage0 missed the public generic family at line $line: $stage0_output"
    grep -qF "L$line cannot propagate GenericFault from a function returning Destination" <<< "$stage1_output" \
        || fail "Stage1 missed the public generic family at line $line: $stage1_output"
done
if grep -qE 'is private to module|try requires a fallible expression' <<< "$stage0_output$stage1_output"; then
    fail "A sibling-only private import affected an unrelated caller: $stage0_output $stage1_output"
fi

echo "cross-module Try sibling-private-import smoke OK"
