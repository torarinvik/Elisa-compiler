#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"
fixture="$ROOT/test/repro/raise_shared_singleton_tag.elisa"
valid="$("$RPT" < "$fixture")"
[[ "$valid" == *$'P 0\nD 0'* ]] || { printf 'shared singleton tag rejected:\n%s\n' "$valid" >&2; exit 1; }
invalid="$(sed 's/raise FileError.NotFound/raise FileError.PermissionDenied/' "$fixture" | "$RPT")"
grep -q 'raise cannot propagate tag' <<< "$invalid" || { printf 'different tag accepted:\n%s\n' "$invalid" >&2; exit 1; }
echo 'shared singleton error tag smoke OK'
