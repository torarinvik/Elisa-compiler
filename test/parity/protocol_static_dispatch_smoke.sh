#!/usr/bin/env bash
# STATIC PROTOCOL DISPATCH THROUGH A BOUND TYPE PARAMETER — `T.method(args)`.
#
#     def tag[T: Tagged](v: T) -> i64:
#         return T.tag_of(v)
#
# codegen_call.elisa took this path only when the UNIT declared exactly one impl, on the
# reasoning that with two the bare method name is ambiguous. The hazard is real; the gate
# asked the wrong question. T is BOUND while the instantiation is being emitted, so the
# arguments have concrete types and ordinary overload resolution can name the impl — the
# ambiguity is settled per CALL, not per program. Any unit including the std declares ~22
# impls, so the old gate meant static dispatch never worked in a real program at all.
#
# Resolution demands a UNIQUE exact match, and this smoke pins both halves of that:
#   1. two impls of one protocol on DISTINCT types dispatch to the right one — verified by
#      the answer, not by "it compiled", because picking either would still compile;
#   2. an AMBIGUOUS set still declines rather than guessing. stage1 models `char`, `int`,
#      `i64` and `isize` as one ValueType, so `impl Str for char` and `impl Str for i64`
#      are indistinguishable here; taking the first made `print(42)` print "*" (chr 42).
#      A compiler that answers "*" is worse than one that refuses, so refusing is the
#      contract until type arguments carry name-level identity.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
[ -f "$RUNTIME_OBJ" ] || { echo "protocol-static-dispatch SKIP: no runtime object"; exit 0; }
STD="$ROOT/elisacore_std"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LLVM_BIN_DIR="${ELISA_LLVM_BIN_DIR:-$(dirname -- "$LLVM_CONFIG")}"
LLVM_CLANG="${ELISA_CLANG:-$LLVM_BIN_DIR/clang}"
[ -x "$LLVM_CLANG" ] || LLVM_CLANG="$(command -v clang || true)"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
failed=0
fail() { echo "  FAIL $1"; failed=$((failed + 1)); }

# --- 1. two impls on distinct types, dispatched by the bound type ------------------------
# The old single-impl gate declined this outright. Picking "either" answers 11 or 22, so the
# exit code separates a correct dispatch from a lucky one.
cat >"$WORK/twoimpl.elisa" <<'EOF'
protocol Tagged:
    def tag_of(self: Self) -> i64

impl Tagged for i64:
    def tag_of(self: i64) -> i64:
        return 1

impl Tagged for f64:
    def tag_of(self: f64) -> i64:
        return 2

def tag[T: Tagged](v: T) -> i64:
    return T.tag_of(v)

def main() -> i64:
    a: i64 = 5
    b: f64 = 5.0
    return tag(a) * 10 + tag(b)
EOF
if bash "$ROOT/scripts/elisac_stage1.sh" -emit exe -O2 -o "$WORK/twoimpl" "$WORK/twoimpl.elisa" >"$WORK/twoimpl.log" 2>&1; then
    "$WORK/twoimpl" >/dev/null 2>&1 </dev/null; two_rc=$?
    [ "$two_rc" = 12 ] || fail "two-impl dispatch: exit $two_rc, want 12 (i64 -> 1, f64 -> 2)"
else
    fail "two-impl dispatch: stage1 declined ($(head -1 "$WORK/twoimpl.log"))"
fi

# stage0 must agree, when one is already available. Never BUILD a stage0 here: the harness
# runs against pinned toolchains and building would write outside the worktree.
if [ -n "${ELISACORE_BIN:-}" ] && [ -x "${ELISACORE_BIN:-}" ] && [ -x "$LLVM_CLANG" ]; then
    if "$ELISACORE_BIN" -emit obj -O2 -o "$WORK/twoimpl.s0.o" "$WORK/twoimpl.elisa" >"$WORK/twoimpl.s0.log" 2>&1 \
       && "$LLVM_CLANG" -Wl,-dead_strip -o "$WORK/twoimpl.s0" "$WORK/twoimpl.s0.o" "$RUNTIME_OBJ" >>"$WORK/twoimpl.s0.log" 2>&1; then
        "$WORK/twoimpl.s0" >/dev/null 2>&1 </dev/null; s0_rc=$?
        [ "$s0_rc" = 12 ] || fail "two-impl dispatch: stage0 exit $s0_rc, want 12"
    else
        fail "two-impl dispatch: stage0 build failed ($(tail -1 "$WORK/twoimpl.s0.log"))"
    fi
fi

# --- 2. an ambiguous set must DECLINE, never guess ----------------------------------------
# `char` and `i64` are one ValueType to this backend, so `T.tag_of(v)` below has two equally
# good candidates. The unit must not build; if it does, the compiler picked one silently.
cat >"$WORK/ambiguous.elisa" <<'EOF'
protocol Tagged:
    def tag_of(self: Self) -> i64

impl Tagged for char:
    def tag_of(self: char) -> i64:
        return 1

impl Tagged for i64:
    def tag_of(self: i64) -> i64:
        return 2

def tag[T: Tagged](v: T) -> i64:
    return T.tag_of(v)

def main() -> i64:
    a: i64 = 5
    return tag(a)
EOF
if bash "$ROOT/scripts/elisac_stage1.sh" -emit exe -O2 -o "$WORK/ambiguous" "$WORK/ambiguous.elisa" >"$WORK/ambiguous.log" 2>&1; then
    "$WORK/ambiguous" >/dev/null 2>&1 </dev/null; amb_rc=$?
    fail "ambiguous dispatch silently resolved (exit $amb_rc); it must decline until type arguments carry names"
fi

# --- 3. the std still builds and prints ---------------------------------------------------
# `print(42)` remains blocked by check 2's ambiguity (char/int/i64 all implement Str). What
# must keep working is everything around it, so a regression here is visible immediately.
if [ -f "$STD/elisacore_runtime.elisa" ]; then
    cat >"$WORK/stdprint.elisa" <<EOF
include "$STD/elisacore_runtime.elisa"

def main() -> i64:
    can Console.Write, Memory.Allocate, Console.Format, Abort.Panic:
        print("text")
        return 0
EOF
    if ELISA_STAGE1_SEMANTIC_GATE=1 bash "$ROOT/scripts/elisac_stage1.sh" -emit exe -O2 \
            -o "$WORK/stdprint" "$WORK/stdprint.elisa" >"$WORK/stdprint.log" 2>&1; then
        got=$("$WORK/stdprint" 2>/dev/null </dev/null)
        [ "$got" = "text" ] || fail "std print: got '$got', want 'text'"
    else
        fail "std print: stage1 declined ($(head -1 "$WORK/stdprint.log"))"
    fi
fi

if [ "$failed" -gt 0 ]; then
    echo "protocol-static-dispatch FAILED: $failed failures"
    exit 1
fi
echo "protocol-static-dispatch OK: T.method(args) resolves by the bound type when unique, declines when ambiguous"
