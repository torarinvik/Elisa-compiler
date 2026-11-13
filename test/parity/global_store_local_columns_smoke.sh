#!/usr/bin/env bash
# Local-reference escapes stored globally use the value's source span once.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"
report=$(ELISA_REPORT_COLUMNS=1 "$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/global_store_local_escape.pos.elisa")
[[ $(grep -Fc 'storing a reference to function-local storage' <<< "$report") -eq 2 ]]
grep -Fq 'L13:29-30 storing a reference' <<< "$report"
grep -Fq 'L14:27-28 storing a reference' <<< "$report"
echo 'global local-reference store columns OK'
