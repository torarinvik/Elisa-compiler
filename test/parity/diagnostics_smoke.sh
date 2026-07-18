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
    duplicate_pattern_binding
    duplicate_set_element
    duplicate_variant_field
    empty_iterable
    empty_range
    field_access_on_primitive
    firm_arg_type_mismatch
    float_equality
    identical_branches
    identical_logical_operands
    if_value_missing_else
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
    container_var_scalar_mismatch
    container_var_ordering
    optional_var_scalar_mismatch
    container_count_scalar_mismatch
    logical_structural_operand
)
EXPECTS=(
    "comparison is always vacuous for u8"
    "variable 'q' expects P, got int"
    "invalid cast from bool to i64"
    "redundant \`.cast[i32]\`: the operand already has type i32; remove the cast"
    "field 'a' is immutable"
    "condition must be bool, got void"
    "comparison requires numeric operands"
    "darray literal element expects i64, got static u8"
    "struct pattern expects struct 'Q', got 'P'"
    "match arm expects enum 'E', got 'G'"
    "warning: panic requires can[Abort]"
    "call to \"g\" requires can[Abort]"
    "call to \"emit\" requires can[Console]"
    "permission \"Console\" has no member \"Read\""
    "call to \"callee\" requires can[Console]"
    "call to \"h\" requires can[Abort]"
    "must be the first statements of the function body"
    "returns void (no result value to bind)"
    "dict keys cannot contain linear handles, got Guard"
    "set elements cannot contain linear handles, got Guard"
    "termination clause is unused"
    "cannot have a default value (it is verification-only"
    "storage type must be an explicit integer type, got bool"
    "value 300 does not fit storage type u8"
    "raise requires the current function to return an error union"
    "the scalar type i32 cannot carry a region"
    "cannot be returned with a region-less type"
    "return type expects row[0], got shape_out[0]"
    "return type expects pair[0], got pair[0]"
    "region dependency facts were invalidated"
    "region \"scratch\" was destroyed"
    "storage dependency facts were invalidated"
    "duplicate packed group member 'b' in H.flags"
    "declares named states but is missing a derive state: block"
    "written in multiple branches and read after the join"
    # --- matching expected substrings for the batch above (index-aligned) ---
    "dict keys cannot contain linear handles, got Guard"
    "array literal expects 3 elements, got 2"
    "array literal element expects i64, got static u8"
    "assignment to loop variable 'i' has no effect on iteration"
    "cannot call non-function value of type Point"
    "cannot call non-function value of type i64"
    "augmented assignment requires numeric operands"
    "const enum member 'Color'.'Red' value 300 does not fit storage type u8"
    "constant comparison is always false"
    "condition is always true"
    "struct literal field 'a' expects i64, got static u8"
    "dict literal key 0 has type static u8, expected i64"
    "dict literal value 0 has type static u8, expected i64"
    "result of 'compute' (returns i64) is discarded; assign it or discard explicitly with _ ="
    "division by zero"
    "double negation has no effect; use the value directly"
    "duplicate condition: this branch repeats an earlier condition and can never run"
    "duplicate decorator 'hot'"
    "dict literal has a duplicate key ''"
    "match arm '1' is unreachable because an earlier arm already matches it"
    "name x bound more than once in pattern"
    "set literal has a duplicate element ''"
    "duplicate payload field 'x' in enum variant 'E.A'"
    "empty list literal requires an expected array or darray type"
    "for loop over an empty range never executes"
    "field access requires struct type, got i64"
    "argument 1 to 'g' expects i64, got cstr"
    "floating-point equality comparison is unreliable; use a tolerance"
    "if and else branches are identical"
    "identical operands on both sides of 'and'"
    "an \`if\` used as a value must have a final \`else\`"
    "value assigned to x is immediately overwritten"
    "indexing requires string, array, view, packed store, or reference type, got i64"
    "constant index 5 out of bounds for i64[3]"
    "'while true' loop never exits (no break or return in its body)"
    "argument 1 to 'g' expects i64, got static u8"
    "integer literal 300 does not fit in u8"
    "logical operator with constant boolean operand"
    "modulo by zero"
    "negated equality comparison; use the opposite operator"
    "constant index -1 out of bounds for int[3]"
    "shift count is negative"
    "match guard must be bool, got i64"
    "operator requires numeric operands"
    "shift count is out of range for every integer width (valid range 0..63)"
    "range bounds must be integral, got float"
    "redundant arithmetic: the literal operand makes this operation a no-op or a constant"
    "redundant comparison to a boolean literal; use the value (or its negation) directly"
    "redundant continue at end of loop body"
    "arithmetic of 'x' with itself always yields a constant"
    "has no effect: target and value are identical"
    "with itself is always the same"
    "set literal element 0 has type static u8, expected i64"
    "shift by zero has no effect"
    "operator requires integral operands"
    "index must be integral, got f64"
    "ternary branches are incompatible: i64 and static u8"
    "has no field 'z'"
    "unknown type 'mysterytype'"
    "unknown type 'mysterytype'"
    "if condition must be bool, got container"
    "while condition must be bool, got optional"
    "variable 'n' expects bool, got i64"
    "operator requires numeric operands"
    "variable 'x' expects bool, got char"
    "if condition must be bool, got usize"
    "if condition must be bool, got container"
    "if condition must be bool, got container"
    "variable 'xs' expects darray, got int"
    "return type expects darray, got int"
    "membership operator requires a list literal or tokenset on the right-hand side, got container"
    "darray push expects i64, got static u8"
    "dict index expects key of type i64, got string"
    "if condition must be bool, got container"
    "cannot compare darray with int"
    "invalid cast from int to bool"
    "operator requires numeric operands"
    "variable 'n' expects bool, got i64"
    "darray literal element expects i64, got static u8"
    "'M' is a namespace; write M::member"
    "expression statement has no effect; its result is discarded"
    "argument 1 to 'take' expects i64, got void"
    "collection element cannot be void"
    "field access requires struct type, got void"
    "indexing requires string, array, view, packed store, or reference type, got void"
    "match requires an enum, const enum, error set, optional, integer, string, tuple, sequence, or struct value, got void"
    "operator requires numeric operands"
    "unary operator requires numeric operand"
    "cannot bind void expression to 'y'; the initializer produces no value"
    "comparison requires numeric operands"
    "darray literal element expects i64, got tuple"
    "tuple pattern arity does not match the tuple scrutinee"
    "or-pattern alternatives must bind the same names"
    "variable 'x' expects i64, got tuple"
    "return type expects i64, got tuple"
    "argument 1 to 'g' expects i64, got tuple"
    "comparison requires numeric operands"
    "operator requires numeric operands"
    "operator requires numeric operands"
    "augmented assignment requires numeric operands"
    "variable 'x' expects i64, got container"
    "comparison requires numeric operands"
    "variable 'y' expects i64, got optional"
    "variable 'n' expects bool, got usize"
    "logical operator requires bool operands"
)

total=0
failed=0

check_parses() {
    local file="$1" out="$2"
    if ! echo "$out" | grep -qE '^P 0$'; then
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
        if echo "$out" | grep -qF "$expect"; then
            echo "  PASS $name.pos (fired: \"$expect\")"
        else
            echo "  FAIL $name.pos: expected diagnostic not found" >&2
            echo "    expected substring: $expect" >&2
            echo "    actual output:" >&2
            echo "$out" | sed 's/^/      /' >&2
            failed=$((failed + 1))
        fi
    else
        if echo "$out" | grep -qF "$expect"; then
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
