#!/usr/bin/env bash
# Repeated selections of one canonical error family must union across alias spellings.
# Stage0 currently rejects alias-qualified error families, so this checks the Stage1
# semantic result directly; the canonical-path repeated-family smoke provides parity.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_repeated_alias_family.elisa"
output="$("$RPT" < "$FIXTURE")"
if ! grep -q '^D 1$' <<< "$output" || ! grep -q '^L20 cannot propagate' <<< "$output"; then
    echo "EWR repeated-alias smoke expected one missing-Zed diagnostic at L20:\n$output" >&2
    exit 1
fi

echo "EWR repeated-alias smoke OK: one canonical family is unioned across aliases"
