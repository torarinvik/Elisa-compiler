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
backend="$ROOT/src/backend"
src="$backend/llvm_validation_peel.cpp"
# Bridge sources include other C++ files from this directory. Key them all so
# adding an include cannot leave the cached bridge stale after an edit.
export LC_ALL=C
key="$(
  {
    inputs=()
    for input in "$backend"/*.cpp "$backend"/*.h; do
      [[ "$input" == "$backend/llvm_masked_split_multiply.cpp" ]] || inputs+=("$input")
    done
    elisa_sha256 "${inputs[@]}" "$cxx"
    "$cxx" --version
    printf '%s\n' -O1 -fPIC "${cxxflags[@]}"
  } | elisa_sha256 | awk '{print $1}'
)"
cache_dir="${ELISA_LLVM_BRIDGE_CACHE_DIR:-$ROOT/build/cache/llvm_bridge}"
cached="$cache_dir/$key.o"
if [[ ! -s "$cached" ]]; then
  mkdir -p "$cache_dir"
  tmp="$cached.tmp.$$"
  "$cxx" -O1 -fPIC "${cxxflags[@]}" -c "$src" -o "$tmp"
  mv -f "$tmp" "$cached"
fi
split_src="$backend/llvm_masked_split_multiply.cpp"
split_key="$(
  {
    elisa_sha256 "$split_src" "$cxx"
    "$cxx" --version
    printf '%s\n' -O1 -fPIC "${cxxflags[@]}"
  } | elisa_sha256 | awk '{print $1}'
)"
split_cached="$cache_dir/$split_key.o"
if [[ ! -s "$split_cached" ]]; then
  tmp="$split_cached.tmp.$$"
  "$cxx" -O1 -fPIC "${cxxflags[@]}" -c "$split_src" -o "$tmp"
  mv -f "$tmp" "$split_cached"
fi
"$cxx" -r "$cached" "$split_cached" -o "$1"
