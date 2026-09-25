#!/usr/bin/env bash
# Multi-column when rows bind scalar columns and keep those names arm-local.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
LLI="${LLI:-/opt/homebrew/opt/llvm/bin/lli}"
FIXTURE="$ROOT/test/repro/tuple_when_binders.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-tuple-when-bindings.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$LLI" ]] || { echo "tuple when binders smoke: missing lli: $LLI" >&2; exit 2; }

"$STAGE0" -emit llvm -O0 -o "$WORK/stage0.ll" "$FIXTURE"
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$FIXTURE"
! rg -q '!elisa\.declined' "$WORK/stage1.ll"
/opt/homebrew/opt/llvm/bin/opt -passes=verify -disable-output "$WORK/stage0.ll"
/opt/homebrew/opt/llvm/bin/opt -passes=verify -disable-output "$WORK/stage1.ll"
set +e
"$LLI" "$WORK/stage0.ll"
stage0_rc=$?
"$LLI" "$WORK/stage1.ll"
stage1_rc=$?
set -e
[[ "$stage0_rc" -eq 52 && "$stage1_rc" -eq "$stage0_rc" ]] || {
    echo "tuple when binders smoke FAILED: stage0=$stage0_rc stage1=$stage1_rc expected=52" >&2
    exit 1
}
echo "tuple when binders smoke OK: literal rows, bindings, and wildcard columns agree"
