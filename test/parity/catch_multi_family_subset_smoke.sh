#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
export ELISA_STAGE1_BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
export ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
source "$ROOT/test/parity/build_parse_report.sh"

report=$("$RPT" < "$ROOT/test/repro/catch_multi_family_subset.elisa")
grep -q '^D 1$' <<< "$report"
grep -q 'catch arm "First::Fault.ForbiddenFirst" does not match the caught call' <<< "$report"

# A duplicate full enum tag outside the declared subset does not make the sole
# included short-prefix fallback ambiguous.
unambiguous=$("$RPT" < "$ROOT/test/repro/catch_multi_family_subset_ambiguity.elisa")
grep -q '^D 0$' <<< "$unambiguous"

echo "catch multi-family subset identity smoke OK" >&2
