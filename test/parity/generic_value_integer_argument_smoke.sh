#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"
fixture="$ROOT/test/repro/generic_value_integer_argument.elisa"
valid="$("$RPT" < "$fixture")"
[[ "$valid" == *$'P 0\nD 0'* ]] || { printf 'valid integer generic argument rejected:\n%s\n' "$valid" >&2; exit 1; }
invalid="$(sed 's/first\[i32, 4\]/first[i32, i64]/' "$fixture" | "$RPT")"
[[ "$invalid" != *$'P 0\nD 0'* ]] || { printf 'type name accepted for integer generic argument:\n%s\n' "$invalid" >&2; exit 1; }
echo 'integer generic argument smoke OK'
