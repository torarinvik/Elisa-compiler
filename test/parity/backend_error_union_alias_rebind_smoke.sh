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
FIXTURE="$ROOT/test/repro/backend_error_union_alias_rebind.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-error-union-alias-rebind.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$OPT" ]] || { echo "error union alias rebind smoke: missing opt: $OPT" >&2; exit 2; }
[[ -x "$CLANG" ]] || { echo "error union alias rebind smoke: missing clang: $CLANG" >&2; exit 2; }

for level in 0 2; do
    stage0_first_abi_layout=""
    stage0_second_abi_layout=""
    for stage in 0 1; do
        compiler="$STAGE0"
        [[ "$stage" -eq 0 ]] || compiler="$STAGE1"
        llvm="$WORK/stage${stage}-O${level}.ll"
        "$compiler" -emit llvm "-O$level" -o "$llvm" "$FIXTURE"
        if [[ "$stage" -eq 1 ]] && rg -q '!elisa\.declined' "$llvm"; then
            echo "error union alias rebind smoke: Stage1 declined a function at -O$level" >&2
            exit 1
        fi
        first_extern="$(rg -F '@first_external(' "$llvm" || true)"
        second_extern="$(rg -F '@second_external(' "$llvm" || true)"
        [[ -n "$first_extern" && -n "$second_extern" ]] || {
            echo "error union alias rebind smoke: missing extern declarations at Stage$stage -O$level" >&2
            exit 1
        }
        first_abi="${first_extern/@first_external/@external}"
        second_abi="${second_extern/@second_external/@external}"
        if [[ "$first_abi" == "$second_abi" ]]; then
            echo "error union alias rebind smoke: Stage$stage extern declarations reused the same error ABI at -O$level" >&2
            exit 1
        fi
        first_abi_layout="$(printf '%s\n' "$first_abi" | sed -E 's/%[-a-zA-Z$._0-9]+/%TYPE/g')"
        second_abi_layout="$(printf '%s\n' "$second_abi" | sed -E 's/%[-a-zA-Z$._0-9]+/%TYPE/g')"
        if [[ "$stage" -eq 0 ]]; then
            stage0_first_abi_layout="$first_abi_layout"
            stage0_second_abi_layout="$second_abi_layout"
        else
            if [[ "$first_abi_layout" != "$stage0_first_abi_layout" || "$second_abi_layout" != "$stage0_second_abi_layout" ]]; then
                echo "error union alias rebind smoke: Stage1 extern ABI differs from Stage0 at -O$level" >&2
                echo "  Stage0 first:  $stage0_first_abi_layout" >&2
                echo "  Stage1 first:  $first_abi_layout" >&2
                echo "  Stage0 second: $stage0_second_abi_layout" >&2
                echo "  Stage1 second: $second_abi_layout" >&2
                exit 1
            fi
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
        echo "error union alias rebind smoke FAILED at -O$level: Stage0=$stage0_result Stage1=$stage1_result expected=0" >&2
        exit 1
    fi
done

echo "error union alias rebind smoke OK: repeated key maps to its source-offset ABI row"
