#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN" || exit $?
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$ELISACORE_BIN" && -x "$STAGE1" ]] || { echo "backend_header_smoke FAIL: missing compiler" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# The structs are `layout(c)`: stage0 REFUSES to export a type that is not
# C-ABI-compatible ("export type X must name a concrete C-ABI-compatible struct"), so a
# plain `struct` here made the source one stage0 would reject — and the oracle below could
# not run at all.
cat > "$WORK/input.elisa" <<'ELISA'
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
struct CallbackTable layout(c):
    user: mutable void&?
    callback: fn(mutable void&?, i32) -> void

# Return annotations precede export aliases and must never rename either
# struct to the metadata owner __extern_return in the generated C header.
extern acquire_pair() -> Pair&
extern acquire_outer() -> Outer&
export type Pair as Public
export type Outer as PublicOuter
export type Node as PublicNode
export type CallbackTable as PublicCallbackTable

global seed: i64 = 7
export global seed as ctx_seed

def internal(a: i64, b: i64) -> i64:
    return a + b
export fn add(a: i64, b: i64) -> i64 = internal

def main() -> i64:
    return 0
ELISA
"$ELISACORE_BIN" -emit header -o "$WORK/stage0.h" "$WORK/input.elisa"
"$STAGE1" -emit header -o "$WORK/generated.h" "$WORK/input.elisa"
if ! diff -u "$WORK/stage0.h" "$WORK/generated.h"; then
    echo "backend header smoke FAILED: Stage1 disagrees with Stage0" >&2
    exit 1
fi

# A floor of structural checks, so a generator that emitted nothing could not pass by
# matching an equally empty oracle.
grep -q 'struct Public' "$WORK/generated.h"
grep -q 'struct Inner' "$WORK/generated.h"
grep -q 'struct PublicOuter' "$WORK/generated.h"
grep -q 'Inner inner;' "$WORK/generated.h"
grep -q 'struct PublicNode' "$WORK/generated.h"
grep -q 'PublicNode \*next;' "$WORK/generated.h"
grep -q 'void (\*callback)(void \*arg0, int32_t arg1);' "$WORK/generated.h"
grep -q 'int64_t add(' "$WORK/generated.h"
cc -x c -fsyntax-only "$WORK/generated.h"
c++ -x c++ -fsyntax-only "$WORK/generated.h"
echo "backend header smoke OK (byte-identical to stage0)"
