#!/usr/bin/env bash
# BEHAVIOURAL differential: compile a corpus of real programs with BOTH compilers, RUN
# both, and require the same exit code.
#
# Every other parity check asks whether stage1 ACCEPTS what stage0 accepts. None of them
# ask whether it computes the SAME ANSWER. That gap is not theoretical: `.uintptr()` on a
# ref returned the pointee instead of the address, so `&a[0]` and `&a[4]` compared equal —
# no decline, no link error, a fully green 132-check gate, and a byte-identical gen3
# fixpoint, because the compiler's own source only ever takes `&xs[0]`. A construct the
# compiler uses only in its degenerate form is invisible to self-hosting.
#
# Outcomes per program:
#   MATCH     both compiled, linked, ran, same exit code                — the good case
#   MISMATCH  both ran, DIFFERENT exit codes                            — a silent miscompile
#   DECLINED  stage0 built it, stage1 could not compile or link it      — the acceptance gap
#   SKIP      stage0 itself could not build/link/run it                 — not a parity signal
#
# MISMATCH is ratcheted at zero: a wrong answer is worse than a decline, because a decline
# is loud (an undefined symbol at link) and a wrong answer is not. DECLINED is ratcheted
# separately and is expected to fall as backend coverage grows.
#
#   Usage: test/parity/differential_corpus.sh [--verbose]
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
BASELINE="$ROOT/test/fixtures/differential_corpus.baseline"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"
VERBOSE=0
[[ "${1:-}" == "--verbose" ]] && VERBOSE=1

[ -x "$ELISACORE_BIN" ] || { echo "differential_corpus SKIP: no stage0 at $ELISACORE_BIN"; exit 0; }
[ -x "$STAGE1" ]        || { echo "differential_corpus SKIP: no stage1 seed at $STAGE1"; exit 0; }
[ -f "$RUNTIME_OBJ" ]   || { echo "differential_corpus SKIP: no runtime object"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

# A program that loops forever is a FAILURE, not a hang: bound every run. Compilation is
# bounded too — a backend that diverges would otherwise stall the gate.
RUN() { timeout 10 "$@" >/dev/null 2>&1 </dev/null; }
COMPILE_TIMEOUT=60

# Link an object into a runnable program. THREE recipes, tried in order, because the plain
# one silently cost this check SIX programs — counted as "stage0 could not arbitrate" when
# the truth was that the LINK LINE was wrong, and among them `emit_obj` and `emit_native`,
# the compiler-driver programs, i.e. the most valuable answers in the corpus to compare.
#
#   1. object + runtime — the ordinary program.
#   2. object ALONE — a program that INCLUDES the std defines the runtime itself, so adding
#      the object duplicates every symbol ("duplicate symbol '_perm_arena'"). This is how
#      test/parity/build_parse_report.sh has always linked parse_report.
#   3. object + runtime + libLLVM — a program that drives the backend calls LLVM-C directly
#      (`_LLVMAddFunction`, `_LLVMArrayType`, …), exactly as scripts/self_host_gen2.sh links.
#
# Both compilers go through this same function, so whichever recipe wins is the same for
# each and the comparison stays fair.
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LLVM_LIBDIR="$("$LLVM_CONFIG" --libdir 2>/dev/null || true)"
link_program() {
    local out="$1" obj="$2"
    clang -Wl,-dead_strip -o "$out" "$obj" "$RUNTIME_OBJ" >/dev/null 2>&1 && return 0
    clang -Wl,-dead_strip -o "$out" "$obj" >/dev/null 2>&1 && return 0
    [ -n "$LLVM_LIBDIR" ] || return 1
    clang -Wl,-dead_strip -o "$out" "$obj" "$RUNTIME_OBJ" \
        -L"$LLVM_LIBDIR" -lLLVM -Wl,-rpath,"$LLVM_LIBDIR" >/dev/null 2>&1 && return 0
    return 1
}

# Programs with a TRIAGED intermittent stage1 failure. Each must have a recorded
# reproducer; see memory/stage1-intermittent-segfault.md. Empty is the goal.
#
# EMPTY as of the `[@r]` arena-threading fix: `easm_lockstep_parse_smoke` was the only entry,
# and it was a use-after-free of a munmap'd region (0/400 after the fix, 13/400 before).
# Do not add an entry here without a REPRODUCER. The way that one was finally caught was to
# make the failure deterministic rather than to run it more times: patch `free_region` in
# elisacore_std/arena.elisa to `mprotect(addr, size, 0)` instead of `munmap`, rebuild the
# runtime object, and every use-after-free faults on the spot with a usable lldb backtrace
# (stage0 0/40, stage1 40/40). Worth reaching for first next time.
KNOWN_INTERMITTENT=()

match=0; mismatch=0; declined=0; skipped=0; intermittent=0
: > "$WORK/mismatches.txt"
: > "$WORK/declines.txt"
: > "$WORK/flaky.txt"
: > "$WORK/intermittent.txt"

# The corpus: every .elisa in the stage1 tree with a top-level `main`. Excludes build
# outputs and the vendored runtime (compiled as a unit elsewhere, not as a program).
# (a while-read loop, not `mapfile`: the system bash here is 3.2, which lacks it)
# -print0/-0 is REQUIRED: the repo path contains spaces, and plain xargs split on them,
# silently yielding an EMPTY corpus and a green "0 programs" run.
# stage0's own tree is included when present: it is far larger than this repo's fixtures
# and exercises constructs stage1's source never uses — which is exactly where a
# degenerate-form blind spot like the `.uintptr()` bug hides. Self-filtering: anything
# stage0 cannot build and run is skipped, so scratch files cost nothing but time.
# An ARRAY, not a space-joined string: these paths contain spaces, and word-splitting a
# joined string yields nonexistent directories and a silent EMPTY corpus.
CORPUS_DIRS=("$ROOT/test" "$ROOT/.probe")
[ -d "$ELISA_CORE" ] && CORPUS_DIRS+=("$ELISA_CORE")
find "${CORPUS_DIRS[@]}" -name '*.elisa' -print0 2>/dev/null \
  | xargs -0 grep -l '^def main' 2>/dev/null | sort > "$WORK/programs.txt"

# Read the list on FD 3, and give every child /dev/null for stdin. Reading it on plain
# stdin loses the corpus: a compiled program that reads input DRAINS the list, and the loop
# silently stops after one entry (observed: "1 programs" from a 59-program corpus).
while IFS= read -r src <&3; do
    [ -n "$src" ] || continue
    name="$(basename "$src" .elisa)"

    # ---- stage0 is the ORACLE. If IT cannot produce a running program, this file is not
    # a parity signal (a fixture meant to fail to compile, a driver needing stdin, ...).
    if ! timeout "$COMPILE_TIMEOUT" "$ELISACORE_BIN" -emit obj -o "$WORK/$name.s0.o" "$src" >/dev/null 2>&1 </dev/null; then
        skipped=$((skipped + 1)); continue
    fi
    if ! link_program "$WORK/$name.s0" "$WORK/$name.s0.o"; then
        skipped=$((skipped + 1)); continue
    fi
    RUN "$WORK/$name.s0"; s0_rc=$?
    # 124 = timeout. An oracle that hangs cannot arbitrate.
    if [ "$s0_rc" -eq 124 ]; then skipped=$((skipped + 1)); continue; fi

    # ---- stage1. A compile or link failure is the ACCEPTANCE gap, not a wrong answer:
    # a declined function is dropped, so the link fails with an undefined symbol.
    if ! timeout "$COMPILE_TIMEOUT" env ELISA_STAGE1_BIN="$STAGE1" bash "$ROOT/scripts/elisac_stage1.sh" \
            -o "$WORK/$name.s1.o" "$src" >/dev/null 2>&1 </dev/null; then
        declined=$((declined + 1)); echo "$name (compile)" >> "$WORK/declines.txt"; continue
    fi
    if ! link_program "$WORK/$name.s1" "$WORK/$name.s1.o"; then
        declined=$((declined + 1)); echo "$name (link: a declined function was dropped)" >> "$WORK/declines.txt"; continue
    fi
    RUN "$WORK/$name.s1"; s1_rc=$?

    # A disagreement must REPRODUCE before it counts. Two ways this gate can cry wolf, both
    # observed or reachable:
    #   * NONDETERMINISM. The corpus sweeps stage0's own tree, which holds the concurrency
    #     smokes (pool_stress, threading, par_map, nursery); their exit codes depend on
    #     scheduling.
    #   * A STAGE1 TIMEOUT. `s0_rc -eq 124` is skipped above, but 124 from the stage1 run
    #     was just another exit code — so a program that ran slow under load was reported
    #     as a silent miscompile.
    # A "1 program produces a DIFFERENT ANSWER" failure did fire once here and did not
    # reproduce across five later runs with no compiler change in between. That is worse
    # than a missing check: MISMATCH is the one thing ratcheted at zero, so a gate that
    # cries wolf trains the next REAL wrong answer to be waved through as "the flaky one".
    #
    # Re-running only on disagreement keeps the happy path at one run per compiler.
    if [ "$s0_rc" != "$s1_rc" ]; then
        RUN "$WORK/$name.s0"; s0_rc2=$?
        RUN "$WORK/$name.s1"; s1_rc2=$?
        # Only an UNSTABLE ORACLE justifies a skip. An unstable STAGE1 does not: this very
        # check first reported `easm_lockstep_parse_smoke` as stage0 42/42, stage1 139/42 —
        # an INTERMITTENT SEGFAULT in stage1-compiled code, which is a worse bug than a
        # steady wrong answer, not a reason to look away. Classing "stage1 varies" as flaky
        # would have buried it.
        if [ "$s0_rc" != "$s0_rc2" ]; then
            skipped=$((skipped + 1))
            echo "$name (oracle nondeterministic: stage0 $s0_rc/$s0_rc2)" >> "$WORK/flaky.txt"
            continue
        fi
        # stage1 disagreeing with ITSELF is still a stage1 defect: report the failing run.
        # KNOWN_INTERMITTENT holds the ones already triaged and recorded, so the gate stays
        # DETERMINISTIC instead of failing on whichever ~3% run happens to crash. They are
        # printed every run, loudly, and counted separately — this is a to-do list, not an
        # exemption, and it should only ever shrink.
        # `${a[@]+"${a[@]}"}`: bash 3.2 (macOS) treats an EMPTY array as unbound under `set -u`,
        # so the plain expansion would abort the gate now that the list is empty.
        if [ "$s1_rc" != "$s1_rc2" ] && printf '%s\n' ${KNOWN_INTERMITTENT[@]+"${KNOWN_INTERMITTENT[@]}"} | grep -qx "$name"; then
            intermittent=$((intermittent + 1))
            echo "$name (stage0 $s0_rc, stage1 $s1_rc/$s1_rc2)" >> "$WORK/intermittent.txt"
            continue
        fi
        if [ "$s1_rc" != "$s1_rc2" ]; then
            mismatch=$((mismatch + 1))
            printf '%-44s stage0=%-4s stage1=%s/%s (INTERMITTENT)  %s\n' "$name" "$s0_rc" "$s1_rc" "$s1_rc2" "$src" >> "$WORK/mismatches.txt"
            continue
        fi
        s0_rc=$s0_rc2
        s1_rc=$s1_rc2
    fi

    if [ "$s0_rc" -eq "$s1_rc" ]; then
        match=$((match + 1))
    else
        mismatch=$((mismatch + 1))
        printf '%-44s stage0=%-4s stage1=%-4s  %s\n' "$name" "$s0_rc" "$s1_rc" "$src" >> "$WORK/mismatches.txt"
    fi
done 3< "$WORK/programs.txt"

# The loop body runs in THIS shell (redirect, not a pipe), so the counters below are the
# real totals — piping `find` straight into `while` would subshell them away to zero.

total=$((match + mismatch + declined + skipped + intermittent))
echo "differential corpus: $total programs — $match match, $mismatch MISMATCH, $declined declined, $skipped skipped (stage0 could not arbitrate)" >&2

if [ "$mismatch" -gt 0 ]; then
    echo "SILENT MISCOMPILES — both compilers ran the program, answers differ:" >&2
    cat "$WORK/mismatches.txt" >&2
fi
# Always surfaced, not gated on VERBOSE: a program that quietly stopped arbitrating is
# coverage silently lost, which is exactly the failure mode this harness exists to avoid.
if [ -s "$WORK/intermittent.txt" ]; then
    echo "KNOWN INTERMITTENT stage1 FAILURES (triaged, still open — must shrink to zero):" >&2
    cat "$WORK/intermittent.txt" >&2
fi
if [ -s "$WORK/flaky.txt" ]; then
    echo "NONDETERMINISTIC (skipped — cannot arbitrate):" >&2
    cat "$WORK/flaky.txt" >&2
fi
if [ "$VERBOSE" -eq 1 ] && [ "$declined" -gt 0 ]; then
    echo "declined by stage1:" >&2
    cat "$WORK/declines.txt" >&2
fi

# Ratchet. MISMATCH must be 0 — a wrong answer is never acceptable. DECLINED rides a
# baseline that should only ever fall.
#
# The baseline is 2, and BOTH entries are named so it cannot drift into a dumping ground:
#   regular_enum_values — the DELIBERATE policy decline (stage0 lowers a bare `x = v` to a
#     shadowing declaration and compiles `while i < 3: i = i + 1` into an infinite loop;
#     stage1 refuses). Recorded in docs and in memory/stage1-parity-status.
#   emit_obj_debug_ir — a REAL stage1 bug, found the moment the link recipes below made
#     this program arbitrable at all: any program that calls the std's `print` leaves an
#     undefined `_print__unknown`. Call resolution tries the GENERIC `print[T: Str]` BEFORE
#     the non-generic overloads (codegen_call.elisa: `generic_index_of` is checked above
#     `lookup_function`), so an exact `def print(value: cstr)` never wins; the generic is
#     then instantiated at cstr, its `T.__cast__(value)` body DECLINES, and the symbol is
#     dropped. Reproduces in three lines — `print("hi")` with the std included. Lower this
#     back to 1 when that lands.
allowed_declines=0
[ -f "$BASELINE" ] && allowed_declines="$(tr -d '[:space:]' < "$BASELINE")"

rc=0
if [ "$mismatch" -gt 0 ]; then
    echo "differential corpus FAILED: $mismatch program(s) produce a DIFFERENT ANSWER under stage1" >&2
    rc=1
fi
if [ "$declined" -gt "$allowed_declines" ]; then
    echo "differential corpus FAILED: $declined declines exceeds baseline $allowed_declines" >&2
    echo "  (see test/fixtures/differential_corpus.baseline)" >&2
    rc=1
fi
if [ "$declined" -lt "$allowed_declines" ]; then
    echo "differential corpus: IMPROVED to $declined declines (baseline $allowed_declines) — commit it: echo $declined > $BASELINE" >&2
fi
[ "$rc" -eq 0 ] && echo "differential corpus OK: $match match, 0 mismatches, $declined declined (baseline $allowed_declines)" >&2
exit "$rc"
