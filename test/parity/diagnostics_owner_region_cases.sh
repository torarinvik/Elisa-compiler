# Generic operator checks must not borrow a type parameter from another declaration
# that happens to share a logical line with `#line`.
generic_operator_owner_out=$(printf 'type T = i64\n#line 0 generic_owner.elisa\ndef phantom[T]() -> void:\n    pass\n#line 0 concrete_owner.elisa\ndef concrete_sum(a: T, b: T) -> T:\n    return a + b\n' | "$RPT")
if grep -Fq 'operator requires numeric operands' <<< "$generic_operator_owner_out"; then
    echo "FAIL generic_operator_no_bound: a same-line generic owner misclassified a concrete alias function" >&2
    echo "$generic_operator_owner_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS generic_operator_no_bound line-zero owner collision"
fi
generic_operator_bound_owner_out=$(printf 'protocol Add:\n    def __add__(self: Self, other: Self) -> Self\n#line 0 bounded_owner.elisa\ndef evidence[T: Add](x: T, y: T) -> T:\n    return x + y\n#line 0 unbound_owner.elisa\ndef bad[U](x: U, y: U) -> U:\n    return x + y\n' | "$RPT")
if ! grep -Fq 'operator requires numeric operands' <<< "$generic_operator_bound_owner_out"; then
    echo "FAIL generic_operator_no_bound: a same-line bounded owner suppressed the unbound function's operator diagnostic" >&2
    echo "$generic_operator_bound_owner_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS generic_operator_no_bound line-zero bounded-owner collision"
fi

# Extern effect references are separate annotations from their declaration markers. The source
# lines are forced equal so a line-only lookup would give `second` the first extern's effect.
same_line_extern_effect_out=$(printf '#line 37 first_effect.elisa\nextern first_effect() -> void can[Memory.Allocate]\n#line 37 second_effect.elisa\nextern second_effect() -> void can[Unsafe.Alias]\ndef effect_caller() -> void:\n    second_effect()\n' | "$RPT")
if ! grep -Fq 'call to "second_effect" requires can[Unsafe]' <<< "$same_line_extern_effect_out"; then
    echo "FAIL extern effect owner: a same-line sibling supplied the wrong capability ref" >&2
    echo "$same_line_extern_effect_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS extern effect owner same-line declaration identity"
fi
complete_multieffect_extern_out=$(printf '#line 37 first_row.elisa\nextern first_row() -> void can[Memory.Allocate, Console.Write]\n#line 37 second_row.elisa\nextern second_row() -> void can[Unsafe.Alias, Global.Write]\ndef row_caller() -> void:\n    can Unsafe.Alias:\n        second_row()\n' | "$RPT")
if ! grep -Fq 'call to "second_row" requires can[Global]' <<< "$complete_multieffect_extern_out"; then
    echo "FAIL extern effect owner: full same-line effect row did not retain its second member and declaration owner" >&2
    echo "$complete_multieffect_extern_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS extern effect owner preserves full same-line permission rows"
fi
empty_extern_row_out=$(printf 'extern empty_effect() -> void can[]\ndef empty_row_caller() -> void:\n    empty_effect()\n' | "$RPT")
if grep -Fq 'call to "empty_effect" requires' <<< "$empty_extern_row_out"; then
    echo "FAIL extern effect owner: an explicit empty can[] row was treated as an unknown permission" >&2
    echo "$empty_extern_row_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS extern effect owner treats explicit empty rows as pure"
fi
cross_module_extern_effect_collision_out=$(cat "$REPO_ROOT/test/repro/extern_cross_module_effect_leaf_collision.elisa" | "$RPT")
if grep -Fq 'call to "inspect" requires can[Disk]' <<< "$cross_module_extern_effect_collision_out"; then
    echo "FAIL extern effect owner: a same-leaf module sibling supplied the wrong capability ref" >&2
    echo "$cross_module_extern_effect_collision_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS extern effect owner fails closed on cross-module same-leaf ambiguity"
fi
inspect_console_warning_count=$(grep -Fc 'call to "inspect" requires can[Console]' <<< "$cross_module_extern_effect_collision_out" || true)
if [[ "$inspect_console_warning_count" -lt 5 ]]; then
    echo "FAIL extern effect owner: qualified, selectively imported, and locally shadowed calls must use Second::inspect's Console row" >&2
    echo "$cross_module_extern_effect_collision_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS extern effect owner diagnoses qualified, imported, and locally shadowed calls from the selected module row"
fi
if ! grep -Fq 'call to "inspect_via" requires can[Console]' <<< "$cross_module_extern_effect_collision_out"; then
    echo "FAIL extern effect owner: a via row must retain its concrete Console requirement" >&2
    echo "$cross_module_extern_effect_collision_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS extern effect owner diagnoses the concrete capability carried by a via row"
fi
if grep -Fq 'call to "imported_shadow_call" requires can[Console]' <<< "$cross_module_extern_effect_collision_out"; then
    echo "FAIL extern effect owner: a shadowing callback parameter leaked the imported extern's Console row" >&2
    echo "$cross_module_extern_effect_collision_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS extern effect owner keeps imported extern rows out of shadowing callback functions"
fi
for source_worker in qualified_source_worker imported_source_worker imported_return_source_worker; do
    if ! grep -Fq "call to \"$source_worker\" requires can[Console]" <<< "$cross_module_extern_effect_collision_out"; then
        echo "FAIL extern effect source identity: $source_worker did not propagate the selected extern Console row" >&2
        echo "$cross_module_extern_effect_collision_out" | sed 's/^/    /' >&2
        failed=$((failed + 1))
    fi
done
if grep -Fq 'call to "panic_callback_source" requires can[Abort]' <<< "$cross_module_extern_effect_collision_out"; then
    echo "FAIL extern effect source identity: a local callback named panic created an Abort.Panic source row" >&2
    echo "$cross_module_extern_effect_collision_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS extern effect source identity preserves selected owners, returns, and local panic shadowing"
fi
if grep -Fq 'call to "call_imported_block_tail_shadow" requires can[Console]' <<< "$cross_module_extern_effect_collision_out"; then
    echo "FAIL extern effect source identity: an Expr.Block tail call ignored its local callback binder" >&2
    echo "$cross_module_extern_effect_collision_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS extern effect source identity carries block-tail callback shadowing through both effect walkers"
fi
if ! grep -Fq 'call to "multi_source_caller" requires can[Console, Memory]' <<< "$cross_module_extern_effect_collision_out"; then
    echo "FAIL extern effect source identity: a wrapper lost one of the selected extern's required refs" >&2
    echo "$cross_module_extern_effect_collision_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS extern effect source identity preserves every selected extern ref through wrappers"
fi
shared_source_console_warning_count=$(grep -Fc 'call to "shared_source_worker" requires can[Console]' <<< "$cross_module_extern_effect_collision_out" || true)
if [[ "$shared_source_console_warning_count" -lt 2 ]] || grep -Fq 'call to "shared_source_worker" requires can[Disk]' <<< "$cross_module_extern_effect_collision_out"; then
    echo "FAIL extern effect source identity: qualified regular calls did not select only the module's declared effect row in outside-grant and block-coverage checks" >&2
    echo "$cross_module_extern_effect_collision_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS extern effect source identity selects the exact module row in outside-grant and block-coverage checks"
fi
nested_module_console_warning_count=$(grep -Fc 'call to "nested_module_worker" requires can[Console]' <<< "$cross_module_extern_effect_collision_out" || true)
if [[ "$nested_module_console_warning_count" -lt 1 ]] || grep -Fq 'call to "nested_module_worker" requires can[Disk]' <<< "$cross_module_extern_effect_collision_out"; then
    echo "FAIL extern effect source identity: nested module declarations did not retain their canonical full module path" >&2
    echo "$cross_module_extern_effect_collision_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS extern effect source identity preserves nested module paths for declared effect rows"
fi
blocking_same_line_effect_out=$(printf '#line 37 blocking_decorator.elisa\n@blocking\nextern blocking_call() -> void\n#line 38 signature_effect.elisa\nextern signature_call() -> void can[Unsafe.Alias]\ndef blocking_effect_caller() -> void:\n    blocking_call()\n    signature_call()\n' | "$RPT")
if ! grep -Fq 'call to "blocking_call" requires can[Blocking]' <<< "$blocking_same_line_effect_out" || ! grep -Fq 'call to "signature_call" requires can[Unsafe]' <<< "$blocking_same_line_effect_out"; then
    echo "FAIL extern effect owner: @blocking and signature effects crossed on a shared logical line" >&2
    echo "$blocking_same_line_effect_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS extern effect owner separates @blocking from signature effects"
fi
same_line_extern_segment_out=$(printf '#line 37 module_a.elisa\nmodule A:\n    extern f() -> void can[Unsafe.SegmentMutation, Segment.Guest]\n#line 37 module_b.elisa\nmodule B:\n    extern f() -> void\ndef main() -> i64:\n    return 0\n' | "$RPT")
same_line_extern_segment_count=$(grep -Fc 'mutates the active segment; add @segment_transition' <<< "$same_line_extern_segment_out" || true)
if [[ "$same_line_extern_segment_count" -ne 1 ]]; then
    echo "FAIL extern segment owner: a same-named sibling borrowed another module's marker" >&2
    echo "$same_line_extern_segment_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS extern segment owner same-named module declaration identity"
fi
same_line_ensures_return_out=$(printf '#line 0 numeric_return.elisa\ndef choose(value: i64) -> i64 ensures return true:\n    return value\n#line 0 boolean_return.elisa\ndef choose(value: bool) -> bool:\n    return value\n' | "$RPT")
same_line_ensures_return_count=$(grep -Fc 'ensures return true on function "choose" requires a bool return type' <<< "$same_line_ensures_return_out" || true)
if [[ "$same_line_ensures_return_count" -ne 1 ]]; then
    echo "FAIL ensures return owner: a same-line bool overload borrowed its sibling's marker" >&2
    echo "$same_line_ensures_return_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS ensures return owner same-line overload identity"
fi
same_line_field_default_out=$(cat "$REPO_ROOT/test/repro/field_default_type_owner_line_zero.elisa" | "$RPT")
same_line_field_default_count=$(grep -Fc 'default value for struct field "bad" expects bool, got int' <<< "$same_line_field_default_out" || true)
if [[ "$same_line_field_default_count" -ne 1 ]]; then
    echo "FAIL field default owner: a same-line field borrowed its sibling's type/kind marker" >&2
    echo "$same_line_field_default_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS field default owner same-line field identity"
fi
mutable_field_default_count=$(grep -Fc 'default value for struct field "mutable_bad" expects bool, got int' <<< "$same_line_field_default_out" || true)
if [[ "$mutable_field_default_count" -ne 1 ]]; then
    echo "FAIL field default mutable type head: mutable bool must report the underlying bool mismatch" >&2
    echo "$same_line_field_default_out" | sed 's/^/    /' >&2
    failed=$((failed + 1))
else
    echo "PASS field default mutable type head"
fi

# The direct warning plus match guards/bodies and the catch expression, guards, and body
# prove each structured arm walker visits its conditions and statements.
require_diagnostic_count logical_constant_operand_arm_traversal \
    "$FIXTURES/logical_constant_operand.pos.elisa" \
    'logical operator with constant boolean operand' 8

echo "-- guard_condition_nonbool --"
run_case guard_condition_nonbool pos "$FIXTURES/guard_condition_nonbool.pos.elisa" "logical operator requires bool operands"
run_case guard_condition_nonbool neg "$FIXTURES/guard_condition_nonbool.neg.elisa" "logical operator requires bool operands"

require_diagnostic_count iter_mutref_expression_contexts \
    "$FIXTURES/iter_mutref_expression_contexts.pos.elisa" \
    'cannot pass "xs" by mutable reference while it is being iterated: the callee may push/clear/relocate its buffer' 8

echo "-- region_returned_stored_borrow --"
run_case region_returned_stored_borrow pos "$REPO_ROOT/test/repro/region_returned_stored_borrow.pos.elisa" "cannot be returned with a region-less type"
run_case region_returned_stored_borrow neg "$REPO_ROOT/test/repro/region_returned_stored_borrow.neg.elisa" "cannot be returned with a region-less type"

echo "-- while_tail_fallthrough --"
run_case while_true_tail_no_exit neg "$FIXTURES/while_true_tail_missing_return.neg.elisa" "may fall through without returning a value"
run_case while_true_tail_can_break pos "$FIXTURES/while_true_tail_can_break.pos.elisa" "may fall through without returning a value"

echo "-- view_return_escape --"
region_return_msg="value backed by a short-lived region escapes via return; the region ends at scope exit"
for escape_shape in darray binding tail tuple struct_field; do
    run_case "view_return_escape_$escape_shape" pos "$FIXTURES/view_return_escape_$escape_shape.pos.elisa" "$region_return_msg"
done
run_case view_return_escape neg "$FIXTURES/view_return_escape.neg.elisa" "$region_return_msg"
run_case region_param_container_return pos "$FIXTURES/region_param_container_return.pos.elisa" "$region_return_msg"
run_case region_param_container_return neg "$FIXTURES/region_param_container_return.neg.elisa" "$region_return_msg"
run_case region_param_container_return_reference_element pos "$FIXTURES/region_param_container_return_reference_element.pos.elisa" "$region_return_msg"
run_case region_param_container_return_inferred_new pos "$FIXTURES/region_param_container_return_inferred_new.pos.elisa" "$region_return_msg"
run_case region_param_container_return_inner_new pos "$FIXTURES/region_param_container_return_inner_new.pos.elisa" "$region_return_msg"
run_case region_param_container_return_auto_move pos "$FIXTURES/region_param_container_return_auto_move.pos.elisa" "$region_return_msg"
run_case region_param_container_return_inner_move pos "$FIXTURES/region_param_container_return_inner_move.pos.elisa" "$region_return_msg"
# The return-escape exception must not bless a local merely because its annotation says @r.
# These are independent semantic-pass diagnostics from the initializer/assignment provenance.
require_region_control() {
    local name="$1" file="$2" expect="$3"
    local out
    out="$("$RPT" < "$file" 2>&1)"
    if grep -qF "$expect" <<< "$out"; then
        echo "  PASS $name (independent provenance refusal: \"$expect\")"
    else
        echo "  FAIL $name: independent provenance refusal missing" >&2
        echo "    expected substring: $expect" >&2
        echo "$out" | sed 's/^/      /' >&2
        failed=$((failed + 1))
    fi
}
require_region_control region_param_container_return_inferred_new "$FIXTURES/region_param_container_return_inferred_new.pos.elisa" '`new[auto]` is deprecated'
require_region_control region_param_container_return_inferred_new "$FIXTURES/region_param_container_return_inferred_new.pos.elisa" 'variable "values" expects darray, got reference'
inferred_region_store='value in region "<inferred>" is stored into longer-lived region "r"'
require_region_control region_param_container_return_auto_move "$FIXTURES/region_param_container_return_auto_move.pos.elisa" "$inferred_region_store"
run_case region_param_container_return_same_region_store neg "$FIXTURES/region_param_container_return.neg.elisa" "$inferred_region_store"

# Semicolon-separated multistatements are not legal Elisa. Pin that parser rejection instead of
# treating equal source-line numbers as evidence that the unsafe reassignment is supported syntax.
require_removed_semicolon_control() {
    local name="$1" file="$2" out
    out="$("$RPT" < "$file" 2>&1)"
    if grep -qF '`;` statement separator has been removed' <<< "$out"; then
        echo "  PASS $name (unsupported multistatement syntax rejected)"
    else
        echo "  FAIL $name: expected removed-semicolon parser diagnostic missing" >&2
        echo "$out" | sed 's/^/      /' >&2
        failed=$((failed + 1))
    fi
}
require_removed_semicolon_control region_param_container_return_semicolon_refusal "$FIXTURES/region_param_container_return_semicolon_refusal.elisa"
run_case region_param_container_return_branch_bindings neg "$FIXTURES/region_param_container_return_branch_bindings.neg.elisa" "$region_return_msg"

# Stage0's independent region/type passes are the authority for these source-provenance
# controls. Keep them separate from Stage1's return-escape diagnostic assertions above.
require_stage0_region_control() {
    local name="$1" file="$2" expect="$3"
    local log="$REPO_ROOT/build/g75-region-control-$name.$$.log"
    local object="$REPO_ROOT/build/g75-region-control-$name.$$.o"
    if "$ELISACORE_BIN" -emit obj -o "$object" "$file" >"$log" 2>&1; then
        echo "  FAIL $name: Stage0 accepted unsafe caller-region provenance" >&2
        failed=$((failed + 1))
    elif grep -qF "$expect" "$log"; then
        echo "  PASS $name (Stage0 independently refused: \"$expect\")"
    else
        echo "  FAIL $name: expected Stage0 provenance refusal missing" >&2
        echo "    expected substring: $expect" >&2
        sed 's/^/      /' "$log" >&2
        failed=$((failed + 1))
    fi
}
require_stage0_region_control region_param_container_return_inner_new "$FIXTURES/region_param_container_return_inner_new.pos.elisa" 'cannot return value: region dependency facts include local region "inner"'
require_stage0_region_control region_param_container_return_inferred_new "$FIXTURES/region_param_container_return_inferred_new.pos.elisa" 'expects darray[i64], got mutable darray[i64]& @__auto'
require_stage0_region_control region_param_container_return_auto_move "$FIXTURES/region_param_container_return_auto_move.pos.elisa" 'value in region "<inferred>" is stored into longer-lived region "r"'
require_stage0_region_control region_param_container_return_inner_move "$FIXTURES/region_param_container_return_inner_move.pos.elisa" 'value in region "inner" is stored into longer-lived region "r"'
require_stage0_region_control region_param_container_return_reference_element "$FIXTURES/region_param_container_return_reference_element.pos.elisa" 'cannot return value: region dependency facts include local region "inner"'
run_case local_view_escape_binding pos "$FIXTURES/local_view_escape_binding.pos.elisa" "view of local \"v\" escapes via return; the array dies at scope exit"
run_case view_return_escape neg "$FIXTURES/view_return_escape.neg.elisa" "escapes via return; the array dies at scope exit"
run_case local_view_escape_struct_field pos "$FIXTURES/local_view_escape_struct_field.pos.elisa" "view of local \"s\" escapes via return; the array dies at scope exit"
run_case local_view_escape_view_call pos "$FIXTURES/local_view_escape_view_call.pos.elisa" "value backed by a short-lived region escapes via return"
run_case local_view_escape_more neg "$FIXTURES/local_view_escape_more.neg.elisa" "escapes via return"
run_case return_ref_local_in_block pos "$FIXTURES/return_ref_local_in_block.pos.elisa" "returning a reference into function-local storage"
run_case view_return_escape neg "$FIXTURES/view_return_escape.neg.elisa" "returning a reference into function-local storage"
