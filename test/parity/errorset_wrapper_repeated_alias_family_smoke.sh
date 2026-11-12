#!/usr/bin/env bash
# Repeated selections of one canonical error family must union across alias spellings.
# Both compilers must resolve the aliases and reject only the narrowed destination.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_repeated_alias_family.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
stage0_rows="$(printf '%s\n' "$stage0_output" | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: return type expects.*$#L\1#p')"
if [[ "$stage0_status" -eq 0 || "$stage0_rows" != 'L20' || $(printf '%s\n' "$stage0_output" | grep -cF "$FIXTURE:" || true) != 1 ]]; then
    printf 'Stage0 repeated-alias diagnostic differs:\n%s\n' "$stage0_output" >&2
    exit 1
fi
output="$("$RPT" < "$FIXTURE")"
if ! grep -q '^D 1$' <<< "$output" || ! grep -q '^[[:space:]]*L20 return type expects' <<< "$output"; then
    echo "EWR repeated-alias smoke expected one missing-Zed diagnostic at L20:\n$output" >&2
    exit 1
fi

echo "EWR repeated-alias smoke OK: one canonical family is unioned across aliases"
