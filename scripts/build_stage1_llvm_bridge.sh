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
sources=(
  "$backend/llvm_validation_peel.cpp"
  "$backend/llvm_scalar_loop_idioms.cpp"
  "$backend/llvm_reverse_byte_fold.cpp"
  "$backend/llvm_constant_paths.cpp"
  "$backend/llvm_memory_and_call_passes.cpp"
  "$backend/llvm_small_zero.cpp"
  "$backend/llvm_numeric_passes.cpp"
  "$backend/llvm_masked_split_multiply.cpp"
  "$backend/llvm_bounded_remainder.cpp"
  "$backend/llvm_signed_range_masks.cpp"
)
export LC_ALL=C
toolchain_inputs="$(
  elisa_sha256 "$cxx"
  "$cxx" --version
  printf '%s\n' -O1 -fPIC "${cxxflags[@]}"
)"
# Each unit is keyed by its quoted local includes, including transitive
# includes. A fill-pass edit can therefore reuse the validation bridge.
bridge_keys() {
  "$ELISA_TOOL_PYTHON" - "$toolchain_inputs" "${sources[@]}" <<'PY_KEYS'
import hashlib
import re
import sys
from pathlib import Path

includes = re.compile(rb'^\s*#\s*include\s*"([^"]+)"', re.MULTILINE)
for source in sys.argv[2:]:
    digest = hashlib.sha256(sys.argv[1].encode())
    pending = [Path(source)]
    seen = set()
    while pending:
        path = pending.pop().resolve()
        if path in seen:
            continue
        seen.add(path)
        content = path.read_bytes()
        digest.update(str(path).encode() + b"\0")
        digest.update(hashlib.sha256(content).digest())
        pending.extend(path.parent / name.decode() for name in includes.findall(content))
    print(digest.hexdigest())
PY_KEYS
}
keys="$(bridge_keys)"
cache_dir="${ELISA_LLVM_BRIDGE_CACHE_DIR:-$ROOT/build/cache/llvm_bridge}"
mkdir -p "$cache_dir"
# The merged bridge is identical whenever its ordered translation units
# are identical. Avoid starting a second linker on warm seed runs.
merged_key="$(printf '%s\n' stage1-llvm-bridge-v1 -nostdlib -r "$keys" | elisa_sha256)"
merged="$cache_dir/merged-${merged_key%% *}.o"
if [[ -s "$merged" ]]; then
  cp "$merged" "$1"
  exit
fi
objects=()
jobs=()
temporary=()
destinations=()
cleanup() {
  if (( ${#temporary[@]} )); then
    for tmp in "${temporary[@]}"; do
      if [[ -e "$tmp" ]]; then unlink "$tmp"; fi
    done
  fi
}
trap cleanup EXIT
index=0
while IFS= read -r key; do
  source="${sources[$index]}"
  cached="$cache_dir/$key.o"
  objects+=("$cached")
  if [[ ! -s "$cached" ]]; then
    tmp="$cached.tmp.$$"
    temporary+=("$tmp")
    destinations+=("$cached")
    "$cxx" -O1 -fPIC "${cxxflags[@]}" -c "$source" -o "$tmp" &
    jobs+=("$!")
  fi
  index=$((index + 1))
done <<<"$keys"
status=0
if (( ${#jobs[@]} )); then
  for job in "${jobs[@]}"; do
    wait "$job" || status=$?
  done
fi
if (( status )); then exit "$status"; fi
if (( ${#temporary[@]} )); then
  if [[ "$(bridge_keys)" != "$keys" ]]; then
    echo "Stage1 LLVM bridge inputs changed during compilation" >&2
    exit 1
  fi
  for index in "${!temporary[@]}"; do
    mv -f "${temporary[$index]}" "${destinations[$index]}"
  done
fi
merged_tmp="$(mktemp "$merged.tmp.XXXXXXXX")"
temporary+=("$merged_tmp")
"$cxx" -nostdlib -r "${objects[@]}" -o "$merged_tmp"
mv -f "$merged_tmp" "$merged"
cp "$merged" "$1"
