#!/usr/bin/env bash
# Parenthesized indexed receivers retain their outer source span for diagnostics.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"
report=$(ELISA_REPORT_COLUMNS=1 "$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/darray_index_receiver.pos.elisa")
for span in 'L5:8-9' 'L8:11-12' 'L11:12-13' 'L14:5-6' 'L17:8-9'; do
    grep -Fq "$span darray " <<< "$report"
done
echo 'darray receiver columns OK'
