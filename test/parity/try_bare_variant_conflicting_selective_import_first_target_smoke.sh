#!/usr/bin/env bash
# Conflicting selective imports preserve Core's first bare-name target.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/try_bare_variant_conflicting_selective_import_first_target.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || {
  printf 'conflicting selective-import smoke expected the import conflict and one controlled Try mismatch:\n%s\n' "$stage0_output" >&2
  exit 1
}

grep -Eq ':18:[0-9]+(-[0-9]+)?: conflicting import.*"Expected"' <<< "$stage0_output" || {
  printf 'Stage0 did not report the conflicting Expected import:\n%s\n' "$stage0_output" >&2
  exit 1
}
stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+-[0-9]+: cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows='L29'

[[ "$stage0_rows" == "$expected_rows" ]] || {
  printf 'Stage0 conflicting-import diagnostics differ:\n%s\n%s\n' "$stage0_rows" "$stage0_output" >&2
  exit 1
}
[[ $(grep -cF 'cannot propagate' <<< "$stage0_output") == 1 ]] || {
  printf 'Stage0 reported an unexpected Try diagnostic count:\n%s\n' "$stage0_output" >&2
  exit 1
}
grep -q 'cannot propagate Expected from a function returning Fault' <<< "$stage0_output" || {
  printf 'Stage0 did not select ProviderA.Expected as the first imported family:\n%s\n' "$stage0_output" >&2
  exit 1
}
[[ $(grep -cF 'cannot propagate' <<< "$stage1_output") == 1 ]] || {
  printf 'Stage1 reported an unexpected Try diagnostic count:\n%s\n' "$stage1_output" >&2
  exit 1
}
[[ "$stage1_rows" == "$expected_rows" ]] || {
  printf 'Stage1 conflicting-import diagnostics differ:\n%s\n%s\n' "$stage1_rows" "$stage1_output" >&2
  exit 1
}
grep -q 'cannot propagate Expected from a function returning Fault' <<< "$stage1_output" || {
  printf 'Stage1 did not select ProviderA.Expected as the first imported family:\n%s\n' "$stage1_output" >&2
  exit 1
}

printf 'bare-variant conflicting selective-import smoke OK: the first imported target wins\n'
