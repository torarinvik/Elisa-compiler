#!/usr/bin/env bash
# EWR must preserve a public same-name overload after a private sibling when #line
# makes their logical declaration lines collide.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
python3 "$REPO_ROOT/test/proofs/check_errorset_wrapper_return_source.py" --source-only
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_public_sibling_same_line.elisa"
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1 || true)"
stage1_output="$("$RPT" < "$FIXTURE")"

grep -qF 'is private to module' <<< "$stage0_output" || {
    printf 'Stage0 did not keep the private overload private:\n%s\n' "$stage0_output" >&2
    exit 1
}
grep -qF 'is private to module' <<< "$stage1_output" || {
    printf 'Stage1 did not keep the private overload private:\n%s\n' "$stage1_output" >&2
    exit 1
}
[[ "$(grep -c 'is private to module' <<< "$stage0_output")" -eq 1 ]] || {
    printf 'Stage0 hid the public same-name sibling:\n%s\n' "$stage0_output" >&2
    exit 1
}
[[ "$(grep -c 'is private to module' <<< "$stage1_output")" -eq 1 ]] || {
    printf 'Stage1 hid the public same-name sibling:\n%s\n' "$stage1_output" >&2
    exit 1
}
if grep -qE 'cannot propagate|return type expects' <<< "$stage1_output"; then
    printf 'Stage1 lost the public infallible candidate while checking the wrapper:\n%s\n' "$stage1_output" >&2
    exit 1
fi

echo "errorset wrapper public sibling smoke OK: #line collision preserves public candidate visibility"
