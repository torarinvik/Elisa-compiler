#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
export ELISA_STAGE1_BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
export ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
source "$ROOT/test/parity/build_parse_report.sh"

report=$("$RPT" < "$ROOT/test/repro/catch_inactive_static_branches.elisa")
grep -q '^D 0$' <<< "$report"

# Only a proven inactive scope is omitted by the resolver.
report=$("$RPT" <<'EOF'
module Nested:
    static if false:
        def dormant() -> i64:
            pass
    static else:
        def active() -> i64:
            pass
EOF
)
grep -q '^P 0$' <<< "$report"
grep -q '^D 1$' <<< "$report"
grep -q 'function active may fall through without returning a value' <<< "$report"

echo "catch inactive static-branch smoke OK" >&2
