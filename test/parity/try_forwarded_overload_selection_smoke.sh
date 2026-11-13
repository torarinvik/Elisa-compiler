#!/usr/bin/env bash
# Forwarded caller parameters select the same fallible overload as an explicit call.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
FIXTURE="$REPO_ROOT/test/repro/try_overload_nested_and_forwarded_calls.elisa"
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1 || true)"
stage1_output="$("$RPT" < "$FIXTURE")"
for line in 30 36; do
    grep -Eq ":${line}:[0-9]+[^:]*: cannot propagate" <<< "$stage0_output" || { echo "Stage0 missed forwarded error family at $line: $stage0_output" >&2; exit 1; }
    grep -Eq "^[[:space:]]*L${line} cannot propagate PublicFault from a function returning OtherFault$" <<< "$stage1_output" || { echo "Stage1 missed forwarded error family at $line: $stage1_output" >&2; exit 1; }
done
if grep -q 'try requires a fallible expression' <<< "$stage1_output"; then
    echo "Stage1 treated a forwarded fallible call as non-fallible: $stage1_output" >&2
    exit 1
fi
echo 'try forwarded overload selection OK'
