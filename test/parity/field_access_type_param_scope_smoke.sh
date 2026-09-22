#!/usr/bin/env bash
# A local shadow of a type-param parameter suppresses field-access diagnostics only
# while that binding is in scope. Both drivers must reject the post-branch invalid
# access and accept the legitimate field access through a branch-local struct.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

STAGE1_BIN="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$REPO_ROOT/build/runtime/elisacore_runtime.o}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

stage1_compile() {
    env -u ELISACORE_BIN -u ELISA_CORE -u REPO_ROOT \
        ELISA_STAGE1_BIN="$STAGE1_BIN" ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" \
        bash "$REPO_ROOT/scripts/elisac_stage1.sh" "$@"
}

expect_reject_both() {
    local fixture="$1" stage0_status=0 stage1_status=0
    "$ELISACORE_BIN" -emit obj -o "$WORK/stage0.o" "$fixture" >"$WORK/stage0.log" 2>&1 || stage0_status=$?
    stage1_compile -emit obj -o "$WORK/stage1.o" "$fixture" >"$WORK/stage1.log" 2>&1 || stage1_status=$?
    [[ "$stage0_status" -eq 1 ]] || { echo "field-access scope smoke FAIL: expected Stage0 semantic rejection (exit 1), got $stage0_status for $fixture" >&2; cat "$WORK/stage0.log" >&2; exit 1; }
    [[ "$stage1_status" -eq 1 ]] || { echo "field-access scope smoke FAIL: expected Stage1 semantic rejection (exit 1), got $stage1_status for $fixture" >&2; cat "$WORK/stage1.log" >&2; exit 1; }
}

expect_accept_both() {
    local fixture="$1"
    "$ELISACORE_BIN" -emit obj -o "$WORK/stage0.o" "$fixture" >/dev/null 2>&1 || {
        echo "field-access scope smoke FAIL: Stage0 rejected $fixture" >&2; exit 1;
    }
    stage1_compile -emit obj -o "$WORK/stage1.o" "$fixture" >/dev/null 2>&1 || {
        echo "field-access scope smoke FAIL: Stage1 rejected $fixture" >&2; exit 1;
    }
}

expect_reject_both "$REPO_ROOT/test/repro/generic_field_access_scope_leak.elisa"
expect_reject_both "$REPO_ROOT/test/repro/generic_field_access_ref_param.neg.elisa"
expect_accept_both "$REPO_ROOT/test/repro/generic_field_access_ref_shadow.pos.elisa"
expect_reject_both "$REPO_ROOT/test/repro/generic_field_access_match_scope_leak.neg.elisa"
expect_reject_both "$REPO_ROOT/test/repro/generic_field_access_array_child.neg.elisa"
expect_accept_both "$REPO_ROOT/test/repro/generic_field_access_scope_shadow.pos.elisa"
expect_reject_both "$REPO_ROOT/test/repro/primitive_field_access_scope_leak.neg.elisa"
expect_accept_both "$REPO_ROOT/test/repro/primitive_field_access_scope_shadow.pos.elisa"
expect_reject_both "$REPO_ROOT/test/fixtures/diagnostics/field_access_through_primitive_ref.neg.elisa"
echo "field-access parity smoke OK: generic value/ref parameters, branch-scope shadowing, and primitive-reference rejection"
