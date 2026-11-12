#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"
fixture="$ROOT/test/repro/local_reference_null_comparison.elisa"
local_report="$("$RPT" < "$fixture")"
[[ "$local_report" == *$'P 0\nD 0'* ]] || { printf 'local null comparison charged global authority:\n%s\n' "$local_report" >&2; exit 1; }
global_report="$("$RPT" <<'ELISA'
global mutable item: i64&? = null
def exists() -> bool:
    return item != null
ELISA
)"
grep -q 'without Global.Read' <<< "$global_report" || { printf 'global binding read escaped its authority check:\n%s\n' "$global_report" >&2; exit 1; }
echo 'local reference null comparison OK'
