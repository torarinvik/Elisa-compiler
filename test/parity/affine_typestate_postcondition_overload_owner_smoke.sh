#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_affine_typestate_call_owner.py"

out="$(cat "$REPO_ROOT/test/repro/affine_typestate_postcondition_overload_owner.elisa" | "$RPT")"
grep -q '^P 0$' <<< "$out" || {
    echo "affine typestate call-owner smoke FAIL: fixture did not parse cleanly: $out" >&2
    exit 1
}
if grep -Fq 'indexing requires string, array, view, packed store, or reference type' <<< "$out"; then
    echo "affine typestate call-owner smoke FAIL: match payload regression produced an unrelated non-indexable diagnostic: $out" >&2
    exit 1
fi
count="$(grep -Fc 'linear value "ticket" must be consumed before scope exit' <<< "$out" || true)"
if [[ "$count" -ne 4 ]]; then
    echo "affine typestate call-owner smoke FAIL: expected the direct, branch-shadowed, stale-type i64 loop, and local-callable loop calls without postconditions to leave their linear tickets live: $out" >&2
    exit 1
fi
generic_count="$(grep -Fc 'linear value "generic_ticket" must be consumed before scope exit' <<< "$out" || true)"
if [[ "$generic_count" -ne 1 ]]; then
    echo "affine typestate call-owner smoke FAIL: exact bool overload must suppress generic postcondition fallback: $out" >&2
    exit 1
fi
boxed_generic_count="$(grep -Fc 'linear value "generic_boxed_ticket" must be consumed before scope exit' <<< "$out" || true)"
if [[ "$boxed_generic_count" -ne 0 ]]; then
    echo "affine typestate call-owner smoke FAIL: the caller generic T inside imported Boxed[T] must bind the generic Boxed[Elem] overload: $out" >&2
    exit 1
fi
nominal_generic_count="$(grep -Fc 'linear value "generic_nominal_ticket" must be consumed before scope exit' <<< "$out" || true)"
if [[ "$nominal_generic_count" -ne 1 ]]; then
    echo "affine typestate call-owner smoke FAIL: caller generic T must not select the concrete nominal-T overload: $out" >&2
    exit 1
fi
provider_generic_count="$(grep -Fc 'linear value "generic_provider_box_ticket" must be consumed before scope exit' <<< "$out" || true)"
if [[ "$provider_generic_count" -ne 0 ]]; then
    echo "affine typestate call-owner smoke FAIL: alias-owned ImportedProvider::T collided with caller generic T and rejected its matching generic overload: $out" >&2
    exit 1
fi
if grep -Eq 'linear value "concrete_provider_box_ticket"|concrete_provider_box_ticket.*(state|typestate|transition)' <<< "$out"; then
    echo "affine typestate call-owner smoke FAIL: concrete BoxedWithOwner[bool] must select the non-consuming overload before explicit redeem: $out" >&2
    exit 1
fi
match_count="$(grep -Fc 'linear value "match_ticket" must be consumed before scope exit' <<< "$out" || true)"
if [[ "$match_count" -ne 1 ]]; then
    echo "affine typestate call-owner smoke FAIL: unknown match binder inherited the final function's same-spelled structural TypeId and selected a consuming overload: $out" >&2
    exit 1
fi
region_pair_count="$(grep -Fc 'linear value "region_pair_ticket" must be consumed before scope exit' <<< "$out" || true)"
qualified_nominal_alias_count="$(grep -Fc 'linear value "qualified_nominal_mismatch_ticket" must be consumed before scope exit' <<< "$out" || true)"
if [[ "$region_pair_count" -ne 1 ]]; then
    echo "affine typestate call-owner smoke FAIL: repeated formal regions must not select a postcondition for distinct actual regions: $out" >&2
    exit 1
fi
if [[ "$qualified_nominal_alias_count" -ne 1 ]]; then
    echo "affine typestate call-owner smoke FAIL: a zero-TypeId qualified nominal alias must not select a same-spelled but different-owner postcondition: $out" >&2
    exit 1
fi
for selected_name in qualified_ticket imported_return_ticket get_else_ticket pair_ticket structured_ticket imported_structural_alias_ticket imported_nominal_ticket qualified_nominal_match_ticket module_alias_nominal_match_ticket qualified_nominal_tuple_ticket qualified_nominal_array_ticket qualified_structural_alias_ticket qualified_nominal_pair_alias_ticket qualified_nominal_ref_ticket qualified_nominal_optional_ticket qualified_type_alias_ticket imported_type_alias_ticket module_alias_type_ticket same_region_ticket generic_boxed_ticket; do
    if grep -Fq "linear value \"$selected_name\" must be consumed before scope exit" <<< "$out"; then
        echo "affine typestate call-owner smoke FAIL: a firmly typed qualified/imported type alias, qualified/imported-return, get-else, or tuple argument lost its consuming postcondition: $out" >&2
        exit 1
    fi
done
field_owner_count="$(grep -Fc 'linear value "field_owner_ticket" must be consumed before scope exit' <<< "$out" || true)"
if [[ "$field_owner_count" -ne 1 ]]; then
    echo "affine typestate call-owner smoke FAIL: ambiguous named return field owner must stay unknown instead of borrowing the caller's Item field type: $out" >&2
    exit 1
fi
loop_count="$(grep -Fc 'declared outside the loop is consumed on every iteration' <<< "$out" || true)"
if [[ "$loop_count" -ne 1 ]]; then
    echo "affine typestate call-owner smoke FAIL: expected only the explicit outer-ticket loop call to report a repeated iteration consume: $out" >&2
    exit 1
fi

echo "affine typestate call-owner smoke OK"
