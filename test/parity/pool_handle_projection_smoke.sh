#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/platform.sh"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
LLVM_CONFIG="${LLVM_CONFIG:-$ELISA_LLVM_BIN_DIR/llvm-config}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-pool-projection.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
ELISA_STAGE1_BIN="$STAGE1" bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -o "$WORK/probe.o" "$ROOT/test/parity/pool_handle_projection_unit.elisa"
# llvm-config supplies the libraries matching the compiler's backend ABI.
read -r -a llvm_ldflags <<< "$("$LLVM_CONFIG" --ldflags)"
read -r -a llvm_libs <<< "$("$LLVM_CONFIG" --libs --system-libs | tr '\n' ' ')"
read -r -a host_flags <<< "$ELISA_LINK_EXE_FLAGS"
"$CLANG" "$WORK/probe.o" "$RUNTIME" "${llvm_ldflags[@]}" "${llvm_libs[@]}" ${host_flags[@]+"${host_flags[@]}"} "$ELISA_LD_ALLOW_UNDEFINED" -o "$WORK/probe"
"$WORK/probe"
echo 'pool handle projection fallback smoke OK'
