#!/usr/bin/env bash
# Stage0/stage1 soundness regression: payload enum identity includes its module.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0" || exit $?
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
FIXTURE="$ROOT/test/repro/module_payload_enum_namespacing.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-payload-enum-namespacing.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "module payload enum namespacing smoke FAIL: stage0 unavailable" >&2; exit 1; }
[[ -x "$STAGE1" ]] || { echo "module payload enum namespacing smoke FAIL: stage1 unavailable" >&2; exit 1; }

"$STAGE0" -emit obj -O0 -o "$WORK/stage0.o" "$FIXTURE" >/dev/null 2>&1
cc -fno-builtin "$WORK/stage0.o" "$ROOT/scripts/pymodule_runtime_fallback.c" "$ROOT/test/parity/profile_hooks.c" -o "$WORK/stage0"
"$STAGE1" -emit exe -O0 -o "$WORK/stage1" "$FIXTURE" >/dev/null 2>&1
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$FIXTURE" >/dev/null 2>&1
! rg -q '!elisa\.declined' "$WORK/stage1.ll"

set +e
"$WORK/stage0"
stage0_rc=$?
"$WORK/stage1"
stage1_rc=$?
set -e
test "$stage0_rc" -eq 0
test "$stage1_rc" -eq 0

echo "module payload enum namespacing soundness OK: both stages preserve module-local payload tags"
