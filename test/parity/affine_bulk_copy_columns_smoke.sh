#!/usr/bin/env bash
# Bulk-copy diagnostics identify the argument that would duplicate handles.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"
report=$(ELISA_REPORT_COLUMNS=1 "$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/affine_bulk_copy.pos.elisa")
for span in 'L23:15-17' 'L25:13-17' 'L27:13-14' 'L30:12-13' 'L33:15-17'; do
    grep -Fq "$span " <<< "$report"
done
fields=$(ELISA_REPORT_COLUMNS=1 "$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/affine_bulk_copy_field.pos.elisa")
grep -Fq 'L23:20-24 darray extend' <<< "$fields"
grep -Fq 'L24:23-24 bulk darray push' <<< "$fields"
echo 'affine bulk-copy columns OK'
