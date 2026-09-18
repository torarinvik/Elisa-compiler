#!/usr/bin/env bash
# Stage0/Stage1 parity for explicit region capacity expressions. The parser retains the
# capacity as source text, so the backend must reconstruct and fold the same integer AST
# rather than accepting only a decimal literal.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1_ROOT="${ELISA_STAGE1_ROOT:-$ROOT}"
STAGE1="${ELISA_STAGE1_BIN:-$STAGE1_ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/region_capacity_const_expression.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

[[ -x "$STAGE0" ]] || { echo "region capacity expression smoke: missing stage0: $STAGE0" >&2; exit 2; }
[[ -x "$STAGE1" ]] || { echo "region capacity expression smoke: missing stage1: $STAGE1" >&2; exit 2; }

"$STAGE0" -emit llvm -O0 -o "$WORK/stage0.ll" "$FIXTURE" >/dev/null
ELISA_STAGE1_ROOT="$STAGE1_ROOT" ELISA_STAGE1_BIN="$STAGE1" \
    "$STAGE1_ROOT/scripts/elisac_stage1.sh" -emit llvm -O0 -o "$WORK/stage1.ll" "$FIXTURE" >/dev/null

! rg -q '!elisa\.declined' "$WORK/stage0.ll"
! rg -q '!elisa\.declined' "$WORK/stage1.ll"
rg -q 'new_region_backend' "$WORK/stage1.ll"

echo "region capacity expression parity OK: named, qualified, arithmetic, and parenthesized capacities"
