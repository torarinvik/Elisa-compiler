#!/usr/bin/env bash
# EWR must match Core when a public wrapper is behind a private module path.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_private_module.elisa"
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1 || true)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: (cannot propagate|return type expects).*$#L\1#p' \
    | LC_ALL=C sort)"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"

grep -qF 'is private to module' <<< "$stage0_output" || {
    printf 'Stage0 did not reject the private module path:\n%s\n' "$stage0_output" >&2
    exit 1
}
grep -qF 'is private to module' <<< "$stage1_output" || {
    printf 'Stage1 did not reject the private module path:\n%s\n' "$stage1_output" >&2
    exit 1
}
grep -qx 'L18' <<< "$stage0_rows" || {
    printf 'Stage0 owning-module control no longer has the expected mismatch:\n%s\n' "$stage0_output" >&2
    exit 1
}
grep -qx 'L18' <<< "$stage1_rows" || {
    printf 'Stage1 failed to retain the owning-module mismatch:\n%s\n' "$stage1_output" >&2
    exit 1
}
if [[ "$stage1_rows" != "$stage0_rows" ]]; then
    printf 'EWR private-module diagnostics differ from Core:\nStage0: %s\nStage1: %s\n' "$stage0_rows" "$stage1_rows" >&2
    exit 1
fi

echo "errorset wrapper private-module smoke OK: module-path privacy matches Core"
