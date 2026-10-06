#!/usr/bin/env bash
# Differential regression for optional enum payload bindings across module lookup.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURES="$ROOT/test/fixtures/diagnostics"
STAGE0="${ELISA_OPTIONAL_STAGE0_BIN:-${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}}"
STAGE1="${ELISA_OPTIONAL_STAGE1_BIN:-${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}}"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/elisa-optional-enum-payload.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

[[ -x "$STAGE0" ]] || { echo "missing stage0 compiler: $STAGE0" >&2; exit 2; }
[[ -x "$STAGE1" ]] || { echo "missing stage1 compiler: $STAGE1" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

expect_rejected() {
    local stage="$1" compiler="$2" mode="$3" fixture="$4" expected="$5" rc=0
    local log="$TMP/$stage-$fixture.log"
    "$compiler" -emit "$mode" -O0 -o "$TMP/$stage-$fixture.out" "$FIXTURES/$fixture.elisa" >"$log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]] || ! grep -Fq "$expected" "$log"; then
        echo "FAIL $stage accepted or misdiagnosed $fixture (exit $rc)" >&2
        cat "$log" >&2
        return 1
    fi
    echo "PASS $stage rejects $fixture"
}

expect_accepted() {
    local stage="$1" compiler="$2" mode="$3" fixture="$4" rc=0
    local log="$TMP/$stage-$fixture.log"
    "$compiler" -emit "$mode" -O0 -o "$TMP/$stage-$fixture.out" "$FIXTURES/$fixture.elisa" >"$log" 2>&1 || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        echo "FAIL $stage rejected valid source $fixture (exit $rc)" >&2
        cat "$log" >&2
        return 1
    fi
    echo "PASS $stage accepts $fixture"
}

# Stage0 semantic mode avoids unrelated backend declines in hierarchical enum layouts.
# Both invalid fixtures must be rejected by Stage1 before object generation, including when
# the callee is brought into scope with `using`.
expect_rejected stage0 "$STAGE0" semantic hierarchical_optional_enum_payload_mismatch.neg 'got Probe.Expr?'
expect_rejected stage1 "$STAGE1" obj hierarchical_optional_enum_payload_mismatch.neg 'got optional'
expect_rejected stage0 "$STAGE0" semantic imported_consumer_optional_enum_payload_mismatch.neg 'got Expr?'
expect_rejected stage1 "$STAGE1" obj imported_consumer_optional_enum_payload_mismatch.neg 'got optional'
expect_rejected stage0 "$STAGE0" semantic imported_optional_enum_payload_expression_mismatch.neg 'got Expr?'
expect_rejected stage1 "$STAGE1" obj imported_optional_enum_payload_expression_mismatch.neg 'got optional'
expect_rejected stage0 "$STAGE0" semantic hierarchical_optional_enum_payload_mismatch_named.neg 'got Probe.Expr?'
expect_rejected stage1 "$STAGE1" obj hierarchical_optional_enum_payload_mismatch_named.neg 'got optional'

# Keep compatible optional forwarding, exact non-optional payloads, and generic/overloaded
# calls accepted; the added gate must not become a blanket rejection of match-bound values.
for fixture in \
    hierarchical_enum_payload_valid.pos \
    hierarchical_optional_enum_payload_forward.pos \
    hierarchical_optional_enum_payload_generic.pos \
    hierarchical_optional_enum_payload_overload.pos \
    hierarchical_optional_enum_payload_forward_named \
    hierarchical_optional_enum_payload_refined; do
    expect_accepted stage0 "$STAGE0" semantic "$fixture"
    expect_accepted stage1 "$STAGE1" obj "$fixture"
done

echo "optional enum payload Stage0/Stage1 differential OK"
