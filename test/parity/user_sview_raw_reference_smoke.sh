#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"
report="$("$RPT" < "$ROOT/test/repro/user_sview_raw_reference.elisa")"
[[ "$report" == *$'P 0\nD 0'* ]] || { printf 'user-defined raw-reference sview rejected:\n%s\n' "$report" >&2; exit 1; }
unsafe="$("$RPT" <<'ELISA'
def sview(value: cstr, start: i64, end: i64) -> i64:
    return start + end
def use(value: u8&) -> i64:
    return sview(value, 0, 2)
ELISA
)"
grep -q 'expects NUL-terminated cstr, got raw reference' <<< "$unsafe" || { printf 'raw pointer accepted for cstr parameter:\n%s\n' "$unsafe" >&2; exit 1; }
echo 'user sview reference parameter OK'
