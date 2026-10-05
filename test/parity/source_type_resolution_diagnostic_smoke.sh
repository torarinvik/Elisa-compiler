#!/usr/bin/env bash
# Source-level type-resolution errors must be reported before backend lowering, while a
# uniquely imported same-spelled type remains valid.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
S0="${ELISA_STAGE0_BIN:-$ELISACORE_BIN}"
S1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$S0" || exit $?
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$S1" || exit $?
work="$(mktemp -d)"
trap 'status=$?; if [ "$status" -eq 0 ]; then rm -rf "$work"; else echo "source type resolution logs retained at: $work" >&2; fi' EXIT

fail() { echo "source type resolution diagnostics FAIL: $1" >&2; exit 1; }
reject_both() {
  local fixture="$1" expected_s0="$2" expected_s1="${3:-$2}" s0_rc=0 s1_rc=0 source="$REPO_ROOT/test/repro/$1.elisa"
  "$S0" -emit llvm -o /dev/null "$source" >"$work/$fixture.s0" 2>&1 || s0_rc=$?
  env -u ELISA_STAGE1_RUNTIME_STD "$S1" -emit llvm -o /dev/null "$source" >"$work/$fixture.s1" 2>&1 || s1_rc=$?
  [ "$s0_rc" -eq 1 ] || fail "$fixture Stage0 expected semantic exit 1, got $s0_rc: $(cat "$work/$fixture.s0")"
  [ "$s1_rc" -eq 1 ] || fail "$fixture Stage1 expected semantic exit 1, got $s1_rc: $(cat "$work/$fixture.s1")"
  grep -qF "$expected_s0" "$work/$fixture.s0" || fail "$fixture Stage0 diagnostic missing '$expected_s0': $(cat "$work/$fixture.s0")"
  grep -qF "$expected_s1" "$work/$fixture.s1" || fail "$fixture Stage1 diagnostic missing '$expected_s1': $(cat "$work/$fixture.s1")"
  if grep -qF 'backend could not produce a linkable unit' "$work/$fixture.s1" || grep -qF 'backend emitted no functions' "$work/$fixture.s1"; then
    fail "$fixture reached backend decline: $(cat "$work/$fixture.s1")"
  fi
}
accept_both() {
  local fixture="$1" source="$REPO_ROOT/test/repro/$1.elisa"
  "$S0" -emit llvm -o /dev/null "$source" >"$work/$fixture.s0" 2>&1 || fail "$fixture Stage0 control rejected: $(cat "$work/$fixture.s0")"
  env -u ELISA_STAGE1_RUNTIME_STD "$S1" -emit llvm -o /dev/null "$source" >"$work/$fixture.s1" 2>&1 || fail "$fixture Stage1 control rejected: $(cat "$work/$fixture.s1")"
}

reject_both alias_cycle_source_diagnostic 'unknown type'
alias_s0_count="$(grep -cF 'unknown type "Cycle' "$work/alias_cycle_source_diagnostic.s0" || true)"
alias_s1_count="$(grep -cF 'unknown type "Cycle' "$work/alias_cycle_source_diagnostic.s1" || true)"
[ "$alias_s0_count" -eq 3 ] || fail "alias-cycle Stage0 expected three source diagnostics, got $alias_s0_count"
[ "$alias_s1_count" -eq 3 ] || fail "alias-cycle Stage1 expected three source diagnostics, got $alias_s1_count"
reject_both alias_cycle_module_owner_control 'unknown type "LocalA"'
module_alias_s0_count="$(grep -cF 'unknown type' "$work/alias_cycle_module_owner_control.s0" || true)"
module_alias_s1_count="$(grep -cF 'unknown type' "$work/alias_cycle_module_owner_control.s1" || true)"
[ "$module_alias_s0_count" -eq 3 ] || fail "module alias-cycle Stage0 expected three diagnostics with acyclic North control, got $module_alias_s0_count"
[ "$module_alias_s1_count" -eq 3 ] || fail "module alias-cycle Stage1 expected three diagnostics with acyclic North control, got $module_alias_s1_count"
reject_both ambiguous_wildcard_type_import 'unknown identifier "Code"' 'undefined identifier "Code"'
accept_both single_wildcard_type_import_control
echo 'source type resolution diagnostics OK: alias cycle and duplicate wildcard import fail semantically; unique import accepted'
