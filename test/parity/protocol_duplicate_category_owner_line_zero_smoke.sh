#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_declaration_is_protocol_owner_identity.py"

out="$(cat "$REPO_ROOT/test/repro/protocol_duplicate_category_owner_line_zero.elisa" | "$RPT")"
count_type="$(grep -Fc 'duplicate type "Shared"' <<< "$out" || true)"
count_interface="$(grep -Fc 'duplicate interface "Shared"' <<< "$out" || true)"
if [[ "$count_type" -ne 1 || "$count_interface" -ne 0 ]]; then
    echo "protocol duplicate-category owner smoke FAIL: repeated type aliases got the wrong category: $out" >&2
    exit 1
fi

echo "protocol duplicate-category owner smoke OK"
