#!/usr/bin/env bash
# Exercise the actual constant-global pass against LLVM C API edge cases.
# The probe uses Stage0 because Stage1 currently rejects its local LLVM aggregate
# setup on region/effect checks; the pass itself remains Stage1 source.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
source "$ROOT/scripts/platform.sh"
TIMEOUT=$(command -v gtimeout || command -v timeout)
run() { "$TIMEOUT" -k 1s 29s "$@"; }
major=$("$LLVM_CONFIG" --version | cut -d. -f1)
[[ "$major" == 23 && "$ELISA_HOST_OS" == Darwin ]] || { echo 'constant-global range probes require qualified Darwin and LLVM 23'; exit 0; }
STAGE0="${ELISACORE_BIN:-$HOME/.elisac/elisac-stage0}"
run bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
run bash "$ROOT/scripts/assert_stage1_fresh.sh" "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
run bash "$ROOT/scripts/build_runtime_object.sh"
T=$(mktemp -d "${TMPDIR:-/tmp}/stage1-const-global-range.XXXXXX")
trap 'rm -rf "$T"' EXIT
run "$STAGE0" -O0 -emit obj -o "$T/probe.o" "$ROOT/test/parity/stage1_const_global_range_probe.elisa"
run "${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}" "$T/probe.o" "${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}" -L"$ELISA_LLVM_LIBDIR" $ELISA_LLVM_LIBS $ELISA_LINK_EXE_FLAGS -Wl,-rpath,"$ELISA_LLVM_LIBDIR" -o "$T/probe"
run "$T/probe"
echo 'stage1 constant-global range safety probes passed'
