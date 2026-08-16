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

# The structs are `layout(c)`: stage0 REFUSES to export a type that is not
# C-ABI-compatible ("export type X must name a concrete C-ABI-compatible struct"), so a
# plain `struct` here made the source one stage0 would reject — and the oracle below could
# not run at all.
cat > "$BUILD/input.elisa" <<'ELISA'
struct Inner layout(c):
    value: i64
struct Pair layout(c):
    left: i64
    right: u8
struct Outer layout(c):
    inner: Inner
struct Node layout(c):
    value: i64
    next: Node&

export type Pair as Public
export type Outer as PublicOuter
export type Node as PublicNode

global seed: i64 = 7
export global seed as ctx_seed

def internal(a: i64, b: i64) -> i64:
    return a + b
export fn add(a: i64, b: i64) -> i64 = internal

def main() -> i64:
    return 0
ELISA
"$BUILD/emit_header" < "$BUILD/input.elisa" > "$BUILD/generated.h"

# ORACLE, not a hand-written assertion list. The greps this replaced had drifted from the
# generator twice over — they demanded `PublicNode* next;` where both compilers now write
# `PublicNode *next;` (C binds the star to the declarator), and `intptr_t` where an `i64`
# must render `int64_t`. A frozen expectation cannot notice that stage0 moved; comparing
# against stage0 directly cannot miss it.
#
# Only the include GUARD is normalized away: stage0 derives it from the source filename
# while this host driver hardcodes ELISA_GENERATED_H, which is a property of the driver,
# not of the generator under test.
"$ELISACORE_BIN" -emit header -o "$BUILD/stage0.h" "$BUILD/input.elisa" >/dev/null 2>&1
# Also drop a trailing blank line: this host driver publishes the header with `puts`,
# which appends a newline of its own. That is the DRIVER's, not the generator's — the CLI
# `-emit header` output is byte-identical to stage0 without it.
normalize() { sed -E 's/(ifndef|define|endif.*) [A-Z0-9_]+_H/\1 GUARD_H/' "$1" | sed -e '$ { /^$/d; }'; }
if ! diff <(normalize "$BUILD/stage0.h") <(normalize "$BUILD/generated.h") > "$BUILD/header.diff"; then
    echo "backend header smoke FAILED: generator disagrees with stage0"
    head -20 "$BUILD/header.diff"
    exit 1
fi

# A floor of structural checks, so a generator that emitted nothing could not pass by
# matching an equally empty oracle.
grep -q 'struct Public' "$BUILD/generated.h"
grep -q 'struct Inner' "$BUILD/generated.h"
grep -q 'struct PublicOuter' "$BUILD/generated.h"
grep -q 'Inner inner;' "$BUILD/generated.h"
grep -q 'struct PublicNode' "$BUILD/generated.h"
grep -q 'PublicNode \*next;' "$BUILD/generated.h"
grep -q 'int64_t add(' "$BUILD/generated.h"
cc -x c -fsyntax-only "$BUILD/generated.h"
c++ -x c++ -fsyntax-only "$BUILD/generated.h"
echo "backend header smoke OK (byte-identical to stage0)"
