#!/usr/bin/env bash
# Const enums share a primitive backend representation but not a source-level owner. Equality
# between distinct owners must be rejected before lowering, even when their payload values are
# equal. Same-owner values, aliases, payload-enum equality, and reference identity are controls.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
S0="${ELISA_STAGE0_BIN:-$ELISACORE_BIN}"
S1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$S1" || exit $?
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fail() { echo "const-enum owner equality FAIL: $1" >&2; exit 1; }
reject_both() {
  local case_name="$1" expected_s0="$2" expected_s1="${3:-$2}" source="$REPO_ROOT/test/repro/$1.elisa"
  local s0_rc=0 s1_rc=0
  "$S0" -emit llvm -o /dev/null "$source" >"$work/$case_name.s0" 2>&1 || s0_rc=$?
  env -u ELISA_STAGE1_RUNTIME_STD "$S1" -emit llvm -o /dev/null "$source" >"$work/$case_name.s1" 2>&1 || s1_rc=$?
  [ "$s0_rc" -ne 0 ] || fail "$case_name accepted by Stage0"
  [ "$s1_rc" -ne 0 ] || fail "$case_name accepted by Stage1"
  grep -qF "$expected_s0" "$work/$case_name.s0" || fail "$case_name Stage0 diagnostic changed: $(cat "$work/$case_name.s0")"
  grep -qF "$expected_s1" "$work/$case_name.s1" || fail "$case_name Stage1 lacks semantic diagnostic '$expected_s1': $(cat "$work/$case_name.s1")"
  if grep -qF 'backend could not produce a linkable unit' "$work/$case_name.s1"; then
    fail "$case_name reached backend decline instead of source semantics"
  fi
}
accept_both() {
  local case_name="$1" source="$REPO_ROOT/test/repro/$1.elisa"
  "$S0" -emit llvm -o /dev/null "$source" >"$work/$case_name.s0" 2>&1 || fail "$case_name Stage0 control rejected: $(cat "$work/$case_name.s0")"
  env -u ELISA_STAGE1_RUNTIME_STD "$S1" -emit llvm -o /dev/null "$source" >"$work/$case_name.s1" 2>&1 || fail "$case_name Stage1 control rejected: $(cat "$work/$case_name.s1")"
  if grep -qF 'backend could not produce a linkable unit' "$work/$case_name.s0" "$work/$case_name.s1"; then
    fail "$case_name control reached backend decline"
  fi
}

reject_both const_enum_cross_owner_equal_payload 'cannot compare OwnerA and OwnerB'
reject_both const_enum_cross_owner_wrong_shorthand 'Foreign'
reject_both const_enum_module_owner_collisions 'cannot compare North.Code and South.Code' 'cannot compare'
accept_both const_enum_same_owner_nonunit_equality
accept_both const_enum_alias_same_owner_equality
accept_both const_enum_module_owner_positive_controls
accept_both payload_enum_equality_control
accept_both const_enum_reference_equality_control

echo 'const-enum owner equality OK: equal-payload and wrong-owner shorthand rejected before lowering; same-owner, non-unit, alias, payload-enum and reference controls accepted'
