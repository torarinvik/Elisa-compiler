#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
LLVM_CONFIG="${LLVM_CONFIG:-$ELISA_LLVM_BIN_DIR/llvm-config}"
LLVM_BIN="$(dirname -- "$LLVM_CONFIG")"
OPT="${ELISA_OPT:-$LLVM_BIN/opt}"
CLANG="${ELISA_CLANG:-$LLVM_BIN/clang}"
FIXTURE="$ROOT/test/repro/backend_bare_variant_error_union.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-bare-variant-error-union.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$OPT" ]] || { echo "bare-variant error-union smoke: missing opt: $OPT" >&2; exit 2; }
[[ -x "$CLANG" ]] || { echo "bare-variant error-union smoke: missing clang: $CLANG" >&2; exit 2; }

for level in 0 2; do
    llvm="$WORK/stage1-O$level.ll"
    "$STAGE1" -emit llvm "-O$level" -o "$llvm" "$FIXTURE"
    if rg -q '!elisa\.declined' "$llvm"; then
        echo "bare-variant error-union smoke: Stage1 declined a function at -O$level" >&2
        exit 1
    fi
    "$OPT" -passes=verify -disable-output "$llvm"
    DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
        "$CLANG" "-O$level" -Wno-override-module -o "$WORK/stage1-O$level" "$llvm"
    set +e
    "$WORK/stage1-O$level"
    result=$?
    set -e
    if [[ "$result" -ne 0 ]]; then
        echo "bare-variant error-union smoke FAILED at -O$level: exit=$result expected=0" >&2
        exit 1
    fi
done

echo "backend bare-variant error-union smoke OK: payload survives subset forwarding"
