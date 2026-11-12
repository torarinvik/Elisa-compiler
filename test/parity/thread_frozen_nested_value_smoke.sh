#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"
valid="$( { printf '# nopath\n'; cat "$ROOT/test/repro/thread_frozen_nested_value.elisa"; } | "$RPT")"
[[ "$valid" == *$'P 0\nD 0'* ]] || { printf 'frozen nested value rejected:\n%s\n' "$valid" >&2; exit 1; }
invalid="$( { printf '# nopath\n'; cat "$ROOT/test/repro/thread_unpublished_nested_value.elisa"; } | "$RPT")"
grep -q 'store dependency facts require rebase' <<< "$invalid" || { printf 'unpublished nested store accepted:\n%s\n' "$invalid" >&2; exit 1; }
local_views="$( { printf '# nopath\n'; cat "$ROOT/test/repro/thread_local_array_view.elisa"; } | "$RPT")"
[[ "$(grep -c 'argument to "pool_submit1" is not structurally shareable' <<< "$local_views")" -eq 2 ]] || {
  printf 'local array views crossed a thread boundary:\n%s\n' "$local_views" >&2
  exit 1
}
echo 'frozen nested value transfer OK'
