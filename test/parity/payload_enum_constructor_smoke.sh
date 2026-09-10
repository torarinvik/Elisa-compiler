#!/usr/bin/env bash
# Stage1 regression: qualified payload-enum variants are constructors even when the
# variant carries no payload. This path was accidentally nested under plain-enum lowering.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-payload-enum-constructor.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "payload enum constructor smoke SKIP: stage0 unavailable"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "payload enum constructor smoke SKIP: stage1 unavailable"; exit 0; }
[[ -f "$RUNTIME_OBJ" ]] || { echo "payload enum constructor smoke SKIP: runtime object unavailable"; exit 0; }

FIXTURE="$ROOT/test/repro/stage1_payload_enum_field.elisa"
"$STAGE0" -emit obj -O0 -o "$WORK/stage0.o" "$FIXTURE" >/dev/null 2>&1
cc -fno-builtin "$WORK/stage0.o" "$RUNTIME_OBJ" \
    "$ROOT/scripts/pymodule_runtime_fallback.c" "$ROOT/test/parity/profile_hooks.c" \
    -o "$WORK/stage0"

ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" "$STAGE1" -emit exe -O0 -o "$WORK/stage1" "$FIXTURE" >/dev/null 2>&1
ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" "$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$FIXTURE" >/dev/null 2>&1
! rg -q '!elisa\.declined' "$WORK/stage1.ll"
/opt/homebrew/opt/llvm/bin/opt -passes=verify -disable-output "$WORK/stage1.ll"

set +e
"$WORK/stage0"
stage0_status=$?
"$WORK/stage1"
stage1_status=$?
set -e
test "$stage0_status" -eq 0
test "$stage1_status" -eq 0

echo "payload enum constructor smoke OK: stage0 and stage1 construct and test a payload enum"
