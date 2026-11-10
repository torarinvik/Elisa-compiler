#!/usr/bin/env bash
# An explicitly converted byte reference must remain a pointer in a cstr return.
# Check both the native round trip and the IR so a scalar byte load cannot pass.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
[ -f "$RUNTIME_OBJ" ] || { echo "cstr-ref-return FAIL: no runtime object" >&2; exit 1; }

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
cat >"$WORK/passthrough.elisa" <<'EOF'
extern puts(text: cstr) -> i32

def text_bytes(text: cstr) -> u8&:
    trusted Unsafe.PointerCast:
        return text.cast[u8&]

def as_text(text: cstr) -> cstr:
    trusted Unsafe.PointerCast:
        return text_bytes(text).cast[cstr]

def main() -> i64:
    _ = puts(as_text("1234"))
    return 0
EOF
if build_run passthrough; then
    [ "$out" = "1234" ] || fail "cstr pass-through: printed '$out', want '1234'"
else
    fail "cstr pass-through: stage1 declined ($(head -1 "$WORK/passthrough.log"))"
fi

# The IR must return the pointer produced by the call without loading a byte.
if bash "$ROOT/scripts/elisac_stage1.sh" -emit llvm -o "$WORK/passthrough.ll" "$WORK/passthrough.elisa" >"$WORK/passthrough.ll.log" 2>&1; then
    body=$(sed -n '/^define[^@]*@as_text/,/^}/p' "$WORK/passthrough.ll")
    [ -n "$body" ] || fail "as_text missing from the emitted module"
    grep -q 'load i8' <<< "$body" && fail "as_text still loads a byte out of the cstr: $body"
    grep -qE 'ret ptr %' <<< "$body" || fail "as_text does not return the call result: $body"
else
    fail "-emit llvm on the pass-through fixture failed ($(head -1 "$WORK/passthrough.ll.log"))"
fi

if [ "$failed" -gt 0 ]; then
    echo "cstr-ref-return FAILED: $failed failures"
    exit 1
fi
echo "cstr-ref-return OK: an explicitly converted byte reference retains its pointer"
