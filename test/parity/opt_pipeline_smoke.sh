#!/usr/bin/env bash
# OPTIMISATION MUST NEVER CHANGE ANSWERS. stage1's -O1/-O2/-O3 run LLVM's `default<O{n}>`
# pipeline (they were rejected outright while `default<O2>` trapped on large self-host
# modules — those traps were the opaque-handle `==` and arena-identity miscompiles in the
# self-hosted binary, fixed 2026-08-02/03). This smoke compiles every runnable repro
# fixture at -O0, -O2 AND -O3 and demands the SAME exit code from all three; -O2 must also match the
# recorded -O0 answer, so a pipeline that "fixes" a latent miscompile by optimising it away
# still fails loudly.
#
# `-emit llvm` is exercised on one fixture: the module must parse as textual IR (llvm-as or
# clang can consume it) and contain the program's main.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
[ -f "$RUNTIME_OBJ" ] || { echo "opt_pipeline SKIP: no runtime object"; exit 0; }
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LLVM_BIN_DIR="${ELISA_LLVM_BIN_DIR:-$(dirname -- "$LLVM_CONFIG")}"
LLVM_CLANG="${ELISA_CLANG:-$LLVM_BIN_DIR/clang}"
if [ ! -x "$LLVM_CLANG" ]; then
    LLVM_CLANG="$(command -v clang || true)"
fi
[ -x "$LLVM_CLANG" ] || { echo "opt_pipeline SKIP: no clang for LLVM_CONFIG=$LLVM_CONFIG"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

# A 124 from `timeout` is retried with a wider budget before it is believed. Every one of
# these fixtures finishes in well under a second; on a loaded host a single 10s expiry
# reported "-O0 exit 42, -O2 exit 124" for sixteen fixtures at once — the exact signature
# of "optimisation changed the answer", fabricated by scheduling. A binary that genuinely
# spins expires at 30s too and still fails.
RUN_TIMED() {
    local status
    timeout 10 "$@" >/dev/null 2>&1 </dev/null; status=$?
    if [ "$status" -eq 124 ]; then timeout 30 "$@" >/dev/null 2>&1 </dev/null; status=$?; fi
    return $status
}

checked=0
failed=0
for src in "$ROOT"/test/repro/*.elisa; do
    name="$(basename "$src" .elisa)"
    grep -q "def main() -> i64" "$src" || continue
    # -O0 (the baseline the corpus already validates against stage0)
    if ! bash "$ROOT/scripts/elisac_stage1.sh" -O0 -o "$WORK/$name.o0.o" "$src" >/dev/null 2>&1; then
        continue    # a decline is the corpus's business, not this smoke's
    fi
    "$LLVM_CLANG" -Wl,-dead_strip -o "$WORK/$name.o0" "$WORK/$name.o0.o" "$RUNTIME_OBJ" >/dev/null 2>&1 || continue
    RUN_TIMED "$WORK/$name.o0"; rc0=$?
    [ "$rc0" -eq 124 ] && continue
    # -O2 through the pass pipeline
    if ! bash "$ROOT/scripts/elisac_stage1.sh" -O2 -o "$WORK/$name.o2.o" "$src" >/dev/null 2>&1; then
        echo "  FAIL $name: -O2 compile failed where -O0 succeeded"
        failed=$((failed + 1)); continue
    fi
    "$LLVM_CLANG" -Wl,-dead_strip -o "$WORK/$name.o2" "$WORK/$name.o2.o" "$RUNTIME_OBJ" >/dev/null 2>&1 || { echo "  FAIL $name: -O2 link"; failed=$((failed + 1)); continue; }
    RUN_TIMED "$WORK/$name.o2"; rc2=$?
    checked=$((checked + 1))
    if [ "$rc0" != "$rc2" ]; then
        echo "  FAIL $name: -O0 exit $rc0, -O2 exit $rc2"
        failed=$((failed + 1))
    fi
    # -O3 as well. It is NOT a duplicate of -O2: its CGSCC pipeline adds passes -O2 never
    # runs (ArgumentPromotion among them), and one of those rewrites call arguments from the
    # callee's REAL signature. A synthesized call built with the wrong ARITY is undefined
    # rather than invalid under opaque pointers, so `opt -passes=verify` reads it as clean --
    # the set membership helper was called with 2 arguments where its instantiation declared
    # 3, and only -O3 ever noticed, by dying with SIGBUS.
    if ! bash "$ROOT/scripts/elisac_stage1.sh" -O3 -o "$WORK/$name.o3.o" "$src" >/dev/null 2>&1; then
        echo "  FAIL $name: -O3 compile failed where -O0 succeeded"
        failed=$((failed + 1)); continue
    fi
    "$LLVM_CLANG" -Wl,-dead_strip -o "$WORK/$name.o3" "$WORK/$name.o3.o" "$RUNTIME_OBJ" >/dev/null 2>&1 || { echo "  FAIL $name: -O3 link"; failed=$((failed + 1)); continue; }
    RUN_TIMED "$WORK/$name.o3"; rc3=$?
    if [ "$rc0" != "$rc3" ]; then
        echo "  FAIL $name: -O0 exit $rc0, -O3 exit $rc3"
        failed=$((failed + 1))
    fi
done

# -emit llvm: one fixture, textual IR out, must contain main and round-trip through clang.
LL_SRC="$ROOT/test/repro/region_statement_form.elisa"
if bash "$ROOT/scripts/elisac_stage1.sh" -emit llvm -o "$WORK/ll.ll" "$LL_SRC" >/dev/null 2>&1 \
   && grep -q "define i64 @main" "$WORK/ll.ll" \
   && "$LLVM_CLANG" -c -o "$WORK/ll.o" "$WORK/ll.ll" >/dev/null 2>&1; then
    :
else
    echo "  FAIL -emit llvm: no parseable IR with @main"
    failed=$((failed + 1))
fi

# -emit exe: compile+link one fixture end to end and RUN it; the exit code must match
# the object-path build the loop above already validated.
EXE_SRC="$ROOT/test/repro/region_statement_form.elisa"
if bash "$ROOT/scripts/elisac_stage1.sh" -emit exe -o "$WORK/exe_probe" "$EXE_SRC" >/dev/null 2>&1; then
    RUN_TIMED "$WORK/exe_probe"; exe_rc=$?
    if [ "$exe_rc" != 42 ]; then
        echo "  FAIL -emit exe: exit $exe_rc, want 42"
        failed=$((failed + 1))
    fi
else
    echo "  FAIL -emit exe: build failed"
    failed=$((failed + 1))
fi

if [ "$failed" -gt 0 ]; then
    echo "opt_pipeline FAILED: $failed failures over $checked fixtures"
    exit 1
fi
echo "opt_pipeline OK: $checked fixtures agree at -O0, -O2 and -O3; -emit llvm round-trips"
