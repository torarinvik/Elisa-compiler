#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
export ELISA_STAGE1_BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
export ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
source "$ROOT/test/parity/build_parse_report.sh"

report=$("$RPT" < "$ROOT/test/repro/catch_nested_alias_target.elisa")
grep -q '^D 1$' <<< "$report"
grep -q 'non-exhaustive catch over Fault; missing Fault.Missing' <<< "$report"

echo "nested Catch alias target smoke OK" >&2
