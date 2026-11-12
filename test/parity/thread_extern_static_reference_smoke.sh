#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"
fixture="$ROOT/test/repro/thread_extern_static_reference.elisa"
valid="$("$RPT" < "$fixture")"
[[ "$valid" == *$'P 0\nD 0'* ]] || { printf 'static extern reference rejected:\n%s\n' "$valid" >&2; exit 1; }
invalid="$(sed 's/extern shared_cell() -> static i32\&/extern shared_cell() -> i32\&/' "$fixture" | "$RPT")"
grep -q 'not structurally shareable across threads' <<< "$invalid" || { printf 'non-static extern reference accepted:\n%s\n' "$invalid" >&2; exit 1; }
echo 'extern static reference transfer OK'
