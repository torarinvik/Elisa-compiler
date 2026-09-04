#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../wasm-sdk-stage0/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
SOURCE="$ROOT/test/repro/catch_aggregate_result.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-aggregate-catch.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "aggregate catch result smoke SKIP: stage0 unavailable"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "aggregate catch result smoke SKIP: stage1 unavailable"; exit 0; }

compile_and_run() {
    local name="$1"
    local compiler="$2"
    local object="$WORK/$name.o"
    local executable="$WORK/$name"
    local llvm="$WORK/$name.ll"

    "$compiler" -emit llvm -O0 -o "$llvm" "$SOURCE" >/dev/null 2>&1
    ! rg -q '!elisa\.declined' "$llvm"
    rg -q 'define .*@consume\(' "$llvm"
    rg -q 'alloca %Box' "$llvm"
    rg -q 'phi i64|alloca i64' "$llvm"

    "$compiler" -emit obj -O2 -o "$object" "$SOURCE" >/dev/null 2>&1
    clang -o "$executable" "$object"
    set +e
    "$executable"
    local result=$?
    set -e
    [[ "$result" -eq 49 ]]
}

compile_and_run stage0 "$STAGE0"
compile_and_run stage1 "$STAGE1"

echo "aggregate catch result smoke OK: aggregate error payloads can be caught into scalar arm results in both compiler generations"
