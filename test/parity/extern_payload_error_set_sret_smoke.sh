#!/usr/bin/env bash
# Verify the target's hidden-sret C ABI for a payload error set larger than return registers.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LLVM_BIN="$(dirname -- "$LLVM_CONFIG")"
OPT="${ELISA_OPT:-$LLVM_BIN/opt}"
CLANG="${ELISA_CLANG:-$LLVM_BIN/clang}"
FIXTURE="$ROOT/test/repro/extern_payload_error_set_sret.elisa"
STUB="$ROOT/test/repro/extern_payload_error_set_sret.c"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-error-set-sret.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$OPT" ]] || { echo "extern error-set sret smoke: missing opt: $OPT" >&2; exit 2; }
[[ -x "$CLANG" ]] || { echo "extern error-set sret smoke: missing clang: $CLANG" >&2; exit 2; }

for level in 0 2; do
    llvm="$WORK/stage1-O$level.ll"
    "$STAGE1" -emit llvm "-O$level" -o "$llvm" "$FIXTURE"
    if rg -q '!elisa\.declined' "$llvm"; then
        echo "extern error-set sret smoke: Stage1 declined at -O$level" >&2
        exit 1
    fi
    grep -Eq '^declare void @external_probe\(ptr sret\(' "$llvm" || {
        echo "extern error-set sret smoke: declaration omitted the typed sret parameter at -O$level" >&2
        rg -n 'external_probe' "$llvm" >&2 || true
        exit 1
    }
    grep -Eq 'call void @external_probe\(ptr .*sret\(' "$llvm" || {
        echo "extern error-set sret smoke: call site omitted the typed sret parameter at -O$level" >&2
        rg -n 'external_probe' "$llvm" >&2 || true
        exit 1
    }
    "$OPT" -passes=verify -disable-output "$llvm"
    DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
        "$CLANG" "-O$level" -Wno-override-module -o "$WORK/llvm-O$level" "$llvm" "$STUB"
    set +e
    "$WORK/llvm-O$level"
    llvm_result=$?
    set -e
    [[ "$llvm_result" -eq 41 ]] || {
        echo "extern error-set sret smoke FAILED for LLVM output at -O$level: result=$llvm_result expected=41" >&2
        exit 1
    }

    object="$WORK/stage1-O$level.o"
    "$STAGE1" -emit obj "-O$level" -o "$object" "$FIXTURE"
    DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
        "$CLANG" -o "$WORK/object-O$level" "$object" "$STUB"
    set +e
    "$WORK/object-O$level"
    object_result=$?
    set -e
    [[ "$object_result" -eq 41 ]] || {
        echo "extern error-set sret smoke FAILED for object output at -O$level: result=$object_result expected=41" >&2
        exit 1
    }
done

echo "extern error-set sret smoke OK: LLVM and object outputs return payload 41 through the C sret ABI at -O0 and -O2"
