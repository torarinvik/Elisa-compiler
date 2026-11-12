#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"
report="$("$RPT" < "$ROOT/test/repro/catch_nested_global_alias.elisa")"
[[ "$report" == *$'P 0\nD 1\n'* && "$report" == *'undefined identifier "NestedGlobal.load"'* ]] || {
    printf 'nested alias must be out of scope at root:\n%s\n' "$report" >&2
    exit 1
}
echo 'nested alias catch scope smoke OK'
