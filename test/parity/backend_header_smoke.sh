#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
[ -x "$ELISACORE_BIN" ] || { echo "backend_header_smoke SKIP: no elisac"; exit 0; }
[ -x "$LLVM_CONFIG" ] || { echo "backend_header_smoke SKIP: no llvm-config"; exit 0; }

BUILD="$ROOT/build/header_smoke"
mkdir -p "$BUILD"
LIBDIR="$($LLVM_CONFIG --libdir)"

"$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/driver.o" "$ROOT/test/breadth/emit_header.elisa" \
    >"$BUILD/build.log" 2>&1

# The normal runtime object deliberately does not provide the compiler-generated overload
# name for this tiny host driver. Supply that one Console bridge locally; the generated
# header itself is still checked by real C and C++ frontends below.
clang -x c -c -o "$BUILD/puts_shim.o" - <<'EOF'
#include <stdio.h>
int elisa_header_puts(const char *s) __asm__("___ovl__puts__cstr__puts");
int elisa_header_puts(const char *s) { return puts(s); }
EOF
clang -o "$BUILD/emit_header" "$BUILD/driver.o" "$BUILD/puts_shim.o" \
    -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR"

printf '%s\n' \
    'struct Inner:' \
    '    value: i64' \
    'struct Pair:' \
    '    left: i64' \
    '    right: u8' \
    'struct Outer:' \
    '    inner: Inner' \
    'struct Node:' \
    '    value: i64' \
    '    next: Node&' \
    '' \
    'export type Pair as Public' \
    'export type Outer as PublicOuter' \
    'export type Node as PublicNode' \
    '' \
    'global seed: i64 = 7' \
    'export global seed as ctx_seed' \
    '' \
    'def internal(a: i64, b: i64) -> i64:' \
    '    return a + b' \
    'export fn add(a: i64, b: i64) -> i64 = internal' \
    '' \
    'def main() -> i64:' \
    '    return 0' \
    | "$BUILD/emit_header" > "$BUILD/generated.h"

grep -q 'struct Public' "$BUILD/generated.h"
grep -q 'struct Inner' "$BUILD/generated.h"
grep -q 'struct PublicOuter' "$BUILD/generated.h"
grep -q 'Inner inner;' "$BUILD/generated.h"
grep -q 'struct PublicNode' "$BUILD/generated.h"
grep -q 'PublicNode\* next;' "$BUILD/generated.h"
grep -q 'extern intptr_t seed;' "$BUILD/generated.h"
grep -q 'intptr_t add(intptr_t a,intptr_t b);' "$BUILD/generated.h"
cc -x c -fsyntax-only "$BUILD/generated.h"
c++ -x c++ -fsyntax-only "$BUILD/generated.h"
echo "backend header smoke OK"
