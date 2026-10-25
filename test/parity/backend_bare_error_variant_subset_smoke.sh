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
FIXTURE="$ROOT/test/repro/backend_bare_error_variant_subset.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-bare-error-variant.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$OPT" ]] || { echo "bare error variant subset smoke: missing opt: $OPT" >&2; exit 2; }
[[ -x "$CLANG" ]] || { echo "bare error variant subset smoke: missing clang: $CLANG" >&2; exit 2; }

for level in 0 2; do
    stage0_leaf_abi=""
    for stage in 0 1; do
        compiler="$STAGE0"
        [[ "$stage" -eq 0 ]] || compiler="$STAGE1"
        llvm="$WORK/stage${stage}-O${level}.ll"
        binary="$WORK/stage${stage}-O${level}"
        "$compiler" -emit llvm "-O$level" -o "$llvm" "$FIXTURE"
        if [[ "$stage" -eq 1 ]] && rg -q '!elisa\.declined' "$llvm"; then
            echo "bare error variant subset smoke: Stage1 declined at -O$level" >&2
            exit 1
        fi
        # At O2 LLVM can inline and remove the internal leaf; check its explicit ABI at O0
        # and keep O2 as a runtime parity check.
        if [[ "$level" -eq 0 ]]; then
            leaf_abi="$(rg -F -m1 '@leaf(' "$llvm" | sed -E 's/%[-a-zA-Z$._0-9]+/%TYPE/g' || true)"
            [[ -n "$leaf_abi" ]] || { echo "bare error variant subset smoke: missing leaf ABI at Stage$stage -O$level" >&2; exit 1; }
            if [[ "$stage" -eq 0 ]]; then
                stage0_leaf_abi="$leaf_abi"
            elif [[ "$leaf_abi" != "$stage0_leaf_abi" ]]; then
                echo "bare error variant subset smoke: Stage1 leaf ABI differs from Stage0 at -O$level" >&2
                echo "  Stage0: $stage0_leaf_abi" >&2
                echo "  Stage1: $leaf_abi" >&2
                exit 1
            fi
        fi
        "$OPT" -passes=verify -disable-output "$llvm"
        DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
            "$CLANG" "-O$level" -Wno-override-module -o "$binary" "$llvm"
    done

    set +e
    "$WORK/stage0-O$level"
    stage0_result=$?
    "$WORK/stage1-O$level"
    stage1_result=$?
    set -e
    if [[ "$stage0_result" -ne 0 || "$stage1_result" -ne "$stage0_result" ]]; then
        echo "bare error variant subset smoke FAILED at -O$level: Stage0=$stage0_result Stage1=$stage1_result expected=0" >&2
        exit 1
    fi
done

echo "bare error variant subset smoke OK: singleton tag registration and propagation match"
