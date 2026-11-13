#!/usr/bin/env bash
# Distinct syntax errors retain their individual token spans after deduplication.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"
report=$(ELISA_REPORT_COLUMNS=1 "$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/region_param_container_return_semicolon_refusal.elisa")
grep -Fq 'L4:40-41 `;` statement separator' <<< "$report"
grep -Fq 'L4:77-78 `;` statement separator' <<< "$report"
report=$(ELISA_REPORT_COLUMNS=1 "$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/bare_comma_statement.neg.elisa")
grep -Fq 'L7:6-7 unexpected token' <<< "$report"
grep -Fq 'L7:8-9 expected newline' <<< "$report"
echo 'parser diagnostic columns OK'
