#!/usr/bin/env bash
# Verify that a C aggregate return for an Elisa payload-bearing error set uses the target C
# register ABI and is reconstructed before Elisa's composite catch dispatcher reads it.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LLVM_BIN="$(dirname -- "$LLVM_CONFIG")"
OPT="${ELISA_OPT:-$LLVM_BIN/opt}"
CLANG="${ELISA_CLANG:-$LLVM_BIN/clang}"
FIXTURES=(
    "$ROOT/test/repro/extern_multi_family_payload.elisa"
    "$ROOT/test/repro/extern_multi_family_payload_try.elisa"
)
STUB="$ROOT/test/repro/extern_multi_family_payload_c_abi_stub.c"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-extern-composite-c-abi.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$OPT" ]] || { echo "extern composite C ABI smoke: missing opt: $OPT" >&2; exit 2; }
[[ -x "$CLANG" ]] || { echo "extern composite C ABI smoke: missing clang: $CLANG" >&2; exit 2; }

for fixture in "${FIXTURES[@]}"; do
    fixture_name="$(basename -- "$fixture" .elisa)"
    for level in 0 2; do
        llvm="$WORK/${fixture_name}-O${level}.ll"
        "$STAGE1" -emit llvm "-O$level" -o "$llvm" "$fixture"
        if rg -q '!elisa\.declined' "$llvm"; then
            echo "extern composite C ABI smoke: Stage1 declined a function in $fixture_name at -O$level" >&2
            exit 1
        fi
        grep -Eq '^declare i64 @external_probe\(ptr, i64\)' "$llvm" || {
            echo "extern composite C ABI smoke: declaration did not use the arm64 C return type in $fixture_name at -O$level" >&2
            rg -n 'external_probe' "$llvm" >&2 || true
            exit 1
        }
        grep -Eq 'call i64 @external_probe\(ptr' "$llvm" || {
            echo "extern composite C ABI smoke: call site did not use the C return type in $fixture_name at -O$level" >&2
            rg -n 'external_probe' "$llvm" >&2 || true
            exit 1
        }
        "$OPT" -passes=verify -disable-output "$llvm"
        DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
            "$CLANG" "-O$level" -Wno-override-module -o "$WORK/${fixture_name}-O$level" "$llvm" "$STUB"

        set +e
        "$WORK/${fixture_name}-O$level"
        result=$?
        set -e
        if [[ "$result" -ne 42 ]]; then
            echo "extern composite C ABI smoke FAILED in $fixture_name at -O$level: result=$result expected=42" >&2
            exit 1
        fi

        object="$WORK/${fixture_name}-O$level.o"
        "$STAGE1" -emit obj "-O$level" -o "$object" "$fixture"
        DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
            "$CLANG" -o "$WORK/${fixture_name}-obj-O$level" "$object" "$STUB"
        set +e
        "$WORK/${fixture_name}-obj-O$level"
        object_result=$?
        set -e
        if [[ "$object_result" -ne 42 ]]; then
            echo "extern composite C ABI object smoke FAILED in $fixture_name at -O$level: result=$object_result expected=42" >&2
            exit 1
        fi
    done
done

echo "extern composite C ABI smoke OK: LLVM and object outputs restore C's { i32, i32 } return for direct catch and propagating try at -O0 and -O2"
