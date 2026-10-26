#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$REPO_ROOT/test/proofs/check_flow_strict_block_if_owner_identity.py"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/flow_strict_block_if_owner_line_zero.elisa")"
grep -qx 'P 0' <<< "$report"
grep -qx 'D 1' <<< "$report"
count="$(grep -c 'strict flow \[-Wflow-strict\]' <<< "$report" || true)"
if [[ "$count" -ne 1 ]]; then
  echo "flow-strict block-if owner smoke FAILED: expected one non-exempt if diagnostic, got $count" >&2
  printf '%s\n' "$report" >&2
  exit 1
fi
echo 'flow-strict block-if owner smoke OK'
