#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/test/parity/resolve_elisac.sh"
S0="${ELISA_STAGE0_BIN:-$ELISACORE_BIN}"
S1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$S0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$S1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/static-if-runtime-call.XXXXXX")"
trap 'rc=$?; if [[ "$rc" -eq 0 ]]; then rm -rf "$WORK"; else echo "static-if runtime-call artifacts retained at $WORK" >&2; fi; exit "$rc"' EXIT

fail() { echo "static-if runtime-call smoke FAIL: $*" >&2; exit 1; }
linux_triple=x86_64-unknown-linux-gnu
for row in "stage0:$S0" "stage1:$S1"; do
    stage="${row%%:*}"
    compiler="${row#*:}"
    if ! ELISA_HOST_LINUX=1 ELISA_HOST_X86_64=1 "$compiler" -emit llvm -target-triple "$linux_triple" -o "$WORK/$stage-positive.ll" "$ROOT/test/repro/static_if_runtime_call_linux.elisa" >"$WORK/$stage-positive.out" 2>"$WORK/$stage-positive.err"; then
        fail "$stage rejected runtime calls in a Linux static-if branch: $(cat "$WORK/$stage-positive.err")"
    fi
    grep -Fq 'target triple = "x86_64-unknown-linux-gnu"' "$WORK/$stage-positive.ll" || fail "$stage output did not retain the requested Linux target"
    if ! ELISA_HOST_LINUX=1 ELISA_HOST_X86_64=1 "$compiler" -emit llvm -target-triple "$linux_triple" -o "$WORK/$stage-nested-static-if.ll" "$ROOT/test/repro/static_if_inside_bare_static_runtime.elisa" >"$WORK/$stage-nested-static-if.out" 2>"$WORK/$stage-nested-static-if.err"; then
        fail "$stage reported a runtime call in a nested static-if arm inside a bare static block: $(cat "$WORK/$stage-nested-static-if.err")"
    fi
    grep -Fq 'target triple = "x86_64-unknown-linux-gnu"' "$WORK/$stage-nested-static-if.ll" || fail "$stage nested static-if output did not retain the requested Linux target"
    if ! "$compiler" -emit llvm -o "$WORK/$stage-inactive-nested-static.ll" "$ROOT/test/repro/static_if_inactive_nested_bare_static.elisa" >"$WORK/$stage-inactive-nested-static.out" 2>"$WORK/$stage-inactive-nested-static.err"; then
        fail "$stage checked a nested bare-static call inside a proven-inactive static-if branch: $(cat "$WORK/$stage-inactive-nested-static.err")"
    fi
    rc=0
    "$compiler" -emit llvm -o "$WORK/$stage-sibling-static-name.ll" "$ROOT/test/repro/static_runtime_sibling_static_name.elisa" >"$WORK/$stage-sibling-static-name.out" 2>"$WORK/$stage-sibling-static-name.err" || rc=$?
    [[ "$rc" -eq 1 ]] || fail "$stage sibling-module runtime function expected semantic exit 1, got $rc"
    grep -Fq 'static expression statement must evaluate at compile time' "$WORK/$stage-sibling-static-name.err" || fail "$stage let a sibling module's static function hide a runtime call: $(cat "$WORK/$stage-sibling-static-name.err")"
    rc=0
    "$compiler" -emit llvm -o "$WORK/$stage-imported-runtime.ll" "$ROOT/test/repro/static_block_imported_runtime_call.elisa" >"$WORK/$stage-imported-runtime.out" 2>"$WORK/$stage-imported-runtime.err" || rc=$?
    [[ "$rc" -eq 1 ]] || fail "$stage imported runtime calls expected semantic exit 1, got $rc"
    imported_runtime_diagnostics="$(grep -Fc 'static expression statement must evaluate at compile time' "$WORK/$stage-imported-runtime.err" || true)"
    [[ "$imported_runtime_diagnostics" -eq 2 ]] || fail "$stage must diagnose both wildcard- and selective-imported runtime calls: $(cat "$WORK/$stage-imported-runtime.err")"
    if ! ELISA_HOST_LINUX=1 ELISA_HOST_X86_64=1 "$compiler" -emit llvm -target-triple "$linux_triple" -o "$WORK/$stage-nested-positive.ll" "$ROOT/test/repro/static_if_nested_runtime_elif_module.elisa" >"$WORK/$stage-nested-positive.out" 2>"$WORK/$stage-nested-positive.err"; then
        fail "$stage rejected nested static-if runtime calls in module/elif branches: $(cat "$WORK/$stage-nested-positive.err")"
    fi
    grep -Fq 'target triple = "x86_64-unknown-linux-gnu"' "$WORK/$stage-nested-positive.ll" || fail "$stage nested output did not retain the requested Linux target"
    if ! ELISA_HOST_LINUX=1 ELISA_HOST_X86_64=1 "$compiler" -emit llvm -target-triple "$linux_triple" -o "$WORK/$stage-same-line.ll" "$ROOT/test/repro/static_if_same_line_heads.elisa" >"$WORK/$stage-same-line.out" 2>"$WORK/$stage-same-line.err"; then
        fail "$stage rejected distinct static-if heads sharing one #line value: $(cat "$WORK/$stage-same-line.err")"
    fi
    grep -Fq '@active_first' "$WORK/$stage-same-line.ll" || fail "$stage omitted the selected first branch"
    grep -Fq '@active_second' "$WORK/$stage-same-line.ll" || fail "$stage omitted the selected fallback branch"
    if grep -Fq '@inactive_second' "$WORK/$stage-same-line.ll"; then
        fail "$stage emitted the false branch because another head shared its #line value"
    fi
    rc=0
    "$compiler" -emit llvm -o "$WORK/$stage-negative.ll" "$ROOT/test/repro/static_block_runtime_call_rejected.elisa" >"$WORK/$stage-negative.out" 2>"$WORK/$stage-negative.err" || rc=$?
    [[ "$rc" -eq 1 ]] || fail "$stage bare static block expected semantic exit 1, got $rc"
    grep -Fq 'static expression statement must evaluate at compile time' "$WORK/$stage-negative.err" || fail "$stage did not preserve bare-static runtime-call refusal"
    rc=0
    ELISA_HOST_LINUX=1 ELISA_HOST_X86_64=1 "$compiler" -emit llvm -target-triple "$linux_triple" -o "$WORK/$stage-nested-negative.ll" "$ROOT/test/repro/static_if_nested_bare_static_rejected.elisa" >"$WORK/$stage-nested-negative.out" 2>"$WORK/$stage-nested-negative.err" || rc=$?
    [[ "$rc" -eq 1 ]] || fail "$stage nested bare static block expected semantic exit 1, got $rc"
    grep -Fq 'static expression statement must evaluate at compile time' "$WORK/$stage-nested-negative.err" || fail "$stage did not refuse nested bare-static runtime call"
    rc=0
    "$compiler" -emit llvm -o "$WORK/$stage-line-reset-negative.ll" "$ROOT/test/repro/static_block_runtime_call_line_reset_rejected.elisa" >"$WORK/$stage-line-reset-negative.out" 2>"$WORK/$stage-line-reset-negative.err" || rc=$?
    [[ "$rc" -eq 1 ]] || fail "$stage bare static block sharing a #line value expected semantic exit 1, got $rc"
    grep -Fq 'static expression statement must evaluate at compile time' "$WORK/$stage-line-reset-negative.err" || fail "$stage confused the bare static block with an unrelated static-if head at the same #line value"
done

echo 'static-if runtime calls and branch identities OK: nested/module/elif branches accepted, inactive nested arms skip static-block checks, imported runtime calls are refused, bare static blocks are refused, and same-line conditional heads remain distinct'
