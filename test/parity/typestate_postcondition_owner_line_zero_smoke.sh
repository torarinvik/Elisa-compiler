#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_typestate_postcondition_owner_identity.py"

out="$(cat "$REPO_ROOT/test/repro/typestate_postcondition_owner_line_zero.elisa" | "$RPT")"
grep -q '^P 0$' <<< "$out" || {
    echo "typestate postcondition owner smoke FAIL: fixture did not parse cleanly: $out" >&2
    exit 1
}
count="$(grep -Fc 'ensures on function "second" requires "target" to resolve to a named-state-bearing target, got Plain' <<< "$out" || true)"
if [[ "$count" -ne 1 ]]; then
    echo "typestate postcondition owner smoke FAIL: same-line sibling borrowed the first function's stateful parameter type: $out" >&2
    exit 1
fi

flow_out="$(cat "$REPO_ROOT/test/repro/derived_typestate_ensures_owner_line_zero.elisa" | "$RPT")"
grep -q '^P 0$' <<< "$flow_out" || {
    echo "typestate postcondition owner smoke FAIL: derived-flow fixture did not parse cleanly: $flow_out" >&2
    exit 1
}
flow_count="$(grep -Fc 'parameter value must be left in its declared state before "advance" returns, but it is left in state Large' <<< "$flow_out" || true)"
if [[ "$flow_count" -ne 1 ]]; then
    echo "typestate postcondition owner smoke FAIL: overload inherited its sibling's ensures postcondition: $flow_out" >&2
    exit 1
fi

echo "typestate postcondition owner smoke OK"
