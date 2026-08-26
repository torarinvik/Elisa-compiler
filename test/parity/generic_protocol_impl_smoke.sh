#!/usr/bin/env bash
# GENERIC PROTOCOL IMPLS — `impl[T] P for C[T]:`.
#
# stage1 used to DECLINE every member of a generic impl and, because a unit is dropped whole
# when any function declines, the whole program with it. The parser matched only the
# three-bare-identifier header (`impl I for C:`), so for `impl[T] Store for darray[T]:` the
# `[T]` was skipped with the rest of the header and captured nowhere; declare_function_impl
# then resolved the member's `darray[T]&` with no binding for T, got TypeKind.Unmodeled and
# returned null. `print(42)` was enough to trigger it — the std's three Store/KeyedStore impls
# are in every program that includes the runtime — and it read as
#   error: backend emitted no functions for this unit; declined 40: store_get, store_count, …
# The fix records the impl header's parameters against each member `def`'s line on the same
# side table function-level generics use (parser_decl_impl.elisa capture_impl_generic_params),
# so a member is a generic TEMPLATE exactly like `def store_get[T](…)` written longhand.
#
# Two fixtures, both RUN, because the two halves fail differently:
#   1. std-free — the impl exists, is reached through a `[H: Holder]` bound, and answers.
#   2. the real std — `impl[T] Store for darray[T]` through `[S: Store]`, which is the shape
#      the whole surface exists for (docs/69) and the one that regressed real programs.
# stage0 is compared against whenever ELISACORE_BIN already names a binary; the smoke never
# builds one itself, so it is safe to run against a pinned toolchain.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
[ -f "$RUNTIME_OBJ" ] || { echo "generic-protocol-impl SKIP: no runtime object"; exit 0; }
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LLVM_BIN_DIR="${ELISA_LLVM_BIN_DIR:-$(dirname -- "$LLVM_CONFIG")}"
LLVM_CLANG="${ELISA_CLANG:-$LLVM_BIN_DIR/clang}"
[ -x "$LLVM_CLANG" ] || LLVM_CLANG="$(command -v clang || true)"
[ -x "$LLVM_CLANG" ] || { echo "generic-protocol-impl SKIP: no clang for LLVM_CONFIG=$LLVM_CONFIG"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
failed=0
fail() { echo "  FAIL $1"; failed=$((failed + 1)); }

# --- 1. std-free: `impl[T] Holder for Box[T]` reached through `[H: Holder]` ---------------
cat >"$WORK/plain.elisa" <<'EOF'
struct Box[T]:
    v: T

protocol Holder:
    type Elem
    def hold_count(s: Self&) -> usize

impl[T] Holder for Box[T]:
    type Elem = T
    def hold_count(s: Box[T]&) -> usize:
        return 7.usize()

def total[H: Holder](h: H&) -> usize:
    return h.hold_count()

def main() -> i64:
    b: Box[i64] = Box[i64]{v: 5}
    return total(&b).i64()
EOF

if bash "$ROOT/scripts/elisac_stage1.sh" -emit exe -O2 -o "$WORK/plain_s1" "$WORK/plain.elisa" >"$WORK/plain_s1.log" 2>&1; then
    "$WORK/plain_s1" >/dev/null 2>&1 </dev/null; plain_rc=$?
    [ "$plain_rc" = 7 ] || fail "std-free generic impl: exit $plain_rc, want 7"
else
    fail "std-free generic impl: stage1 declined ($(head -1 "$WORK/plain_s1.log"))"
fi

# --- 2. the real std: `impl[T] Store for darray[T]` through `[S: Store]` ------------------
STD="$ROOT/elisacore_std"
if [ -f "$STD/collections.elisa" ]; then
    cat >"$WORK/store.elisa" <<EOF
include "$STD/elisacore_runtime.elisa"
include "$STD/collections.elisa"

def total[S: Store](s: S&) -> usize:
    can Abort.Panic:
        return s.store_count()

def main() -> i64:
    can Console.Write, Memory.Allocate, Abort.Panic:
        region r(65536)
        in r:
            xs: mutable darray[i64] = []
            xs.push(7)
            xs.push(9)
            xs.push(11)
            print("ok" if total(&xs) == 3.usize() else "bad")
            return total(&xs).i64()
        destroy r
        return 0
EOF
    if ELISA_STAGE1_SEMANTIC_GATE=1 bash "$ROOT/scripts/elisac_stage1.sh" -emit exe -O2 -o "$WORK/store_s1" "$WORK/store.elisa" >"$WORK/store_s1.log" 2>&1; then
        store_out=$("$WORK/store_s1" 2>/dev/null </dev/null); store_rc=$?
        [ "$store_out" = "ok" ] || fail "std Store impl: printed '$store_out', want 'ok'"
        [ "$store_rc" = 3 ] || fail "std Store impl: exit $store_rc, want 3"
    else
        fail "std Store impl: stage1 declined ($(head -1 "$WORK/store_s1.log"))"
    fi

    # stage0 must agree, when one is already available. Never BUILD a stage0 here: the
    # harness is run against pinned toolchains and building would write outside the worktree.
    if [ -n "${ELISACORE_BIN:-}" ] && [ -x "${ELISACORE_BIN:-}" ]; then
        if "$ELISACORE_BIN" -emit obj -O2 -o "$WORK/store_s0.o" "$WORK/store.elisa" >"$WORK/store_s0.log" 2>&1 \
           && "$LLVM_CLANG" -Wl,-dead_strip -o "$WORK/store_s0" "$WORK/store_s0.o" "$RUNTIME_OBJ" >>"$WORK/store_s0.log" 2>&1; then
            s0_out=$("$WORK/store_s0" 2>/dev/null </dev/null); s0_rc=$?
            [ "$s0_out" = "ok" ] && [ "$s0_rc" = 3 ] || fail "stage0 disagrees: printed '$s0_out' exit $s0_rc, want 'ok' exit 3"
        else
            fail "std Store impl: stage0 build failed ($(tail -1 "$WORK/store_s0.log"))"
        fi
    fi
else
    echo "  note: no vendored elisacore_std; std Store half skipped"
fi

if [ "$failed" -gt 0 ]; then
    echo "generic-protocol-impl FAILED: $failed failures"
    exit 1
fi
echo "generic-protocol-impl OK: impl[T] P for C[T] members register as templates and dispatch under a [S: P] bound"
