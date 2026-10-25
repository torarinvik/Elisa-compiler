#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
export ELISA_STAGE1_BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
export ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
source "$ROOT/test/parity/build_parse_report.sh"

report=$("$RPT" < "$ROOT/test/repro/catch_unknown_static_branches.elisa")
grep -q 'catch arm "Fault.Other" does not match the caught call' <<< "$report"
grep -q 'catch arm "Phantom.Gone" does not match the caught call' <<< "$report"
grep -q 'catch arm "plain" does not match R' <<< "$report"
grep -q 'match expression arm must end with an expression' <<< "$report"

echo "catch unknown static-branch smoke OK" >&2
