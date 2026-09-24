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

echo
echo "diagnostics smoke: $((total - failed))/$total fixtures PASS"
if [[ "$failed" -gt 0 ]]; then
    echo "diagnostics smoke FAIL: $failed fixture(s) failed" >&2
    exit 1
fi
echo "diagnostics smoke OK: all fixtures behave as expected"
