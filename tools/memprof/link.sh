#!/usr/bin/env bash
# Link an Elisa object (default: the seed product's build/elisac_stage1.o) with the
# allocation-hook profiler instead of the weak no-op hooks.
#   tools/memprof/link.sh [OBJECT] [OUT]   -> OUT (default build/memprof/elisac-stage1-memprof)
# Uses the same clang/LLVM selection as the seed (ELISA_CLANG, LLVM_CONFIG; on Linux put
# tools/linux_shim first on PATH or set ELISA_CLANG to it).
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
OBJ="${1:-$ROOT/build/elisac_stage1.o}"
OUT="${2:-$ROOT/build/memprof/elisac-stage1-memprof}"
CLANG="${ELISA_CLANG:-$(command -v clang)}"
LLVM_CONFIG="${LLVM_CONFIG:-llvm-config}"
mkdir -p "$(dirname "$OUT")"
"$CLANG" -O2 -fno-omit-frame-pointer -c -o "$OUT.hooks.o" "$ROOT/tools/memprof/elisa_memprof.c"
libdir="$("$LLVM_CONFIG" --libdir)"
"$CLANG" -Wl,-dead_strip -o "$OUT" "$OBJ" "$OUT.hooks.o" -L"$libdir" -lLLVM -Wl,-rpath,"$libdir"
rm -f "$OUT.hooks.o"
echo "wrote $OUT"
