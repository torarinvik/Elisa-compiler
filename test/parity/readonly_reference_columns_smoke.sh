#!/usr/bin/env bash
# Readonly path mutations identify the failing field or index operation.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"
report=$(ELISA_REPORT_COLUMNS=1 "$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/ref_readonly_path.pos.elisa")
grep -Fq 'L8:6-7 cannot mutate through readonly ref' <<< "$report"
report=$(ELISA_REPORT_COLUMNS=1 "$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/readonly_ref_module_qualified.neg.elisa")
grep -Fq 'L8:6-7 cannot mutate through readonly ref' <<< "$report"
grep -Fq 'L14:6-7 cannot mutate through readonly ref' <<< "$report"
report=$(ELISA_REPORT_COLUMNS=1 "$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/ref_builtin_struct_field.pos.elisa")
grep -Fq 'L18:11-12 cannot mutate through readonly ref' <<< "$report"
echo 'readonly reference columns OK'
