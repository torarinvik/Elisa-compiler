#!/usr/bin/env bash
# A stdlib associated type named Handle must not capture the top-level affine struct.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/affine_borrow_std_alias_collision.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-affine-alias-collision.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
"$STAGE0" -emit obj -O0 -o "$WORK/stage0.o" "$FIXTURE" >/dev/null 2>&1
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$FIXTURE" >/dev/null 2>&1
! rg -q '!elisa\.declined' "$WORK/stage1.ll"
/opt/homebrew/opt/llvm/bin/opt -passes=verify -disable-output "$WORK/stage1.ll"
echo "affine borrow std alias collision smoke OK: both stages accept and Stage1 emits complete IR"
