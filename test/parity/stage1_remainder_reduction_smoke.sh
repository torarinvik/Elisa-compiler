#!/usr/bin/env bash
# Build the pass from current source. This does not replace the full self-host gate.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
. "$ROOT/scripts/platform.sh"
COMPILER="${ELISA_REMAINDER_PROBE_COMPILER:?select the compiler used to build the source-bound probe}"
TIMEOUT="$(command -v gtimeout || command -v timeout)"
run() { "$TIMEOUT" -k 0.1s 29.7s "$@"; }
WORK="$(mktemp -d "${TMPDIR:-/tmp}/stage1-remainder.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
if [[ "$(uname -s)" == Linux ]]; then export ELISA_HOST_LINUX=1; fi
LLVM_CONFIG="${LLVM_CONFIG:-$ELISA_LLVM_BIN_DIR/llvm-config}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
read -r -a LINK_FLAGS <<<"$("$LLVM_CONFIG" --ldflags --system-libs --libs core irreader analysis | tr '\n' ' ')"
run "$COMPILER" -O0 -emit obj -o "$WORK/probe.o" "$ROOT/test/parity/stage1_remainder_reduction_probe.elisa"
run "$CLANG" "$WORK/probe.o" "${LINK_FLAGS[@]}" -Wl,-rpath,"$ELISA_LLVM_LIBDIR" -o "$WORK/probe"
CASE_FLAGS=()
if [[ "$(uname -s)" == Linux ]]; then
    run "$CLANG" -shared -fPIC "$ROOT/test/parity/stage1_remainder_foreign_flags.c" -o "$WORK/foreign.so"
    CASE_FLAGS=(--foreign-flag-library "$WORK/foreign.so")
fi
run python3 "$ROOT/test/parity/stage1_remainder_reduction_cases.py" "$WORK/probe" "${CASE_FLAGS[@]}"
