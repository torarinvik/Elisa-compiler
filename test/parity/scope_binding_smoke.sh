#!/usr/bin/env bash
# Stage1 backend smoke: local SCOPE, `is`-binding SLOTS, and match ALTERNATION arms,
# asserted by exit code.
#
# These are backend gaps the gen3 bootstrap exposed — cases a fixture gate cannot see by
# inspection, because the
# programs compile clean and then return the wrong answer (or segfault), because a load
# reads an alloca that the taken path never stored. Both were found only when gen2 tried
# to compile the compiler, and both are checked DIFFERENTIALLY: stage0 is the oracle, so
# a case that starts passing for the wrong reason still has to agree with stage0.
#
#   1. OR-CHAINED `is` BINDINGS. `e is A(x) or e is B(x)` short-circuits, so only the
#      alternative that matched runs. Giving each alternative its own slot and resolving
#      the body's `x` to the last one declared reads a slot nothing stored. stage0 opens
#      ONE entry-block slot per bound name for the whole condition; stage1 now does too.
#
#   2. SIBLING-BLOCK SHADOWING. A declaration inside a block must not outlive it. The
#      backend scope is a flat append-only list scanned BACKWARDS, so a leftover inner
#      declaration makes a LATER use of the same name resolve to the inner slot — which
#      the later path never stored. This is what killed gen2 on the compiler itself:
#      `emit_statement_loops` declares `int64_type` in the darray-`for` branch and the
#      range-`for` branch below it then allocated with that undominated slot.
#
#   3. MATCH ALTERNATION. `"u8" | "i8" | "bool": 1` — an arm with several literal options.
#      stage1 declined the whole function (which DROPS it, so the link fails), rather than
#      miscompiling it. Every option is compared and the results OR'd.
#
# Every compiled binary runs under a timeout: a scope bug can produce a spinning loop
# rather than a wrong answer, and an untimed gate hangs with it. The expiry is RETRIED with
# a wider budget before it is believed — these fixtures finish in milliseconds, and on a
# loaded host a single 10s expiry reported a 124 as a scope divergence (a wrong answer that
# vanished on the standalone re-run). A genuine spin expires both times and still fails.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/run_timeout.sh"
RUN() { elisa_run_timeout 10 "$@"; }
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"

[ -x "$ELISACORE_BIN" ] || { echo "scope_binding_smoke SKIP: no stage0 at $ELISACORE_BIN"; exit 0; }
[ -x "$STAGE1" ] || { echo "scope_binding_smoke SKIP: no stage1 seed at $STAGE1"; exit 0; }
[ -f "$RUNTIME_OBJ" ] || { echo "scope_binding_smoke SKIP: no runtime object at $RUNTIME_OBJ"; exit 0; }

# macOS's bare `mktemp -d` can silently fall back to the host's short-lived
# per-process temp directory. This suite compiles 80 cases and that directory
# may be reclaimed before the later cases run, turning a compiler check into a
# string of misleading "file not found" failures. Use an explicit template so
# TMPDIR is honored and callers can choose a stable scratch location.
WORK_ROOT="${TMPDIR:-/tmp}"
WORK="$(mktemp -d "$WORK_ROOT/elisa-scope-binding.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
pass=0
fail=0

# Compile `$2` with BOTH compilers, run both, and require stage1 == stage0 == `$3`.
differential() {
    local name="$1" src="$2" want="$3"
    printf '%s' "$src" > "$WORK/$name.elisa"

    if ! "$ELISACORE_BIN" -emit obj -o "$WORK/$name.s0.o" "$WORK/$name.elisa" >"$WORK/$name.s0.log" 2>&1; then
        echo "  FAIL $name: stage0 did not compile the case"; sed -n '1,5p' "$WORK/$name.s0.log"; fail=$((fail + 1)); return
    fi
    if ! clang -Wl,-dead_strip -o "$WORK/$name.s0" "$WORK/$name.s0.o" "$RUNTIME_OBJ" >>"$WORK/$name.s0.log" 2>&1; then
        echo "  FAIL $name: stage0 object did not link"; sed -n '1,5p' "$WORK/$name.s0.log"; fail=$((fail + 1)); return
    fi
    RUN "$WORK/$name.s0"; local s0=$?

    if ! ELISA_STAGE1_BIN="$STAGE1" bash "$ROOT/scripts/elisac_stage1.sh" -o "$WORK/$name.s1.o" "$WORK/$name.elisa" >"$WORK/$name.s1.log" 2>&1; then
        echo "  FAIL $name: stage1 did not compile the case"; sed -n '1,5p' "$WORK/$name.s1.log"; fail=$((fail + 1)); return
    fi
    if ! clang -Wl,-dead_strip -o "$WORK/$name.s1" "$WORK/$name.s1.o" "$RUNTIME_OBJ" >>"$WORK/$name.s1.log" 2>&1; then
        echo "  FAIL $name: stage1 object did not link"; sed -n '1,5p' "$WORK/$name.s1.log"; fail=$((fail + 1)); return
    fi
    RUN "$WORK/$name.s1"; local s1=$?

    if [ "$s0" != "$want" ]; then
        echo "  FAIL $name: stage0 (the ORACLE) returned $s0, expected $want — the case itself is wrong"
        fail=$((fail + 1)); return
    fi
    if [ "$s1" != "$s0" ]; then
        echo "  FAIL $name: stage1 returned $s1, stage0 returned $s0"
        fail=$((fail + 1)); return
    fi
    pass=$((pass + 1))
}
SMOKE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SMOKE_DIR/scope_smoke_bindings.sh"
source "$SMOKE_DIR/scope_smoke_pointers.sh"
source "$SMOKE_DIR/scope_smoke_ref_identity.sh"
source "$SMOKE_DIR/scope_smoke_generics.sh"
source "$SMOKE_DIR/scope_smoke_fn_types.sh"
source "$SMOKE_DIR/scope_smoke_surface.sh"
source "$SMOKE_DIR/scope_smoke_fn_values.sh"

if [ "$fail" -ne 0 ]; then
    echo "scope_binding_smoke FAILED: $pass passed, $fail failed" >&2
    exit 1
fi
echo "scope_binding_smoke OK: $pass/$pass" >&2

