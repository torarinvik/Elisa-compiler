#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
FIXTURE="$REPO_ROOT/test/repro/errorset_param_nested_expression.elisa"

report="$("$RPT" < "$FIXTURE")"
diagnostic_count="$(grep -c 'cannot infer error-set parameter' <<< "$report" || true)"
if [[ "$diagnostic_count" != 5 ]] || ! grep -Eq '^[[:space:]]*L8 cannot infer error-set parameter "R" for call to "wrap"' <<< "$report" || ! grep -Eq '^[[:space:]]*L11 cannot infer error-set parameter "R" for call to "wrap"' <<< "$report" || ! grep -Eq '^[[:space:]]*L15 cannot infer error-set parameter "R" for call to "wrap"' <<< "$report" || ! grep -Eq '^[[:space:]]*L24 cannot infer error-set parameter "Q" for call to "wrap"' <<< "$report" || ! grep -Eq '^[[:space:]]*L30 cannot infer error-set parameter "Q" for call to "wrap"'; then
  printf 'errorset-parameter nested-expression smoke failed; expected diagnostics on lines 8, 11, 15, 24, and 30:\n%s\n' "$report" >&2
  exit 1
fi

printf 'errorset-parameter nested-expression smoke OK\n'
