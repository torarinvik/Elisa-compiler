#!/usr/bin/env bash
# Stage0/Stage1 parity: qualified void error calls with aggregate references
# must retain the module owner and hidden fallible-result ABI.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0" || exit $?
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
FIXTURE="$ROOT/test/repro/qualified_void_error_aggregate.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-qualified-void-error.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "qualified void error aggregate smoke FAIL: stage0 unavailable" >&2; exit 1; }
[[ -x "$STAGE1" ]] || { echo "qualified void error aggregate smoke FAIL: stage1 unavailable" >&2; exit 1; }

"$STAGE0" -emit llvm -O0 -o "$WORK/stage0.ll" "$FIXTURE" >/dev/null 2>&1
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$FIXTURE" >/dev/null 2>&1

for output in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    ! rg -q '!elisa\.declined' "$output"
    rg -q 'define .*WasmBrowser.*HostWire.*validate' "$output"
    rg -q 'define .*wrapper' "$output"
done

echo "qualified void error aggregate parity OK"
