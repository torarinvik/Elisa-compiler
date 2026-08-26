#!/usr/bin/env bash
# `u8&` RETURNED IN A `cstr` CONTEXT — pointer pass-through, not a deref.
#
# codegen_expr_calls.elisa auto-dereferences a call whose declared return is `T&` when the
# surrounding context is not itself a `T&`. That is right for `v: i64 = get_ref()` and WRONG
# for a `cstr` context: `cstr` is a pointer and `u8&` IS one. The load produced an `i8`, the
# return path's type-identity check refused it, and the function declined — which is the shape
# of every integer/float/char `impl Str for X: def __cast__(self: X) -> cstr: return
# int_to_string_scratch(self)` in the std. Fourteen of them declined silently in every program
# that includes the runtime; `print(42)` is the first thing that REFERENCES one (through the
# generic `print[T: Str]`), and a referenced decline drops the whole module.
#
# The same conversion through a LOCAL (`x: cstr = f()`) always passed the pointer through, so
# the two paths disagreed about one program — that inconsistency is the bug in one line.
#
# Two checks, because the fix has to be narrow:
#   1. the `cstr` return round-trips the actual string (not a byte, not a decline);
#   2. the emitted IR really passes the pointer through — no `load i8` in the way.
#
# `print(42)`, the symptom this gap was found through, needs one more thing on top and is
# covered by protocol_static_dispatch_smoke.sh.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
[ -f "$RUNTIME_OBJ" ] || { echo "cstr-ref-return SKIP: no runtime object"; exit 0; }
STD="$ROOT/elisacore_std"
[ -f "$STD/elisacore_runtime.elisa" ] || { echo "cstr-ref-return SKIP: no vendored elisacore_std"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
failed=0
fail() { echo "  FAIL $1"; failed=$((failed + 1)); }

build_run() {   # name -> sets $out / $rc
    local name="$1"
    if ELISA_STAGE1_SEMANTIC_GATE=1 bash "$ROOT/scripts/elisac_stage1.sh" -emit exe -O2 \
            -o "$WORK/$name" "$WORK/$name.elisa" >"$WORK/$name.log" 2>&1; then
        out=$("$WORK/$name" 2>/dev/null </dev/null); rc=$?
        return 0
    fi
    out=""; rc=-1
    return 1
}

# --- 1. a `u8&`-returning call returned as `cstr` -----------------------------------------
cat >"$WORK/passthrough.elisa" <<EOF
include "$STD/elisacore_runtime.elisa"

def as_text(v: i64) -> cstr:
    can Memory.Allocate, Console.Format, Abort.Panic:
        return int_to_string_scratch(v)

def main() -> i64:
    can Console.Write, Memory.Allocate, Console.Format, Abort.Panic:
        print(as_text(1234))
        return 0
EOF
if build_run passthrough; then
    [ "$out" = "1234" ] || fail "cstr pass-through: printed '$out', want '1234'"
else
    fail "cstr pass-through: stage1 declined ($(head -1 "$WORK/passthrough.log"))"
fi

# --- 2. the pass-through is a pass-through, in the IR ------------------------------------
# The runtime check above cannot tell "returned the pointer" from "loaded a byte that happened
# to print" — a declined function would also just not print. Read the emitted module: `as_text`
# must hand back the CALL RESULT, with no `load i8` between. (The deref this narrows is
# exercised across the whole corpus by opt_pipeline_smoke, which runs every runnable fixture
# at -O0/-O2/-O3 and compares answers.)
if bash "$ROOT/scripts/elisac_stage1.sh" -emit llvm -o "$WORK/passthrough.ll" "$WORK/passthrough.elisa" >"$WORK/passthrough.ll.log" 2>&1; then
    body=$(sed -n '/^define[^@]*@as_text/,/^}/p' "$WORK/passthrough.ll")
    [ -n "$body" ] || fail "as_text missing from the emitted module"
    printf '%s\n' "$body" | grep -q 'load i8' && fail "as_text still loads a byte out of the cstr: $body"
    printf '%s\n' "$body" | grep -qE 'ret ptr %' || fail "as_text does not return the call result: $body"
else
    fail "-emit llvm on the pass-through fixture failed ($(head -1 "$WORK/passthrough.ll.log"))"
fi

if [ "$failed" -gt 0 ]; then
    echo "cstr-ref-return FAILED: $failed failures"
    exit 1
fi
echo "cstr-ref-return OK: a u8&-returning call passes through a cstr context, pointer intact"
