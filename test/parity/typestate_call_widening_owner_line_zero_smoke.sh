#!/usr/bin/env bash
# Same-name externs and a sibling def must not share typestate widening facts.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_typestate_call_widening_owner_identity.py"

out="$(cat "$REPO_ROOT/test/repro/typestate_call_widening_owner_line_zero.elisa" | "$RPT")"
grep -q '^P 0$' <<< "$out" || {
    echo "typestate call-widening owner smoke FAIL: fixture did not parse cleanly: $out" >&2
    exit 1
}
mutable_count="$(grep -Fc 'before "call_mutable" returns, but its state was widened by a call' <<< "$out" || true)"
twice_count="$(grep -Fc 'before "call_twice" returns, but its state was widened by a call' <<< "$out" || true)"
two_param_count="$(grep -Fc 'before "call_two" returns, but its state was widened by a call' <<< "$out" || true)"
inactive_extern_count="$(grep -Fc 'before "call_inactive_extern" returns, but its state was widened by a call' <<< "$out" || true)"
const_count="$(grep -Fc 'before "call_const" returns, but its state was widened by a call' <<< "$out" || true)"
arity_count="$(grep -Fc 'before "call_arity" returns, but its state was widened by a call' <<< "$out" || true)"
ambiguous_count="$(grep -Fc 'before "call_ambiguous" returns, but its state was widened by a call' <<< "$out" || true)"
label_count="$(grep -Fc 'before "call_label" returns, but its state was widened by a call' <<< "$out" || true)"
qualified_count="$(grep -Fc 'before "call_qualified" returns, but its state was widened by a call' <<< "$out" || true)"
imported_count="$(grep -Fc 'before "call_imported" returns, but its state was widened by a call' <<< "$out" || true)"
before_import_count="$(grep -Fc 'before "call_before_import" returns, but its state was widened by a call' <<< "$out" || true)"
before_alias_count="$(grep -Fc 'before "call_before_alias" returns, but its state was widened by a call' <<< "$out" || true)"
if_condition_count="$(grep -Fc 'before "call_if_condition" returns, but its state was widened by a call' <<< "$out" || true)"
while_condition_count="$(grep -Fc 'before "call_while_condition" returns, but its state was widened by a call' <<< "$out" || true)"
for_iterable_count="$(grep -Fc 'before "call_for_iterable" returns, but its state was widened by a call' <<< "$out" || true)"
match_scrutinee_count="$(grep -Fc 'before "call_match_scrutinee" returns, but its state was widened by a call' <<< "$out" || true)"
match_guard_count="$(grep -Fc 'before "call_match_guard" returns, but its state was widened by a call' <<< "$out" || true)"
match_body_count="$(grep -Fc 'before "call_match_body" returns, but its state was widened by a call' <<< "$out" || true)"
nested_field_count="$(grep -Fc 'before "call_field_receiver" returns, but its state was widened by a call' <<< "$out" || true)"
move_operand_count="$(grep -Fc 'before "call_move_operand" returns, but its state was widened by a call' <<< "$out" || true)"
region_operand_count="$(grep -Fc 'before "call_region_operand" returns, but its state was widened by a call' <<< "$out" || true)"
inactive_static_block_count="$(grep -Fc 'before "call_inactive_static_block" returns, but its state was widened by a call' <<< "$out" || true)"
active_static_block_count="$(grep -Fc 'before "call_active_static_block" returns, but its state was widened by a call' <<< "$out" || true)"
[[ "$mutable_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: mutable extern warning was borrowed from the same-name def: $out" >&2
    exit 1
}
[[ "$twice_count" -eq 2 ]] || {
    echo "typestate call-widening owner smoke FAIL: distinct widening callsites for one typestate parameter were collapsed or duplicated: $out" >&2
    exit 1
}
[[ "$two_param_count" -eq 2 ]] || {
    echo "typestate call-widening owner smoke FAIL: one call did not report widening for both typestate arguments: $out" >&2
    exit 1
}
[[ "$inactive_extern_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: an inactive extern overload hid the active extern warning: $out" >&2
    exit 1
}
[[ "$inactive_static_block_count" -eq 0 ]] || {
    echo "typestate call-widening owner smoke FAIL: a call in an inactive statement static-if arm was reported: $out" >&2
    exit 1
}
[[ "$active_static_block_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: a call in the active statement static-if arm was skipped: $out" >&2
    exit 1
}
[[ "$const_count" -eq 0 ]] || {
    echo "typestate call-widening owner smoke FAIL: mutable extern sibling tainted the const-ref extern: $out" >&2
    exit 1
}
[[ "$arity_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: a different-arity def hid the uniquely selected mutable extern: $out" >&2
    exit 1
}
[[ "$ambiguous_count" -eq 0 ]] || {
    echo "typestate call-widening owner smoke FAIL: same-shape extern overloads were not left ambiguous: $out" >&2
    exit 1
}
[[ "$label_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: named arguments did not select/map the mutable extern parameter: $out" >&2
    exit 1
}
[[ "$qualified_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: qualified sibling-module call did not resolve the mutable extern owner: $out" >&2
    exit 1
}
[[ "$imported_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: selectively imported bare call did not resolve the mutable extern owner: $out" >&2
    exit 1
}
[[ "$before_import_count" -eq 0 ]] || {
    echo "typestate call-widening owner smoke FAIL: a later selective import retroactively claimed an earlier call: $out" >&2
    exit 1
}
[[ "$before_alias_count" -eq 0 ]] || {
    echo "typestate call-widening owner smoke FAIL: a later module alias retroactively claimed an earlier qualified call: $out" >&2
    exit 1
}
[[ "$if_condition_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: call in an if condition was not scanned: $out" >&2
    exit 1
}
[[ "$while_condition_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: call in a while condition was not scanned: $out" >&2
    exit 1
}
[[ "$for_iterable_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: call in a for iterable was not scanned: $out" >&2
    exit 1
}
[[ "$match_scrutinee_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: call in a match scrutinee was not scanned: $out" >&2
    exit 1
}
[[ "$match_guard_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: call in a match guard was not scanned: $out" >&2
    exit 1
}
[[ "$match_body_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: match arm body was not scanned: $out" >&2
    exit 1
}
[[ "$nested_field_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: extern call nested in a field receiver was not scanned exactly once: $out" >&2
    exit 1
}
[[ "$move_operand_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: extern call nested under move was not scanned: $out" >&2
    exit 1
}
[[ "$region_operand_count" -eq 1 ]] || {
    echo "typestate call-widening owner smoke FAIL: extern call nested under region allocation was not scanned: $out" >&2
    exit 1
}

echo "typestate call-widening exact-owner and overload-shape smoke OK"
