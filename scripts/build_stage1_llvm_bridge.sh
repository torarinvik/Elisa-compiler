#!/usr/bin/env bash
# Build the LLVM C++ utility bridge for a Stage1 compiler executable.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/platform.sh"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# -eq 1 ]] || { echo "usage: $0 output.o" >&2; exit 2; }
LLVM_CONFIG="${LLVM_CONFIG:-$ELISA_LLVM_BIN_DIR/llvm-config}"
llvm_bindir="$("$LLVM_CONFIG" --bindir)"
cxx="${ELISA_LLVM_CXX:-$llvm_bindir/clang++}"
[[ -x "$cxx" ]] || { echo "LLVM C++ compiler not found: $cxx" >&2; exit 2; }
# llvm-config emits compiler options, not user shell code. Split them as arguments.
read -r -a cxxflags <<<"$("$LLVM_CONFIG" --cxxflags)"
"$cxx" -O2 -fPIC "${cxxflags[@]}" -c "$ROOT/src/backend/llvm_validation_peel.cpp" -o "$1"
