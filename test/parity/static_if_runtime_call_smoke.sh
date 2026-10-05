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
    rc=0
    "$compiler" -emit llvm -o "$WORK/$stage-negative.ll" "$ROOT/test/repro/static_block_runtime_call_rejected.elisa" >"$WORK/$stage-negative.out" 2>"$WORK/$stage-negative.err" || rc=$?
    [[ "$rc" -eq 1 ]] || fail "$stage bare static block expected semantic exit 1, got $rc"
    grep -Fq 'static expression statement must evaluate at compile time' "$WORK/$stage-negative.err" || fail "$stage did not preserve bare-static runtime-call refusal"
done

echo 'static-if runtime calls OK: target-selected Linux branch accepted; bare static block remains refused by Stage0 and Stage1'
