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
src="$ROOT/src/backend/llvm_validation_peel.cpp"
# Every seed links the bridge; recompiling it costs ~1 s. Reuse an object keyed
# on the source, the compiler binary and version, and the exact flags.
key="$( { elisa_sha256 "$src" "$ROOT/src/backend/llvm_remainder_tail.cpp" "$ROOT/src/backend/llvm_small_zero.cpp" "$ROOT/src/backend/llvm_scratch_prefix.cpp" "$ROOT/src/backend/llvm_covered_prefix.cpp" "$ROOT/src/backend/llvm_bool_array_pack.cpp" "$ROOT/src/backend/llvm_bounded_division_unroll.cpp" "$ROOT/src/backend/llvm_bounded_product.cpp" "$ROOT/src/backend/llvm_sqrt_proof.cpp" "$ROOT/src/backend/llvm_bounded_sum.cpp" "$ROOT/src/backend/llvm_index_bounds.cpp" "$ROOT/src/backend/llvm_validation_layout.cpp" "$ROOT/src/backend/llvm_short_trip.cpp" "$ROOT/src/backend/llvm_checked_mul.cpp" "$ROOT/src/backend/llvm_bounded_unswitch.cpp" "$ROOT/src/backend/llvm_shared_reciprocal.cpp" "$cxx"; "$cxx" --version; printf '%s\n' -O2 -fPIC "${cxxflags[@]}"; } | elisa_sha256 | awk '{print $1}')"
cache_dir="${ELISA_LLVM_BRIDGE_CACHE_DIR:-$ROOT/build/cache/llvm_bridge}"
cached="$cache_dir/$key.o"
if [[ ! -s "$cached" ]]; then
  mkdir -p "$cache_dir"
  tmp="$cached.tmp.$$"
  "$cxx" -O2 -fPIC "${cxxflags[@]}" -c "$src" -o "$tmp"
  mv -f "$tmp" "$cached"
fi
cp -f "$cached" "$1"
