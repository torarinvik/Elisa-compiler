#!/usr/bin/env bash
# Stage0/Stage1 regression for optional types bound through hierarchical enum payloads.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURES="$ROOT/test/fixtures/diagnostics"
STAGE0="${ELISA_OPTIONAL_STAGE0_BIN:-${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}}"
STAGE1="${ELISA_OPTIONAL_STAGE1_BIN:-${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}}"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/elisa-hierarchical-optional.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

[[ -x "$STAGE0" ]] || { echo "missing stage0 compiler: $STAGE0" >&2; exit 2; }
[[ -x "$STAGE1" ]] || { echo "missing stage1 compiler: $STAGE1" >&2; exit 2; }

EXPECTED='argument 1 to "Probe.consume" expects Probe.Expr, got Probe.Expr?'
STAGE1_EXPECTED='got optional'

expect_rejected() {
    local stage="$1" compiler="$2" mode="$3" source="$4" rc=0
    local log="$TMP/$stage-$source.log"
    local expected="$EXPECTED"
    [[ "$stage" == stage0 ]] || expected="$STAGE1_EXPECTED"
    "$compiler" -emit "$mode" -O0 -o "$TMP/$stage-$source.out" "$FIXTURES/$source.elisa" >"$log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]] || ! grep -Fq "$expected" "$log"; then
        echo "FAIL $stage accepted or misdiagnosed $source (exit $rc)" >&2
        cat "$log" >&2
        return 1
    fi
    echo "PASS $stage rejects nullable payload to non-nullable parameter"
}

expect_accepted() {
    local stage="$1" compiler="$2" mode="$3" source="$4" rc=0
    local log="$TMP/$stage-$source.log"
    "$compiler" -emit "$mode" -O0 -o "$TMP/$stage-$source.out" "$FIXTURES/$source.elisa" >"$log" 2>&1 || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        echo "FAIL $stage rejected valid source $source (exit $rc)" >&2
        cat "$log" >&2
        return 1
    fi
    echo "PASS $stage accepts $source"
}

# Stage0 semantic mode avoids its unrelated backend recursion on otherwise-valid
# hierarchical enum layouts. A rejected type mismatch exits before code generation.
expect_rejected stage0 "$STAGE0" semantic hierarchical_optional_enum_payload_mismatch.neg
expect_rejected stage1 "$STAGE1" obj hierarchical_optional_enum_payload_mismatch.neg
expect_rejected stage0 "$STAGE0" semantic hierarchical_optional_enum_payload_mismatch_named.neg
expect_rejected stage1 "$STAGE1" obj hierarchical_optional_enum_payload_mismatch_named.neg

expect_accepted stage0 "$STAGE0" semantic hierarchical_enum_payload_valid
expect_accepted stage1 "$STAGE1" obj hierarchical_enum_payload_valid
expect_accepted stage0 "$STAGE0" semantic hierarchical_optional_enum_payload_forward
expect_accepted stage1 "$STAGE1" obj hierarchical_optional_enum_payload_forward
expect_accepted stage0 "$STAGE0" semantic hierarchical_optional_enum_payload_forward_named
expect_accepted stage1 "$STAGE1" obj hierarchical_optional_enum_payload_forward_named
expect_accepted stage0 "$STAGE0" semantic hierarchical_optional_enum_payload_overload
expect_accepted stage1 "$STAGE1" obj hierarchical_optional_enum_payload_overload
expect_accepted stage0 "$STAGE0" semantic hierarchical_optional_enum_payload_generic
expect_accepted stage1 "$STAGE1" obj hierarchical_optional_enum_payload_generic
expect_accepted stage0 "$STAGE0" semantic hierarchical_optional_enum_payload_refined
expect_accepted stage1 "$STAGE1" obj hierarchical_optional_enum_payload_refined
