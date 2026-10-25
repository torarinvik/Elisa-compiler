#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/errorset_param_static_import_branch.elisa")"
diagnostic_count="$(grep -c 'cannot infer error-set parameter' <<< "$report" || true)"
if [[ "$diagnostic_count" != 1 ]] || ! grep -Eq '^[[:space:]]*L22 cannot infer error-set parameter "S" for call to "wrap"' <<< "$report"; then
  printf 'errorset-parameter static-import smoke failed; expected the active imported callable diagnostic on line 22:\n%s\n' "$report" >&2
  exit 1
fi

printf 'errorset-parameter static-import smoke OK\n'
