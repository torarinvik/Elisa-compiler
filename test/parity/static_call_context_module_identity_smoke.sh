#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/test/parity/resolve_elisac.sh"
S0="${ELISA_STAGE0_BIN:-$ELISACORE_BIN}"
S1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/static-call-context-module-identity.XXXXXX")"
trap 'rc=$?; if [[ "$rc" -eq 0 ]]; then rm -rf "$WORK"; else echo "static-call-context module-identity artifacts retained at $WORK" >&2; fi; exit "$rc"' EXIT

fail() { echo "static-call-context module-identity smoke FAIL: $*" >&2; exit 1; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$S0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$S1"

for row in "stage0:$S0" "stage1:$S1"; do
    stage="${row%%:*}"
    compiler="${row#*:}"
    rc=0
    "$compiler" -emit llvm -o "$WORK/$stage.ll" "$ROOT/test/repro/static_call_context_module_identity.elisa" >"$WORK/$stage.out" 2>"$WORK/$stage.err" || rc=$?
    [[ "$rc" -eq 1 ]] || fail "$stage should diagnose Runtime.parse calling the static helper, got exit $rc"
    grep -Fq 'static function "helper" can only be called from a static context' "$WORK/$stage.err" || fail "$stage missed the static helper call in the runtime parse body"
    grep -Fq 'static function "hidden" can only be called from a static context' "$WORK/$stage.err" || fail "$stage missed static calls nested in runtime expressions"
    hidden_count="$(grep -Fc 'static function "hidden" can only be called from a static context' "$WORK/$stage.err" || true)"
    [[ "$hidden_count" -eq 8 ]] || fail "$stage should report all eight nested runtime hidden() calls, got $hidden_count"
    grep -Fq 'static function "ancestor_helper" can only be called from a static context' "$WORK/$stage.err" || fail "$stage missed the ancestor static helper call in the nested module body"
    if grep -Fq 'static function "parse" can only be called from a static context' "$WORK/$stage.err"; then
        fail "$stage treated Runtime.caller's runtime parse call as the sibling Compile.parse static function"
    fi
    if grep -Fq 'static function "branch_pick" can only be called from a static context' "$WORK/$stage.err"; then
        fail "$stage treated BranchSelection's inactive static overload as the selected runtime branch"
    fi
    branch_static_count="$(grep -Fc 'static function "branch_static" can only be called from a static context' "$WORK/$stage.err" || true)"
    [[ "$branch_static_count" -eq 1 ]] || fail "$stage should diagnose only the selected static-if runtime caller, not the inactive arm or bare static block (got $branch_static_count)"
    if grep -Fq 'static function "shadowed_helper" can only be called from a static context' "$WORK/$stage.err"; then
        fail "$stage let an ancestor static function outrank a nearer runtime declaration"
    fi
    if grep -Fq 'static function "choose" can only be called from a static context' "$WORK/$stage.err"; then
        fail "$stage diagnosed a same-scope mixed overload without knowing which overload the call selects"
    fi
done

unknown_rc=0
ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown "$S1" -emit llvm -o "$WORK/stage1-unknown.ll" "$ROOT/test/repro/static_call_context_module_identity.elisa" >"$WORK/stage1-unknown.out" 2>"$WORK/stage1-unknown.err" || unknown_rc=$?
[[ "$unknown_rc" -eq 1 ]] || fail "stage1 unknown-target compile should retain the fixture's expected static-call diagnostics, got exit $unknown_rc"
grep -Fq 'static function "compile_only" can only be called from a static context' "$WORK/stage1-unknown.err" || fail "stage1 skipped the runtime caller inside an unresolved static-if arm"
unknown_branch_static_count="$(grep -Fc 'static function "branch_static" can only be called from a static context' "$WORK/stage1-unknown.err" || true)"
[[ "$unknown_branch_static_count" -eq 1 ]] || fail "stage1 unknown-target compile should diagnose the selected static-if runtime call exactly once, got $unknown_branch_static_count"
if grep -Fq 'static function "late_bound" can only be called from a static context' "$WORK/stage1-unknown.err"; then
    fail "stage1 failed to let an unresolved nearer runtime function shadow its ancestor static function"
fi

echo 'static-call-context module identity OK: exact declaration, module, and active branch identities are respected'
