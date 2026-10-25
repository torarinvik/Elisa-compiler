#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
LLVM_CONFIG="${LLVM_CONFIG:-$ELISA_LLVM_BIN_DIR/llvm-config}"
LLVM_BIN="$(dirname -- "$LLVM_CONFIG")"
OPT="${ELISA_OPT:-$LLVM_BIN/opt}"
CLANG="${ELISA_CLANG:-$LLVM_BIN/clang}"
FIXTURE="$ROOT/test/repro/backend_error_identity_line_offset.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-error-identity-offset.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$OPT" ]] || { echo "error identity offset smoke: missing opt: $OPT" >&2; exit 2; }
[[ -x "$CLANG" ]] || { echo "error identity offset smoke: missing clang: $CLANG" >&2; exit 2; }

for level in 0 2; do
    for stage in 0 1; do
        compiler="$STAGE0"
        [[ "$stage" -eq 0 ]] || compiler="$STAGE1"
        llvm="$WORK/stage${stage}-O${level}.ll"
        "$compiler" -emit llvm "-O$level" -o "$llvm" "$FIXTURE"
        if [[ "$stage" -eq 1 ]] && rg -q '!elisa\.declined' "$llvm"; then
            echo "error identity offset smoke: Stage1 declined at -O$level" >&2
            exit 1
        fi
        "$OPT" -passes=verify -disable-output "$llvm"
        DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
            "$CLANG" "-O$level" -Wno-override-module -o "$WORK/stage${stage}-O${level}" "$llvm"
    done

    set +e
    "$WORK/stage0-O$level"
    stage0_result=$?
    "$WORK/stage1-O$level"
    stage1_result=$?
    set -e
    if [[ "$stage0_result" -ne 0 || "$stage1_result" -ne "$stage0_result" ]]; then
        echo "error identity offset smoke FAILED at -O$level: Stage0=$stage0_result Stage1=$stage1_result expected=0" >&2
        exit 1
    fi
done

echo "error identity offset smoke OK: Stage0 and Stage1 agree at -O0 and -O2"
