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
# This does NOT attempt full coverage of all 78 checks — it seeds a representative,
# engine-dependent subset (checks that ride infer_expression_type / local_type_of and
# are therefore most exposed to a regression in the shared type-inference engine).
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
)
EXPECTS=(
    "comparison is always vacuous for u8"
    "variable 'q' expects P, got int"
    "invalid cast from bool to i64"
    "redundant \`.cast[i32]\`: the operand already has type i32; remove the cast"
    "field 'a' is immutable"
    "condition must be bool, got void"
    "ordering comparison requires numeric operands"
    "darray literal element expects i64, got string"
    "struct pattern expects struct 'Q', got 'P'"
    "match arm expects enum 'E', got 'G'"
    "panic performed with no enclosing effect grant"
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
