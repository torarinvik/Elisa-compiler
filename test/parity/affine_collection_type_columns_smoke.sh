#!/usr/bin/env bash
# Affine set elements and dictionary keys point at the start of the rejected type.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"
report=$(ELISA_REPORT_COLUMNS=1 "$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/affine_set_key.pos.elisa")
grep -Fq 'L12:12-18 set elements cannot contain linear handles, got Handle?' <<< "$report"
grep -Fq 'L13:13-17 dict keys cannot contain linear handles, got Pair' <<< "$report"
grep -Fq 'L15:17-23 set elements cannot contain linear handles, got darray[Handle]' <<< "$report"
grep -Fq 'L18:19-25 dict keys cannot contain linear handles, got Handle?' <<< "$report"
echo 'affine collection type columns OK'
