#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/errorset_param_module_scope.elisa")"
diagnostic_count="$(grep -c 'cannot infer error-set parameter' <<< "$report" || true)"
if [[ "$diagnostic_count" != 1 ]] || ! grep -Eq '^[[:space:]]*L10 cannot infer error-set parameter "R" for call to "wrap"' <<< "$report"; then
  printf 'errorset-parameter scope smoke failed; expected only the local Bad::wrap diagnostic on line 10:\n%s\n' "$report" >&2
  exit 1
fi

printf 'errorset-parameter scope smoke OK\n'
