#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/test/parity/resolve_elisac.sh"
S0="${ELISA_STAGE0_BIN:-$ELISACORE_BIN}"
S1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/static-function-offset-filter.XXXXXX")"
trap 'rc=$?; if [[ "$rc" -eq 0 ]]; then rm -rf "$WORK"; else echo "static-function offset-filter artifacts retained at $WORK" >&2; fi; exit "$rc"' EXIT

fail() { echo "static-function offset-filter smoke FAIL: $*" >&2; exit 1; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$S0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$S1"

for row in "stage0:$S0" "stage1:$S1"; do
    stage="${row%%:*}"
    compiler="${row#*:}"
    if ! "$compiler" -emit llvm -o "$WORK/$stage.ll" "$ROOT/test/repro/static_function_nested_offset_filter.elisa" >"$WORK/$stage.out" 2>"$WORK/$stage.err"; then
        fail "$stage rejected nested/module/impl static functions: $(cat "$WORK/$stage.err")"
    fi
    helper_defs="$(grep -Ec '^[[:space:]]*define .*helper' "$WORK/$stage.ll" || true)"
    [[ "$helper_defs" -eq 1 ]] || fail "$stage should emit only the same-line runtime helper, found $helper_defs definitions"
    if grep -Fq 'compile_only_impl' "$WORK/$stage.ll"; then
        fail "$stage emitted a compile-time-only function from an impl scope"
    fi
done

echo 'nested static functions are filtered by exact source identity in modules and impl scopes'
