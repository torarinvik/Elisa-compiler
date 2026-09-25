#!/usr/bin/env bash
# Exercise Stage0's LLVM-internal baseline and Stage1's target C ABI for the minimized
# restricted-composite expression-catch path.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LLVM_BIN="$(dirname -- "$LLVM_CONFIG")"
OPT="${ELISA_OPT:-$LLVM_BIN/opt}"
CLANG="${ELISA_CLANG:-$LLVM_BIN/clang}"
FIXTURE="$ROOT/test/repro/catch_subset_minimal.elisa"
STUB="$ROOT/test/repro/catch_subset_minimal_stub.ll"
C_STUB="$ROOT/test/repro/catch_subset_minimal_c_stub.c"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-composite-subset-catch.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$OPT" ]] || { echo "composite subset catch smoke: missing opt: $OPT" >&2; exit 2; }
[[ -x "$CLANG" ]] || { echo "composite subset catch smoke: missing clang: $CLANG" >&2; exit 2; }
"$OPT" -passes=verify -disable-output "$STUB"

for level in 0 2; do
    for stage in 0 1; do
        compiler="$STAGE0"
        [[ "$stage" -eq 1 ]] && compiler="$STAGE1"
        llvm="$WORK/stage${stage}-O${level}.ll"
        "$compiler" -emit llvm "-O$level" -o "$llvm" "$FIXTURE"
        if [[ "$stage" -eq 1 ]] && rg -q '!elisa\.declined' "$llvm"; then
            echo "composite subset catch smoke: Stage1 declined a function at -O$level" >&2
            exit 1
        fi
        "$OPT" -passes=verify -disable-output "$llvm"
        stub="$STUB"
        [[ "$stage" -eq 1 ]] && stub="$C_STUB"
        if [[ "$stage" -eq 1 ]]; then
            grep -Eq '^declare i64 @foo\(ptr\)' "$llvm" || {
                echo "composite subset catch smoke: Stage1 declaration did not use the arm64 C return type at -O$level" >&2
                rg -n '@foo' "$llvm" >&2 || true
                exit 1
            }
        fi
        DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
            "$CLANG" "-O$level" -Wno-override-module -o "$WORK/stage${stage}-O${level}" "$llvm" "$stub"
    done

    set +e
    "$WORK/stage0-O$level"
    stage0_result=$?
    "$WORK/stage1-O$level"
    stage1_result=$?
    set -e
    if [[ "$stage0_result" -ne 42 || "$stage1_result" -ne "$stage0_result" ]]; then
        echo "composite subset catch smoke FAILED at -O$level: Stage0=$stage0_result Stage1=$stage1_result expected=42" >&2
        exit 1
    fi
done

echo "composite subset expression catch smoke OK: Stage0 LLVM baseline and Stage1 C ABI return 42 at -O0 and -O2"
