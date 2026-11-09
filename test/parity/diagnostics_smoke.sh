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
python3 "$REPO_ROOT/test/proofs/check_signature_contract_owner_identity.py" || {
    echo "signature contract owner proof failed" >&2
    exit 1
}
python3 "$REPO_ROOT/test/proofs/check_extern_signature_contract_owner.py" || {
    echo "extern signature contract owner proof failed" >&2
    exit 1
}
python3 "$REPO_ROOT/test/proofs/check_extern_return_owner_identity.py" || {
    echo "extern return owner proof failed" >&2
    exit 1
}
python3 "$REPO_ROOT/test/proofs/check_backend_extern_ensure_scoped_selection.py" || {
    echo "extern ensure scoped-selection proof failed" >&2
    exit 1
}
python3 "$REPO_ROOT/test/proofs/check_extern_effect_owner_identity.py" || {
    echo "extern effect owner proof failed" >&2
    exit 1
}
python3 "$REPO_ROOT/test/proofs/check_extern_segment_owner_identity.py" || {
    echo "extern segment owner proof failed" >&2
    exit 1
}
python3 "$REPO_ROOT/test/proofs/check_ensures_return_bool_owner.py" || {
    echo "ensures return owner proof failed" >&2
    exit 1
}
python3 "$REPO_ROOT/test/proofs/check_field_default_type_owner_identity.py" || {
    echo "field default owner proof failed" >&2
    exit 1
}
python3 "$REPO_ROOT/test/proofs/check_generic_operator_no_bound_owner_identity.py" || {
    echo "generic operator owner proof failed" >&2
    exit 1
}
python3 "$REPO_ROOT/test/proofs/check_resolve_generic_scope_owner_identity.py" || {
    echo "generic function scope owner proof failed" >&2
    exit 1
}
python3 "$REPO_ROOT/test/proofs/check_thread_generic_owner_identity.py" || {
    echo "thread generic owner proof failed" >&2
    exit 1
}
python3 "$REPO_ROOT/test/proofs/check_region_param_value_arg_owner_identity.py" || {
    echo "region parameter value argument owner proof failed" >&2
    exit 1
}
"$REPO_ROOT/test/parity/protocol_precondition_generic_owner_smoke.sh" || {
    echo "protocol precondition generic owner smoke failed" >&2
    exit 1
}
"$REPO_ROOT/test/parity/unknown_type_generic_owner_smoke.sh" || {
    echo "unknown type generic owner smoke failed" >&2
    exit 1
}
bash "$REPO_ROOT/test/parity/field_access_generic_owner_smoke.sh" || {
    echo "field access generic owner smoke failed" >&2
    exit 1
}

[[ -d "$FIXTURES" ]] || { echo "error: missing fixture dir: $FIXTURES" >&2; exit 2; }

source "$REPO_ROOT/test/parity/diagnostics_fixture_inventory.sh"

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

require_diagnostic_count() {
    local name="$1" file="$2" expect="$3" expected_count="$4"
    total=$((total + 1))
    local out actual
    out="$("$RPT" < "$file" 2>&1)"
    if ! check_parses "$file" "$out"; then
        failed=$((failed + 1))
        return
    fi
    actual="$(grep -Fc "$expect" <<< "$out" || true)"
    if [[ "$actual" -eq "$expected_count" ]]; then
        echo "  PASS $name (saw $actual expected invalidation diagnostics)"
    else
        echo "  FAIL $name: expected $expected_count invalidation diagnostics, saw $actual" >&2
        echo "$out" | sed 's/^/    /' >&2
        failed=$((failed + 1))
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

source "$REPO_ROOT/test/parity/diagnostics_owner_region_cases.sh"
source "$REPO_ROOT/test/parity/diagnostics_affine_storage_cases.sh"

echo "diagnostics smoke: $((total - failed))/$total fixtures PASS"
echo "-- reference_authority_cast --"
# Mirrors stage0 testdata/reference_authority_cast (its .neg = our .pos): hard errors in every mode.
run_case reference_authority_forge pos "$FIXTURES/reference_authority_forge.pos.elisa" "forging a reference from an integer"
run_case reference_authority_upgrade_reborrow pos "$FIXTURES/reference_authority_upgrade_reborrow.pos.elisa" "upgrading a read-only reference to a mutable one"
run_case reference_authority_upgrade_value pos "$FIXTURES/reference_authority_upgrade_value.pos.elisa" "upgrading a read-only reference to a mutable one"
run_case reference_authority_cast neg "$FIXTURES/reference_authority_cast.neg.elisa" "forging a reference from an integer"
run_case reference_authority_cast neg "$FIXTURES/reference_authority_cast.neg.elisa" "upgrading a read-only reference to a mutable one"

if [[ "$failed" -gt 0 ]]; then
    echo "diagnostics smoke FAIL: $failed fixture(s) failed" >&2
    exit 1
fi
echo "diagnostics smoke OK: all fixtures behave as expected"
