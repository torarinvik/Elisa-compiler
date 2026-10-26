#!/usr/bin/env bash
# `new` markers must identify their AST target when sibling constructs share #line 0.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_new_construct_owner_identity.py"

out="$(cat "$REPO_ROOT/test/repro/new_construct_owner_line_zero.elisa" | "$RPT")"
grep -q '^P 0$' <<< "$out" || {
    echo "new construct owner smoke FAIL: fixture did not parse cleanly: $out" >&2
    exit 1
}
positional_count="$(grep -Fc 'positional construction Box(...) is not allowed' <<< "$out" || true)"
packed_count="$(grep -Fc 'packed enum constructor "Node.Leaf" requires an active in Node.Store' <<< "$out" || true)"
[[ "$positional_count" -eq 1 ]] || {
    echo "new construct owner smoke FAIL: same-line sibling inherited the new-form positional exemption: $out" >&2
    exit 1
}
[[ "$packed_count" -eq 1 ]] || {
    echo "new construct owner smoke FAIL: same-line sibling inherited the packed-constructor new exemption: $out" >&2
    exit 1
}
if grep -Fq 'value backed by a short-lived region escapes via return' <<< "$out"; then
    echo "new construct owner smoke FAIL: sibling new-array marker changed the tied return initializer: $out" >&2
    exit 1
fi

echo "new construct exact-target owner smoke OK"
