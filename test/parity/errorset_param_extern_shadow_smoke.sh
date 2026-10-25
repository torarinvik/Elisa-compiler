#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/errorset_param_extern_shadow.elisa")"
if grep -q 'cannot infer error-set parameter' <<< "$report"; then
  printf 'errorset extern-shadow smoke failed; a local extern inherited its parent generic diagnostic:\n%s\n' "$report" >&2
  exit 1
fi

printf 'errorset extern-shadow smoke OK\n'
