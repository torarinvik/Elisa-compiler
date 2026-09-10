#!/usr/bin/env bash
# Stage0/stage1 soundness regression: enum identity includes its declaring module.
# Two same-named enums have different declaration ordinals; selecting the first
# bare-name row would compile but make the Beta check return the wrong answer.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/module_enum_namespacing.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-enum-namespacing.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "module enum namespacing smoke SKIP: stage0 unavailable"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "module enum namespacing smoke SKIP: stage1 unavailable"; exit 0; }

"$STAGE0" -emit obj -O0 -o "$WORK/stage0.o" "$FIXTURE" >/dev/null 2>&1
# Stage0's embedded runtime exposes optional native-callback and profiler hooks. The
# ordinary runtime link supplies them in production; provide the same no-op ABI here so
# this regression tests enum semantics rather than an unrelated host-link choice.
cc -fno-builtin "$WORK/stage0.o" "$ROOT/scripts/pymodule_runtime_fallback.c" "$ROOT/test/parity/profile_hooks.c" -o "$WORK/stage0"
"$STAGE1" -emit exe -O0 -o "$WORK/stage1" "$FIXTURE" >/dev/null 2>&1
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$FIXTURE" >/dev/null 2>&1
! rg -q '!elisa\.declined' "$WORK/stage1.ll"

set +e
"$WORK/stage0"
stage0_status=$?
"$WORK/stage1"
stage1_status=$?
set -e
test "$stage0_status" -eq 0
test "$stage1_status" -eq 0

echo "module enum namespacing soundness OK: both stages preserve module-local ordinals"
