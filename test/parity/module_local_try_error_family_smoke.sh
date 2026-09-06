#!/usr/bin/env bash
# Stage0/stage1 parity: same-named module-local fallible calls must retain the
# caller's lexical error family during `try` propagation.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/module_local_try_error_family.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-module-local-try.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "module-local try error-family smoke SKIP: stage0 unavailable"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "module-local try error-family smoke SKIP: stage1 unavailable"; exit 0; }

"$STAGE0" -emit llvm -O0 -o "$WORK/stage0.ll" "$FIXTURE" >/dev/null 2>&1
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$FIXTURE" >/dev/null 2>&1

for output in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    [[ -s "$output" ]]
    ! rg -q '!elisa\.declined' "$output"
    rg -q 'First.*step' "$output"
    rg -q 'Second.*step' "$output"
done

echo "module-local try error-family parity OK: same-named module calls preserve lexical error sets"
