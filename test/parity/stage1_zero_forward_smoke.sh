#!/usr/bin/env bash
# Verify zero-stack forwarding with real LLVM IR, including rejected edge cases.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
source "$ROOT/scripts/platform.sh"
TIMEOUT=$(command -v gtimeout || command -v timeout)
run() { "$TIMEOUT" -k 1s 29s "$@"; }
major=$("$LLVM_CONFIG" --version | cut -d. -f1)
[[ "$major" == 23 && "$ELISA_HOST_OS" == Darwin ]] || { echo 'zero forwarding probes require qualified Darwin and LLVM 23'; exit 0; }
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
run bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
run bash "$ROOT/scripts/build_runtime_object.sh"
T=$(mktemp -d "${TMPDIR:-/tmp}/stage1-zero-forward.XXXXXX")
trap 'rm -rf "$T"' EXIT
cd "$ROOT"
run "$STAGE1" -O0 -emit obj -o "$T/probe.o" "$ROOT/test/parity/stage1_zero_forward_probe.elisa"
run "${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}" "$T/probe.o" "${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}" -L"$ELISA_LLVM_LIBDIR" $ELISA_LLVM_LIBS $ELISA_LINK_EXE_FLAGS -Wl,-rpath,"$ELISA_LLVM_LIBDIR" -o "$T/probe"
run "$T/probe"
echo 'stage1 zero forwarding safety probes passed'
