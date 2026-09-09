#!/usr/bin/env bash
# Stage1 backend smoke: compile Elisa -> native and assert the program's real BEHAVIOR.
#
# The whole point is that this asserts an EXIT CODE, not "the compiler didn't crash":
# stage1 lexes + parses the source, its own backend drives LLVM-C to build a module, and
# we assemble/link/RUN the result. If any link in that chain is wrong, the exit code is
# wrong.
#
# Build notes (both learned the hard way, see llvm_c.elisa):
#   * `-emit obj` output is self-contained (its only undefined symbols are libc); do NOT
#     also link elisacore_runtime.o or you get duplicate symbols.
#   * `-emit c-archive` MIS-COMPILES this tree — the packed-store analysis fails on the
#     unmodified test/breadth/parse_report.elisa too, so it is a pre-existing stage0 bug,
#     not a backend one. Hence `-emit obj` + clang here.
#
# Every compiled binary runs under a TIMEOUT. A wrong loop does not fail, it HANGS, and an
# untimed gate hangs with it (observed: a stage0-compiled `while` spun at 100% CPU
# forever). A timeout turns that into an ordinary failure.
#
# The timeout is RETRIED with a wider budget before it is believed. These programs finish in
# milliseconds, so a 10s expiry means either a runaway loop -- which never finishes, and so
# expires again -- or a host that was busy enough to stretch a 300ms program past ten
# seconds. That second case is real: on a swapping machine this gate reported a DIFFERENT
# set of "runaway loop" cases on every run, including ones where the STAGE0 binary was the
# one that timed out. Retrying costs 30s on a genuine hang and removes the false positives.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/run_timeout.sh"
RUN() { elisa_run_timeout 10 "$@"; }
set -u
# A MISSPELLED or not-yet-defined check helper is `command not found` -- which bash reports
# on stderr and then keeps going, so the check never runs, `total` never increments, and the
# gate still prints OK. That is a gate that silently stops testing. Trap it: any unknown
# command marks the run failed (observed with a `stage1_ir_case` call placed above its own
# definition, which cost two checks with a green result).
command_not_found_handle() { echo "  FAIL: unknown command '$1' -- a check did not run"; helper_missing=1; }
helper_missing=0

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"

if [ ! -x "$ELISACORE_BIN" ]; then echo "backend_native_smoke SKIP: no elisac at $ELISACORE_BIN"; exit 0; fi
if [ ! -x "$LLVM_CONFIG" ]; then echo "backend_native_smoke SKIP: no llvm-config at $LLVM_CONFIG"; exit 0; fi

LIBDIR="$("$LLVM_CONFIG" --libdir)"
LLC="$("$LLVM_CONFIG" --bindir)/llc"
BUILD="$ROOT/build"
mkdir -p "$BUILD"

# 1. Build the stage1 native emitter (itself an Elisa program).
# Shared, race-free builder (see build_emit_native.sh); run_all primes it once.
if ! ELISA_EMIT_NATIVE="$BUILD/emit_native" REPO_ROOT="$ROOT" bash "$ROOT/test/parity/build_emit_native.sh"; then
    echo "backend_native_smoke FAILED: could not build emit_native"; exit 1
fi

# Extract elisacore_runtime.o from a throwaway c-archive. Emitted programs link against
# it because a darray's backing comes from the Elisa runtime (arena_alloc/realloc/free) —
# the backend is no longer self-contained once containers are in play. Scalar programs
# simply do not reference these symbols, so linking it unconditionally is harmless.
# NOT build/runtime: that directory holds the digest-stamped runtime object that
# build_runtime_object.sh maintains and every downstream project (elisa-ui among them)
# links against. This extraction used to land there too, so each run of this smoke
# silently replaced the stamped object with a stage0 c-archive's copy -- a runtime from a
# different compiler than the product beside it, and one whose stamp no longer matched.
RUNTIME_DIR="$BUILD/backend_smoke_runtime"
mkdir -p "$RUNTIME_DIR"
printf 'def main() -> i64:\n    s: mutable darray[u8] = []\n    s.push(1)\n    return s.count.i64() - 1\n' > "$RUNTIME_DIR/probe.elisa"
if "$ELISACORE_BIN" -emit c-archive -o "$RUNTIME_DIR/probe.a" "$RUNTIME_DIR/probe.elisa" 2>/dev/null; then
    ( cd "$RUNTIME_DIR" && ar x probe.a elisacore_runtime.o 2>/dev/null )
fi
RUNTIME_OBJ="$RUNTIME_DIR/elisacore_runtime.o"
if [ ! -f "$RUNTIME_OBJ" ]; then
    echo "backend_native_smoke FAILED: could not extract elisacore_runtime.o"; exit 1
fi

pass=0
total=0

SMOKE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SMOKE_DIR/backend_smoke_behavior.sh"
source "$SMOKE_DIR/backend_smoke_ir.sh"
source "$SMOKE_DIR/backend_smoke_differential.sh"
source "$SMOKE_DIR/backend_smoke_declines.sh"

if [ "$pass" -ne "$total" ]; then
    echo "backend_native_smoke FAILED: passed=$pass total=$total"
    exit 1
fi
if [ "$helper_missing" -ne 0 ]; then
    echo "backend_native_smoke FAILED: a check helper was undefined, so some checks never ran"
    exit 1
fi
echo "backend_native_smoke OK: $pass/$total native compile-and-run checks"

