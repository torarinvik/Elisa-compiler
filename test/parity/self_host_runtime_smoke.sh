#!/usr/bin/env bash
# SELF-HOSTING THE STANDARD LIBRARY: stage1 compiles elisacore_std's runtime support into an
# object, and a program linked against THAT object gives the same answer as against the
# stage0-built one.
#
# This is the half of self-hosting the bootstrap fixpoint does NOT cover. gen2/gen3 prove
# stage1 reproduces the COMPILER; they say nothing about the runtime, because every gen links
# the stage0-built elisacore_runtime.o. Until this smoke existed, stage1 could not build a
# usable runtime at all and nothing noticed:
#
#   - emit_module_core declined any module without `main`, so a library object was refused
#     outright and the driver reported it as a bare exit 2 (594e3d2);
#   - once it emitted, `arena_free` released its auto region BY CALLING ITSELF, so the object
#     segfaulted in that function's prologue (37b614d);
#   - then `x.f.g` through a ref FIELD read/wrote the SLOT instead of the pointee — in three
#     separate emitter sites — which spun arena_alloc forever and corrupted Region bookkeeping
#     on every allocation (cc9bc47, 5e9fd17, 1fb89f1).
#
# Every one of those was invisible to the full gate, because in an ordinary program the Elisa
# runtime bodies are DEAD CODE: calls bind to elisacore_runtime.o's copies. They only become
# live when that object is the one being built. Hence this smoke.
#
# The program is compiled by STAGE0 on purpose. That isolates the RUNTIME OBJECT as the only
# stage1-produced input, so a failure here cannot be blamed on program codegen.
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 30 "$@"; else "$@"; fi; }
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0_RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
SUPPORT="$ROOT/elisacore_std/native_runtime_support.elisa"

[ -x "$ELISACORE_BIN" ] || { echo "self_host_runtime SKIP: no stage0 at $ELISACORE_BIN"; exit 0; }
[ -x "$STAGE1" ]        || { echo "self_host_runtime SKIP: no stage1 seed at $STAGE1"; exit 0; }
[ -f "$STAGE0_RUNTIME" ]|| { echo "self_host_runtime SKIP: no stage0 runtime at $STAGE0_RUNTIME"; exit 0; }
[ -f "$SUPPORT" ]       || { echo "self_host_runtime SKIP: no $SUPPORT"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
fail=0

# -O0 matches scripts/build_runtime_object.sh; the default -O3 has its own stage0 emit crash.
if ! bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -o "$WORK/rt_stage1.o" "$SUPPORT" \
        >"$WORK/build.log" 2>&1; then
    echo "self_host_runtime FAILED: stage1 could not compile $SUPPORT"
    grep -v 'warning:' "$WORK/build.log" | tail -5
    exit 1
fi

# The runtime must EXPORT what a program links against; internalizing everything produces an
# object that builds clean and resolves nothing (the failure mode 02303f3 fixed).
exported=$(nm -g --defined-only "$WORK/rt_stage1.o" 2>/dev/null | wc -l | tr -d ' ')
if [ "$exported" -lt 100 ]; then
    echo "self_host_runtime FAILED: object exports only $exported symbols — expected 100+"
    exit 1
fi

# Exercise allocation, growth (arena_realloc), and iteration — the paths the miscompiles hit.
cat > "$WORK/prog.elisa" <<'ELISAEOF'
def main() -> i64:
    can Abort.Panic, Memory.Allocate:
        xs: mutable darray[i64] = []
        for i in 0..<64:
            xs.push(i * 3)
        total: mutable i64 = 0
        for x in xs |total|:
            total <- total + x
        return total + xs.count.i64()
ELISAEOF

if ! "$ELISACORE_BIN" -emit obj -o "$WORK/prog.o" "$WORK/prog.elisa" >"$WORK/prog.log" 2>&1; then
    echo "self_host_runtime FAILED: stage0 could not compile the probe program"
    grep -v 'warning:' "$WORK/prog.log" | tail -5
    exit 1
fi

link_and_run() {
    local runtime="$1" out="$2"
    if ! clang -Wl,-dead_strip -o "$out" "$WORK/prog.o" "$runtime" >"$WORK/link.log" 2>&1; then
        echo "  link failed against $runtime"; sed -n '1,6p' "$WORK/link.log"; return 255
    fi
    RUN "$out"; return $?
}

link_and_run "$STAGE0_RUNTIME" "$WORK/prog.rt0"; want=$?
link_and_run "$WORK/rt_stage1.o" "$WORK/prog.rt1"; got=$?

# 139 = SIGSEGV, 124 = timeout (a HANG, which is what the arena_alloc region-walk bug produced).
if [ "$want" -eq 139 ] || [ "$want" -eq 124 ] || [ "$want" -eq 255 ]; then
    echo "self_host_runtime FAILED: the stage0-built runtime itself did not run (exit $want) — the check is broken, not stage1"
    exit 1
fi
if [ "$got" -ne "$want" ]; then
    echo "self_host_runtime FAILED: stage1-built runtime gave $got, stage0-built gave $want"
    [ "$got" -eq 139 ] && echo "  (139 = SIGSEGV)"
    [ "$got" -eq 124 ] && echo "  (124 = TIMED OUT — a hang, not a wrong answer)"
    fail=1
fi

if [ "$fail" -ne 0 ]; then
    exit 1
fi
echo "self_host_runtime OK: stage1 built elisacore_runtime.o ($exported exports); program agrees with the stage0-built object (exit $want)"
