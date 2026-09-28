#!/usr/bin/env bash
# Regression harness for the ~78 stage1 semantic diagnostics (src/semantic/check_*.elisa).
#
# Convention (test/fixtures/diagnostics/): for a diagnostic named <name>,
#   <name>.pos.elisa - minimal standalone snippet that MUST produce the diagnostic
#   <name>.neg.elisa - minimal, structurally-similar snippet that MUST stay silent
#                       for that diagnostic (the false-positive guard)
#
# Both fixtures must PARSE cleanly (`P 0`) — a mis-parsing "pos" fixture would never
# reach the semantic checker, so its "PASS" would be a silent false negative in this
# harness. We assert `P 0` on every fixture before checking diagnostics.
#
# The expected substring per diagnostic is the exact wording rendered by
# diagnostic_message() in src/semantic/semantic_api.elisa (confirmed by hand against
# `./build/parse_report` output when each fixture was authored).
#
# Coverage: this now exercises ~94 of the ~93 check_*.elisa diagnostics (the original
# engine-dependent seed plus a batch closing the 68 previously-uncovered checks — backlog
# Phase A). A handful of checks are covered by dedicated smokes instead (e.g.
# machine_tag_coverage_smoke.sh, flow_strict_census_smoke.sh) or are duplicate
# DiagnosticKinds of an already-listed entry (contract_position == ContractNotFirst,
# contract_result_void == ContractEnsureResultVoid).
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
FIXTURES="$REPO_ROOT/test/fixtures/diagnostics"

source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

[[ -d "$FIXTURES" ]] || { echo "error: missing fixture dir: $FIXTURES" >&2; exit 2; }

# Parallel indexed arrays (name -> exact diagnostic substring expected on the .pos
# fixture and forbidden on the .neg fixture). Deliberately NOT an associative array:
# macOS ships bash 3.2, which predates `declare -A`, and this harness must run under
# the system /bin/bash like every other test/parity script.
NAMES=(
    literal_comparison_impossible
    named_type_mismatch
    invalid_bool_cast
    redundant_cast
    field_immutable_assign
    void_condition
    ordering_non_numeric
    darray_element_mismatch
    struct_pattern_type_mismatch
    match_arm_enum_mismatch
    ungranted_panic
    ungranted_effect_call
    ungranted_extern_effect_call
    unknown_permission_member
    ungranted_forward_inferred_effect_call
    ungranted_inferred_effect_call
    contract_not_first
    contract_ensure_result_void
    dict_key_affine
    set_element_affine
    unused_decreases
    ghost_field_default
    const_enum_storage
    const_enum_value
    raise_without_error_set
    region_annotation_scalar
    region_param_inference_failure
    fresh_shape_return_mismatch
    fresh_shape_argument_mismatch
    destroyed_region_use
    destroyed_region_allocate
    storage_dependency_invalidated
    duplicate_bit_group_member
    named_states_without_derive
    flow_flag_state_machine
    # --- fixtures batch (backlog Phase A items 18-32): 68 previously-uncovered checks ---
    affine_collection
    array_literal_arity
    array_literal_element
    assign_to_loop_var
    call_named_non_function
    call_non_function
    compound_assign_nonnumeric
    const_enum_member_value
    constant_comparison
    constant_condition
    construct_field_type
    dict_key_mismatch
    dict_value_mismatch
    discarded_call_result
    division_by_zero
    double_negation
    duplicate_condition
    duplicate_decorator
    duplicate_dict_key
    duplicate_match_arm
    duplicate_set_element
    duplicate_variant_field
    empty_iterable
    empty_range
    field_access_on_primitive
    firm_arg_type_mismatch
    float_equality
    identical_branches
    identical_logical_operands
    immediate_overwrite
    index_non_indexable
    index_out_of_bounds
    infinite_loop
    literal_arg_type_mismatch
    literal_assign_out_of_range
    logical_constant_operand
    modulo_by_zero
    negated_comparison
    negative_index
    negative_shift
    nonbool_match_guard
    nonnumeric_shift
    oversized_shift
    range_bound_non_integral
    redundant_arithmetic
    redundant_bool_compare
    redundant_continue
    self_arithmetic
    self_assignment
    self_comparison
    set_element_mismatch
    shift_by_zero
    shift_non_integral
    string_index_nonintegral
    ternary_branch_mismatch
    unknown_field_access
    unknown_type_name
    unknown_type_name_generic
    nonbool_condition_container
    nonbool_condition_optional
    container_element_index_mismatch
    loop_element_type
    string_index_element_type
    container_count_condition
    structural_return_condition
    struct_field_structural_type
    container_assign_scalar
    structural_return_mismatch
    membership_rhs_container
    darray_push_type_mismatch
    dict_index_key_mismatch
    dict_index_scalar_projection
    param_structural_type
    container_comparison
    invalid_ctor_cast
    scoped_shadowing_type
    qualified_call_return_type
    nested_darray_literal_element
    namespace_used_as_value
    unused_expression
    void_argument
    void_collection_element
    void_field_access
    void_index
    void_match_scrutinee
    void_operand
    void_unary_operand
    void_value_use
    ordering_non_numeric_tuple
    tuple_scalar_element_mismatch
    tuple_pattern_arity
    or_pattern_binding_mismatch
    tuple_var_scalar_mismatch
    tuple_return_scalar_mismatch
    tuple_arg_scalar_mismatch
    tuple_var_ordering
    tuple_var_arithmetic
    tuple_var_shift
    tuple_var_compound_assign
    region_aggregate_return_escape
    region_field_return_escape
    region_branch_field_return_escape
    region_match_return_escape
    region_block_return_escape
    region_index_return_escape
    region_match_local_return_escape
    region_branch_tainted_aggregate_return
    region_nested_growth_escape
    region_param_growth_escape
    container_var_scalar_mismatch
    container_var_ordering
    optional_var_scalar_mismatch
    container_count_scalar_mismatch
    logical_structural_operand
    nominal_arg_scalar_mismatch
    field_arg_to_mutable_ref
    ref_arg_value_param
    generic_operator_no_bound
    parallel_rebind_threaded
    tuple_destructure_arity
    region_return_escape
    region_return_dependency
    private_global_access
    local_view_escape
    array_literal_element_return
    array_literal_element_void_return
    try_propagation_module_scope
    region_qualifier_out_of_scope
    optional_result_payload_compare
    arena_grow_escape
    top_level_or_pattern_bindings
    wildcard_arm_not_final
    unreachable_variant_arm
    narrowed_arg_enum_declared
    unknown_variant_pattern
    unknown_variant_value
    non_exhaustive_catch
    value_block_jump_out
    value_block_scope_order
    value_block_shadow_declares
    rebind_discard_target
    static_string_binding_return
    static_string_binding_argument
    static_string_binding_cstr_argument
    static_string_binding_declaration
    static_string_binding_ternary
    container_literal_block_tail
    discarded_loop_value
    # --- rule R (2026-09-22): the TYPE's `mutable` is the write capability ---
    ref_rebind_value
    ref_legacy_readonly_source
    ref_argument_capability
    ref_readonly_path
    ref_global_capability
    ref_null_narrowing
    ref_byte_pointer_store
    ref_builtin_struct_field
    ref_cast_capability
    ref_cast_argument
    ref_cstr_out_param
    string_family_decl
    string_family_assign
    string_family_arg
    string_family_return
    string_family_push
    string_family_field
    string_family_ternary
    string_family_optional
    element_assign_wording
    field_assign_wording
    internal_runtime_carrier_param
    aggregate_reference_return_escape
    aggregate_reference_return_local
    aggregate_reference_return_helper_escape
    aggregate_reference_return_helper_chain
    aggregate_reference_return_helper_local
    aggregate_reference_return_helper_assignment
    aggregate_reference_multiple_lenders_escape
    aggregate_reference_block_local_escape
    aggregate_reference_field_return_escape
    aggregate_reference_field_assign_escape
    aggregate_reference_match_return_escape
    aggregate_reference_loop_return_escape
    aggregate_reference_branch_return_escape
)
EXPECTS=(
    "integer literal 300 does not fit in u8"
    "variable \"q\" expects P, got int"
    "invalid cast from bool to i64"
    "redundant \`.cast[i32]\`: the operand already has type i32; remove the cast"
    "field \"a\" is immutable"
    "condition must be bool, got void"
    "comparison requires numeric operands"
    "darray literal element expects i64, got static u8"
    "struct pattern expects struct \"Q\", got \"P\""
    "match arm expects enum \"E\", got \"G\""
    "warning: panic requires can[Abort]"
    "call to \"g\" requires can[Abort]"
    "call to \"emit\" requires can[Console]"
    "permission \"Console\" has no member \"Read\""
    "call to \"callee\" requires can[Console]"
    "call to \"h\" requires can[Abort]"
    "must be the first statements of the function body"
    "undefined identifier \"result\""
    "dict keys cannot contain linear handles, got Guard"
    "set elements cannot contain linear handles, got Guard"
    "termination clause is unused"
    "cannot have a default value: it is verification-only"
    "storage type must be an explicit integer type, got bool"
    "value 300 does not fit storage type u8"
    "raise requires the current function to return an error union"
    "region annotation \`@owner\` is only valid on a function return type; named values do not carry an independent region"
    "cannot be returned with a region-less type"
    "return type expects darray[i32, row], got darray[i32, shape_out#1]"
    "argument 2 to \"same\" expects darray[i32, pair], got darray[i32, shape_after#3]"
    "region dependency facts were invalidated by destroy of region \"scratch\""
    "cannot allocate from destroyed region \"scratch\""
    "storage dependency facts were invalidated by darray push"
    "duplicate packed group member \"b\" in H.flags"
    "declares named states but is missing a derive state: block"
    "written in multiple branches and read after the join"
    # --- matching expected substrings for the batch above (index-aligned) ---
    "dict keys cannot contain linear handles, got Guard"
    "array literal expects 3 elements, got 2"
    "array literal element expects i64, got static u8"
    "assignment to loop variable \"i\" has no effect on iteration"
    "cannot call non-function value of type Point"
    "cannot call non-function value of type i64"
    "augmented assignment requires numeric operands"
    "const enum member \"Color\".\"Red\" value 300 does not fit storage type u8"
    "constant comparison is always false"
    "condition is always true"
    "struct literal field \"a\" expects i64, got static u8"
    "dict literal key 0 has type static u8&, expected i64"
    "dict literal value 0 has type static u8&, expected i64"
    "result of \"compute\" (returns i64) is discarded; assign it or discard explicitly with _ ="
    "division by zero"
    "double negation has no effect; use the value directly"
    "duplicate condition: this branch repeats an earlier condition and can never run"
    "duplicate @hot annotation on function \"f\" (first seen at line 1:2)"
    "dict literal has a duplicate key \"\""
    "match arm \"1\" is unreachable because an earlier arm already matches it"
    "set literal has a duplicate element \"\""
    "duplicate payload field \"x\" in enum variant \"E\".\"A\""
    "empty list literal requires an expected array or darray type"
    "for loop over an empty range never executes"
    "field access requires struct type, got i64"
    "argument 1 to \"g\" expects i64, got cstr"
    "floating-point equality comparison is unreliable; use a tolerance"
    "if and else branches are identical"
    "identical operands on both sides of \"and\""
    "value assigned to x is immediately overwritten"
    "indexing requires string, array, view, packed store, or reference type, got i64"
    "constant index 5 out of bounds for i64[3]"
    "'while true' loop never exits (no break or return in its body)"
    "argument 1 to \"g\" expects i64, got static u8"
    "integer literal 300 does not fit in u8"
    "logical operator with constant boolean operand"
    "modulo by zero"
    "negated equality comparison; use the opposite operator"
    "constant index -1 out of bounds for int[3]"
    "shift count is negative"
    "match arm guard must be bool, got i64"
    "operator requires numeric operands"
    "shift count is out of range for every integer width (valid range 0..63)"
    "for loop range requires integral bounds, got f64 and int"
    "redundant arithmetic: the literal operand makes this operation a no-op or a constant"
    "redundant comparison to a boolean literal; use the value (or its negation) directly"
    "redundant continue at end of loop body"
    "arithmetic of \"x\" with itself always yields a constant"
    "has no effect: target and value are identical"
    "with itself is always the same"
    "set literal element 0 has type static u8&, expected i64"
    "shift by zero has no effect"
    "operator requires integral operands"
    "index must be integral, got f64"
    "ternary branches are incompatible: i64 and static u8"
    "has no field \"z\""
    "unknown type \"mysterytype\""
    "unknown type \"mysterytype\""
    "if condition must be bool, got darray"
    "while condition must be bool, got i64"
    "variable \"n\" expects bool, got i64"
    "operator requires numeric operands"
    "variable \"x\" expects bool, got char"
    "if condition must be bool, got usize"
    "if condition must be bool, got darray"
    "if condition must be bool, got darray"
    "cannot assign int to darray[i64]"
    "return type expects darray[i64], got int"
    "membership operator requires a list literal or tokenset on the right-hand side, got darray[cstr]"
    "darray push expects i64, got static u8"
    "dict index expects key of type i64, got static u8"
    "optional reference to dictionary value"
    "if condition must be bool, got darray"
    "cannot compare darray[i64] and int"
    "invalid cast from int to bool"
    "operator requires numeric operands"
    "variable \"n\" expects bool, got i64"
    "darray literal element expects i64, got static u8"
    "\"M\" is a namespace; write M::geti"
    "expression statement has no effect; its result is discarded"
    "argument 1 to \"take\" expects i64, got void"
    "darray literal element expects i64, got void"
    "field access requires struct type, got void"
    "indexing requires string, array, view, packed store, or reference type, got void"
    "match requires an enum, const enum, error set, optional, integer, string, tuple, sequence, or struct value, got void"
    "operator requires numeric operands"
    "unary operator requires numeric operand"
    "cannot bind void expression to \"y\" (the initializer produces no value)"
    "comparison requires numeric operands"
    "darray literal element expects i64, got (_0: int, _1: int)"
    "tuple pattern expects 2 elements, got 3"
    "or-pattern alternatives must bind the same names"
    "variable \"x\" expects i64, got (first: i64, second: i64)"
    "return type expects i64, got (first: i64, second: i64)"
    "argument 1 to \"g\" expects i64, got (first: i64, second: i64)"
    "comparison requires numeric operands"
    "operator requires numeric operands"
    "operator requires numeric operands"
    "augmented assignment requires numeric operands"
    "cannot return value: region dependency facts include local region"
    "cannot return value: region dependency facts include local region"
    "cannot return value: region dependency facts include local region"
    "escapes via return; the region is freed at scope exit"
    "escapes via return; the region is freed at scope exit"
    "cannot return value: region dependency facts include local region"
    "match requires an enum"
    "value backed by scope-owned region \"scratch\" escapes via return; the region is freed at block exit"
    "darray push allocates into function-scoped region"
    "darray push allocates into function-scoped region"
    "variable \"x\" expects i64, got darray[i64]"
    "comparison requires numeric operands"
    "variable \"y\" expects i64, got i64"
    "variable \"n\" expects bool, got usize"
    "logical operator requires bool operands"
    "argument 1 to \"g\" expects i64, got Box"
    "argument 1 to \"bump\" expects mutable S&, got S"
    "argument 1 to \"sink\" expects C, got mutable C&"
    "operator requires numeric operands"
    "cannot assign (_0: i64, _1: i64) to i64"
    "tuple destructuring expects 3 bindings, got 2"
    "escapes via return; the region is freed at scope exit"
    "cannot return value: region dependency facts include local region \"r\""
    "\"A.counter\" is private to module \"A\""
    "view of local \"scratch\" escapes via return; the array dies at scope exit"
    "array literal element expects i64, got static u8"
    "array literal element expects void, got int"
    "cannot propagate AErr from a function returning BErr"
    "unknown region qualifier \"a\""
    "cannot compare i64? and i64: unwrap the optional first"
    "grows a non-local darray from local arena \"arena\""
    "top-level or-pattern alternatives that bind names are not supported"
    "wildcard match arm must be the final arm"
    "is unreachable because an earlier arm already matches it"
    "argument 1 to \"require_right\" expects Right, got Root"
    "enum \"Shape\" has no variant \"Nope\""
    "enum \"Shape\" has no variant \"Nope\""
    "non-exhaustive catch over Problem; missing Problem.Second"
    "may not jump out of a value block (docs/119 E5)"
    "undefined identifier \"z\""
    "value block may not mutate the outer binding \"x\" (docs/119 E4)"
    "undefined assignment target \"_\" (use = to introduce a new local; <- requires an existing mutable target)"
    "return type expects sview, got static u8&"
    "argument 1 to \"take\" expects sview, got static u8&"
    "argument 1 to \"take_c\" expects cstr, got static u8&"
    "variable \"t\" expects sview, got static u8&"
    "ternary branches are incompatible: static u8& and sview"
    "darray literal has no region to allocate in"
    "accumulator loop result \`valid\` is discarded; make the loop the final expression of its block"
    # --- rule R (2026-09-22) ---
    "cannot assign int to i64&"
    "\"r\" was initialized from a read-only reference, so its \`mutable\` makes it rebindable, not writable"
    "argument 1 to \"poke\" expects mutable u8&, got static u8&"
    "cannot mutate through readonly ref"
    "global \"g\" expects mutable u8&, got static u8&"
    "argument 1 to \"poke\" expects mutable void&, got void&"
    "cannot store a byte pointer (static u8&) through a byte reference"
    "\"region\" was initialized from a read-only reference, so its \`mutable\` makes it rebindable, not writable"
    "cannot assign void& to mutable void&?"
    "argument 1 to \"poke\" expects mutable void&, got void&"
    "cannot assign int to cstr"
    "variable \"a\" expects sview, got cstr"
    "cannot assign sview to cstr"
    "argument 1 to \"take\" expects darray[u8], got cstr"
    "return type expects cstr, got darray[u8]"
    "darray push expects sview, got cstr"
    "struct literal field \"name\" expects sview, got cstr"
    "ternary branches are incompatible: cstr and sview"
    "variable \"a\" expects sview?, got cstr"
    "cannot assign bool to i64"
    "cannot assign bool to i64"
    "internal runtime carrier type \"DynArrayView\" is not supported in user-facing code"
    "returning an aggregate or helper result that contains a reference into function-local storage"
    "returning an aggregate or helper result that contains a reference into function-local storage"
    "returning an aggregate or helper result that contains a reference into function-local storage"
    "returning an aggregate or helper result that contains a reference into function-local storage"
    "returning an aggregate or helper result that contains a reference into function-local storage"
    "returning an aggregate or helper result that contains a reference into function-local storage"
    "returning an aggregate or helper result that contains a reference into function-local storage"
    "returning an aggregate or helper result that contains a reference into function-local storage"
    "returning an aggregate or helper result that contains a reference into function-local storage"
    "returning an aggregate or helper result that contains a reference into function-local storage"
    "returning an aggregate or helper result that contains a reference into function-local storage"
    "returning an aggregate or helper result that contains a reference into function-local storage"
    "returning an aggregate or helper result that contains a reference into function-local storage"
)

total=0
failed=0

check_parses() {
    local file="$1" out="$2"
    if ! grep -qE '^P 0$' <<< "$out"; then
        echo "  FAIL $(basename "$file"): fixture failed to parse cleanly (expected 'P 0'):" >&2
        echo "$out" | sed 's/^/    /' >&2
        return 1
    fi
    return 0
}

run_case() {
    local name="$1" kind="$2" file="$3" expect="$4"
    total=$((total + 1))
    [[ -f "$file" ]] || { echo "  FAIL $name.$kind: missing fixture $file" >&2; failed=$((failed + 1)); return; }

    local out
    out="$("$RPT" < "$file" 2>&1)"

    if ! check_parses "$file" "$out"; then
        failed=$((failed + 1))
        return
    fi

    if [[ "$kind" == "pos" ]]; then
        if grep -qF "$expect" <<< "$out"; then
            echo "  PASS $name.pos (fired: \"$expect\")"
        else
            echo "  FAIL $name.pos: expected diagnostic not found" >&2
            echo "    expected substring: $expect" >&2
            echo "    actual output:" >&2
            echo "$out" | sed 's/^/      /' >&2
            failed=$((failed + 1))
        fi
    else
        if grep -qF "$expect" <<< "$out"; then
            echo "  FAIL $name.neg: diagnostic fired but must stay silent" >&2
            echo "    forbidden substring: $expect" >&2
            echo "    actual output:" >&2
            echo "$out" | sed 's/^/      /' >&2
            failed=$((failed + 1))
        else
            echo "  PASS $name.neg (silent, as expected)"
        fi
    fi
}

num_diagnostics=${#NAMES[@]}
echo "diagnostics smoke: $num_diagnostics diagnostics, $((num_diagnostics * 2)) fixtures"
echo

index=0
while [[ "$index" -lt "$num_diagnostics" ]]; do
    name="${NAMES[$index]}"
    expect="${EXPECTS[$index]}"
    echo "-- $name --"
    run_case "$name" pos "$FIXTURES/$name.pos.elisa" "$expect"
    run_case "$name" neg "$FIXTURES/$name.neg.elisa" "$expect"
    index=$((index + 1))
done

echo "-- region_returned_stored_borrow --"
run_case region_returned_stored_borrow pos "$REPO_ROOT/test/repro/region_returned_stored_borrow.pos.elisa" "cannot be returned with a region-less type"
run_case region_returned_stored_borrow neg "$REPO_ROOT/test/repro/region_returned_stored_borrow.neg.elisa" "cannot be returned with a region-less type"

echo "-- view_return_escape --"
region_return_msg="value escapes its \`in auto:\` scope via return; the inferred region is freed at scope exit"
for escape_shape in darray binding tail tuple struct_field; do
    run_case "view_return_escape_$escape_shape" pos "$FIXTURES/view_return_escape_$escape_shape.pos.elisa" "$region_return_msg"
done
run_case view_return_escape neg "$FIXTURES/view_return_escape.neg.elisa" "$region_return_msg"
run_case local_view_escape_binding pos "$FIXTURES/local_view_escape_binding.pos.elisa" "view of local \"v\" escapes via return; the array dies at scope exit"
run_case view_return_escape neg "$FIXTURES/view_return_escape.neg.elisa" "escapes via return; the array dies at scope exit"
run_case return_ref_local_in_block pos "$FIXTURES/return_ref_local_in_block.pos.elisa" "returning a reference into function-local storage"
run_case view_return_escape neg "$FIXTURES/view_return_escape.neg.elisa" "returning a reference into function-local storage"
echo "-- affine_move_sites --"
run_case affine_move_nested_call pos "$FIXTURES/affine_move_nested_call.pos.elisa" 'linear value "t" must be moved explicitly before argument to call "sink"'
run_case affine_move_struct_field pos "$FIXTURES/affine_move_struct_field.pos.elisa" 'linear value "t" must be moved explicitly before move into struct literal field "a"'
run_case affine_move_tuple_element pos "$FIXTURES/affine_move_tuple_element.pos.elisa" 'linear value "t" must be moved explicitly before move into tuple element "_0"'
run_case affine_move_array_element pos "$FIXTURES/affine_move_array_element.pos.elisa" 'linear value "t" must be moved explicitly before move into array literal element'
run_case affine_move_darray_literal pos "$FIXTURES/affine_move_darray_literal.pos.elisa" 'linear value "t" must be moved explicitly before move into darray literal element'
run_case affine_move_darray_push pos "$FIXTURES/affine_move_darray_push.pos.elisa" 'linear value "t" must be moved explicitly before move into darray push'
run_case affine_move_sites neg "$FIXTURES/affine_move_sites.neg.elisa" "must be moved explicitly"
run_case affine_move_enum_payload pos "$FIXTURES/affine_move_enum_payload.pos.elisa" 'linear value "t" must be moved explicitly before move into enum payload "Box.Full" argument 1'
run_case affine_move_enum_payload_label pos "$FIXTURES/affine_move_enum_payload_label.pos.elisa" 'linear value "u" must be moved explicitly before move into enum payload "Box.Tagged.h"'
run_case affine_move_discard pos "$FIXTURES/affine_move_discard.pos.elisa" 'linear value "t" must be moved explicitly before discard'
run_case affine_move_enum_payload neg "$FIXTURES/affine_move_enum_payload.neg.elisa" "must be moved explicitly"
run_case affine_move_dict_put pos "$FIXTURES/affine_move_dict_put.pos.elisa" 'linear value "t" must be moved explicitly before move into dict put'
run_case affine_move_record_update pos "$FIXTURES/affine_move_record_update.pos.elisa" 'linear value "t" must be moved explicitly before move into record update field "a"'
run_case affine_move_record_update pos "$FIXTURES/affine_move_record_update.pos.elisa" 'value containing linear handles "p" must be moved explicitly before record update'
run_case affine_move_dict_record neg "$FIXTURES/affine_move_dict_record.neg.elisa" "must be moved explicitly"
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'linear value "p.h" must be moved explicitly before move into local "u"'
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'linear value "o.p.h" must be moved explicitly before argument to call "sink"'
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'linear value "p.h" must be moved explicitly before return'
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'linear value "p.h" must be moved explicitly before assignment'
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'linear value "p.h" must be moved explicitly before move into struct literal field "h"'
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'must be moved explicitly before move into enum payload "Box.Full" argument 1'
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'linear value "<value>" must be moved explicitly before argument to call "sink"'
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'linear value "<value>" must be moved explicitly before move into local "u"'
run_case affine_move_projection neg "$FIXTURES/affine_move_projection.neg.elisa" "must be moved explicitly"
echo "-- affine_move_in_loop --"
loop_msg='declared outside the loop is consumed on every iteration'
run_case affine_move_in_for_loop pos "$FIXTURES/affine_move_in_for_loop.pos.elisa" "$loop_msg"
run_case affine_move_in_while_loop pos "$FIXTURES/affine_move_in_while_loop.pos.elisa" "$loop_msg"
run_case affine_move_in_loop_drop pos "$FIXTURES/affine_move_in_loop_drop.pos.elisa" "$loop_msg"
run_case affine_use_after_loop_move pos "$FIXTURES/affine_use_after_loop_move.pos.elisa" 'linear handle value "t" cannot be used after ownership was consumed'
run_case affine_use_in_loop_after_move pos "$FIXTURES/affine_use_in_loop_after_move.pos.elisa" 'linear handle value "t" cannot be used after ownership was consumed'
run_case affine_move_in_loop neg "$FIXTURES/affine_move_in_loop.neg.elisa" "$loop_msg"
run_case affine_move_in_loop neg "$FIXTURES/affine_move_in_loop.neg.elisa" "after ownership was consumed"
run_case affine_move_after_if_move pos "$FIXTURES/affine_move_after_if_move.pos.elisa" 'linear handle value "t" cannot be used after ownership was consumed'
run_case affine_use_after_if_else_move pos "$FIXTURES/affine_use_after_if_else_move.pos.elisa" 'linear handle value "t" cannot be used after ownership was consumed'
run_case affine_move_conditional_in_loop pos "$FIXTURES/affine_move_conditional_in_loop.pos.elisa" "$loop_msg"
run_case affine_move_conditional neg "$FIXTURES/affine_move_conditional.neg.elisa" "after ownership was consumed"
run_case affine_move_conditional neg "$FIXTURES/affine_move_conditional.neg.elisa" "$loop_msg"
echo "-- captured_loop_checks --"
cl_pos="$FIXTURES/captured_loop_checks.pos.elisa"
cl_neg="$FIXTURES/captured_loop_checks.neg.elisa"
run_case captured_loop_checks pos "$cl_pos" 'linear value "t" must be moved explicitly before argument to call "sink"'
run_case captured_loop_checks pos "$cl_pos" 'cannot mutate "xs" while it is being iterated'
run_case captured_loop_checks pos "$cl_pos" 'linear value "k" must be consumed before scope exit'
run_case captured_loop_checks pos "$cl_pos" 'linear handle value "u" cannot be used after ownership was consumed'
run_case captured_loop_checks neg "$cl_neg" "must be moved explicitly"
run_case captured_loop_checks neg "$cl_neg" "while it is being iterated"
run_case captured_loop_checks neg "$cl_neg" "must be consumed before scope exit"
run_case captured_loop_checks neg "$cl_neg" "cannot be used after ownership was consumed"
echo "-- linear_partial_consume --"
lp_pos="$FIXTURES/linear_partial_consume.pos.elisa"
lp_neg="$FIXTURES/linear_partial_consume.neg.elisa"
run_case linear_partial_consume pos "$lp_pos" 'linear value "g" must be consumed before scope exit'
run_case linear_partial_consume pos "$lp_pos" 'linear value "h" must be consumed before scope exit'
run_case linear_partial_consume pos "$lp_pos" 'linear value "m" must be consumed before scope exit'
run_case linear_partial_consume neg "$lp_neg" "must be consumed before scope exit"
run_case linear_partial_consume neg "$lp_neg" "cannot be used after ownership was consumed"
echo "-- value_block_nested_loop --"
vn_pos="$FIXTURES/value_block_nested_loop.pos.elisa"
vn_neg="$FIXTURES/value_block_nested_loop.neg.elisa"
run_case value_block_nested_loop pos "$vn_pos" 'value block may not mutate the outer binding "outer" (docs/119 E4)'
run_case value_block_nested_loop pos "$vn_pos" 'value block may not mutate the outer binding "total" (docs/119 E4)'
run_case value_block_nested_loop pos "$vn_pos" 'value block may not mutate the outer binding "deep" (docs/119 E4)'
run_case value_block_nested_loop pos "$vn_pos" 'value block may not mutate the outer binding "ys" through a call'
run_case value_block_nested_loop neg "$vn_neg" "value block may not mutate"
run_case value_block_nested_loop neg "$vn_neg" "names no binding in scope"
echo "-- call_argument_alias --"
ca_pos="$FIXTURES/call_argument_alias.pos.elisa"
ca_neg="$FIXTURES/call_argument_alias.neg.elisa"
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "x" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "read_write" passes "y" to mutable reference parameter "a" while argument for "b" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "grow" passes "v" to mutable reference parameter "v" while argument for "first" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "whole" passes "p" to mutable reference parameter "p" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "q" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "w" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "z" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "r" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "s" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "u" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "t" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "grow" passes "vv" to mutable reference parameter "v" while argument for "first" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "poke" passes "c" to mutable reference parameter "other" while argument for "self" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "m" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias neg "$ca_neg" "refers to overlapping memory"
echo "-- affine_container_reference --"
acr_pos="$FIXTURES/affine_container_reference.pos.elisa"
acr_neg="$FIXTURES/affine_container_reference.neg.elisa"
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got darray[Handle]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got view[Handle]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got Handle[2]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got dict[i64, Handle]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got darray[darray[Handle]]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got darray[Handle?]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got darray[Pair]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got Box[Handle]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got Pair[2]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got darray[Handle[2]]&'
run_case affine_container_reference neg "$acr_neg" "references to values containing linear handles"
echo "-- affine_container_address --"
aca_pos="$FIXTURES/affine_container_address.pos.elisa"
aca_neg="$FIXTURES/affine_container_address.neg.elisa"
aca_out="$("$RPT" < "$aca_pos" 2>&1)"
total=$((total + 1))
if [[ "$(grep -c 'cannot take address of value containing linear handles' <<< "$aca_out")" == 8 ]]; then
    echo "  PASS affine_container_address.pos (all 8 address sites fired)"
else
    echo "  FAIL affine_container_address.pos: want all 8 address sites: $aca_out" >&2
    failed=$((failed + 1))
fi
run_case affine_container_address neg "$aca_neg" "cannot take address"

echo "-- affine_darray_consume --"
adc_pos="$FIXTURES/affine_darray_consume.pos.elisa"
adc_neg="$FIXTURES/affine_darray_consume.neg.elisa"
adc_out="$("$RPT" < "$adc_pos" 2>&1)"
total=$((total + 1))
if [[ "$(grep -c 'must be consumed before scope exit' <<< "$adc_out")" == 6 && "$(grep -c 'would drop must-consume element' <<< "$adc_out")" == 5 ]]; then
    echo "  PASS affine_darray_consume.pos (6 unconsumed containers, 5 element drops)"
else
    echo "  FAIL affine_darray_consume.pos: want 6 unconsumed + 5 drops: $adc_out" >&2
    failed=$((failed + 1))
fi
run_case affine_darray_consume pos "$adc_pos" 'darray of must-consume elements (drain with `for x in move c:`) "xs" must be consumed before scope exit'
run_case affine_darray_consume pos "$adc_pos" 'darray of must-consume elements (drain with `for x in move c:`) "d" must be consumed before scope exit'
run_case affine_darray_consume pos "$adc_pos" 'indexed assignment would drop must-consume element(s) of type Handle'
run_case affine_darray_consume pos "$adc_pos" 'darray clear would drop must-consume element(s) of type Tracked'
run_case affine_darray_consume neg "$adc_neg" "must-consume"

echo "-- affine_set_key --"
ask_pos="$FIXTURES/affine_set_key.pos.elisa"
ask_neg="$FIXTURES/affine_set_key.neg.elisa"
run_case affine_set_key pos "$ask_pos" "set elements cannot contain linear handles, got Handle?"
run_case affine_set_key pos "$ask_pos" "dict keys cannot contain linear handles, got Pair"
run_case affine_set_key pos "$ask_pos" "set elements cannot contain linear handles, got darray[Handle]"
run_case affine_set_key pos "$ask_pos" "dict keys cannot contain linear handles, got Handle?"
run_case affine_set_key neg "$ask_neg" "cannot contain linear handles"
run_case affine_set_key neg "$ask_neg" "must be consumed before scope exit"

echo "-- affine_comprehension --"
acm_pos="$FIXTURES/affine_comprehension.pos.elisa"
acm_neg="$FIXTURES/affine_comprehension.neg.elisa"
run_case affine_comprehension pos "$acm_pos" "list comprehension value iteration does not support affine element type Handle"
run_case affine_comprehension pos "$acm_pos" "list comprehension value iteration does not support affine element type Pair"
run_case affine_comprehension pos "$acm_pos" "linear value \"g\" must be moved explicitly before move into list comprehension element"
run_case affine_comprehension neg "$acm_neg" "list comprehension"
run_case affine_comprehension neg "$acm_neg" "consumed on every iteration"
run_case affine_comprehension neg "$acm_neg" "must be consumed before scope exit"
run_case affine_comprehension_repeat pos "$FIXTURES/affine_comprehension_repeat.pos.elisa" "consumed on every iteration"

echo "-- affine_container_return --"
acr_pos="$FIXTURES/affine_container_return.pos.elisa"
acr_neg="$FIXTURES/affine_container_return.neg.elisa"
for acr_name in xs made t ps; do
    run_case affine_container_return pos "$acr_pos" "value containing linear handles \"$acr_name\" must be moved explicitly before return"
    run_case affine_container_return pos "$acr_pos" "\"$acr_name\" must be consumed before scope exit"
done
run_case affine_container_return neg "$acr_neg" "must be moved explicitly before return"
run_case affine_container_return neg "$acr_neg" "must be consumed before scope exit"

echo "-- affine_bulk_copy --"
abc_pos="$FIXTURES/affine_bulk_copy.pos.elisa"
abc_neg="$FIXTURES/affine_bulk_copy.neg.elisa"
for abc_element in Handle Pair; do
    run_case affine_bulk_copy pos "$abc_pos" "darray extend does not support affine element type $abc_element; push elements individually with explicit move"
done
for abc_element in Handle "darray[Handle]"; do
    run_case affine_bulk_copy pos "$abc_pos" "bulk darray push does not support affine element type $abc_element; push elements individually with explicit move"
done
run_case affine_bulk_copy pos "$abc_pos" "query expression value iteration does not support affine element type Handle"
run_case affine_bulk_copy neg "$abc_neg" "darray extend does not support affine element type"
run_case affine_bulk_copy neg "$abc_neg" "bulk darray push does not support affine element type"

echo "-- shift_match_guards --"
guard_pos="$FIXTURES/shift_match_guards.pos.elisa"
guard_neg="$FIXTURES/shift_match_guards.neg.elisa"
guard_expectations=(
    "shift count is out of range for every integer width (valid range 0..63)"
    "shift count is negative"
    "shift by zero has no effect"
    "operator requires numeric operands"
    "operator requires integral operands"
)
for guard_case in pos neg; do
    guard_file="$guard_pos"
    [[ "$guard_case" == "neg" ]] && guard_file="$guard_neg"
    total=$((total + ${#guard_expectations[@]}))
    guard_out="$("$RPT" < "$guard_file" 2>&1)"
    if ! check_parses "$guard_file" "$guard_out"; then
        failed=$((failed + ${#guard_expectations[@]}))
        continue
    fi
    for guard_expect in "${guard_expectations[@]}"; do
        guard_count="$(grep -oF -- "$guard_expect" <<< "$guard_out" | wc -l | tr -d ' ')"
        if [[ "$guard_case" == "pos" && "$guard_count" -ge 2 ]]; then
            echo "  PASS shift_match_guards.pos (found $guard_count: \"$guard_expect\")"
        elif [[ "$guard_case" == "neg" && "$guard_count" -eq 0 ]]; then
            echo "  PASS shift_match_guards.neg (silent: \"$guard_expect\")"
        else
            echo "  FAIL shift_match_guards.$guard_case for \"$guard_expect\" (found $guard_count)" >&2
            echo "$guard_out" | sed 's/^/    /' >&2
            failed=$((failed + 1))
        fi
    done
done

echo
echo "diagnostics smoke: $((total - failed))/$total fixtures PASS"
if [[ "$failed" -gt 0 ]]; then
    echo "diagnostics smoke FAIL: $failed fixture(s) failed" >&2
    exit 1
fi
echo "diagnostics smoke OK: all fixtures behave as expected"
