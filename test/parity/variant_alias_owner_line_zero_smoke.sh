#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$REPO_ROOT/test/proofs/check_variant_alias_owner_identity.py"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/variant_alias_owner_line_zero.elisa")"
grep -qx 'P 0' <<< "$report"
grep -qx 'D 1' <<< "$report"
grep -Fq 'accesses a global mutable binding without Global.Write' <<< "$report"
grep -qx 'S 1' <<< "$report"
echo 'variant-alias owner smoke OK'
