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
#
# PARALLEL (Phase T, 2026-09-06): every program is independent, so the per-program work
# runs under `xargs -P` (ELISA_CORPUS_JOBS, default = core count). The script re-enters
# itself as `--one <work> <src>` per program (xargs cannot call a bash function), each
# worker writes ONE result line into its own file under $WORK/res, and the parent reduces.
# Nothing is shared between workers but the read-only compilers. Measured: 49 min serial
# on a 32-core host -> minutes.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
BASELINE="$ROOT/test/fixtures/differential_corpus.baseline"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/structpy-tree}"
VERBOSE=0
[[ "${1:-}" == "--verbose" ]] && VERBOSE=1

[ -x "$ELISACORE_BIN" ] || { echo "differential_corpus SKIP: no stage0 at $ELISACORE_BIN"; exit 0; }
[ -x "$STAGE1" ]        || { echo "differential_corpus SKIP: no stage1 seed at $STAGE1"; exit 0; }
[ -f "$RUNTIME_OBJ" ]   || { echo "differential_corpus SKIP: no runtime object"; exit 0; }

# Worker mode (`--one <work> <src>`) receives the parent's work dir and must not create or
# clean one. (`set -u` above: an unset WORK in a worker used to kill it silently.)
if [[ "${1:-}" == "--one" ]]; then
    WORK="$2"
else
    WORK="$(mktemp -d)"
    trap 'rm -rf "$WORK"' EXIT INT TERM HUP
fi

# A program that loops forever is a FAILURE, not a hang: bound every run. Compilation is
# bounded too — a backend that diverges would otherwise stall the gate.
# A 124 is retried with a wider budget before it is believed: on a loaded host a paging
# stall can hold a fresh process in dyld past ten seconds, and a 124 on ONE side of the
# comparison fabricates a MISMATCH (observed: 3 mismatches in one run, 8 in the next, for
# an identical product). A genuine runaway expires both times and still fails.
RUN() {
    timeout 10 "$@" >/dev/null 2>&1 </dev/null
    local status=$?
    if [ "$status" -eq 124 ]; then timeout 30 "$@" >/dev/null 2>&1 </dev/null; status=$?; fi
    return $status
}
# Last resort for a program that expired BOTH budgets while the other compiler answered: on a
# host running several gates at once the thread/pool fixtures need more than 30 s of wall for
# work they do in two seconds idle, and a 124 on one side then reads as `stage0=42 stage1=124`
# — a fabricated MISMATCH (8 of them in one loaded run, none on a quiet host). A real runaway
# expires this budget too and is still reported.
RUN_LONG() {
    timeout "${ELISA_CORPUS_LONG_TIMEOUT:-180}" "$@" >/dev/null 2>&1 </dev/null
}
COMPILE_TIMEOUT=60
# …and the same rule for COMPILING. A compile that expires is not a DECLINE — the classifier
# below reads a nonzero exit as "stage1 dropped a function", so on a loaded host a slow
# compile was filed as a language gap (5 spurious declines against a baseline of 0 in one
# run; the same corpus on a quiet host declined only the known `lmut_threading_value`).
COMPILE() {
    timeout "$COMPILE_TIMEOUT" "$@" >/dev/null 2>&1 </dev/null
    local status=$?
    if [ "$status" -eq 124 ]; then
        timeout "${ELISA_CORPUS_LONG_TIMEOUT:-180}" "$@" >/dev/null 2>&1 </dev/null; status=$?
    fi
    return $status
}

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

# `$ELISA_CORE/repro/` is EXCLUDED. It holds minimal BUG DEMONSTRATIONS, most of
# them curated because stage1 does NOT agree with stage0 -- that is what the file
# is for. Sweeping them in asks a ratchet whose whole premise is "stage1 matches
# stage0" to enforce that over the one directory guaranteed to violate it, so
# every repro filed broke the gate. That punishes filing repros, which is exactly
# backwards.
#
# Measured before the exclusion: 145 programs, 1 MISMATCH and 11 declines, and
# ALL TWELVE were repro/ files. The mismatch was
# nw_json_hex_escape_literal_stage1, whose own header predicts "stage0: exit 4 /
# stage1: exit 14" -- the corpus was rediscovering a bug that was already written
# down, and failing the gate to report it.
#
# A repro that declines is a FILED BUG, not a regression. The ratchet's job is to
# catch regressions in ordinary programs; repros are tracked by their own files.
# A file carrying the header `# corpus: deliberate-decline` is EXCLUDED: it is a program
# stage0 compiles that stage1 REFUSES on purpose, with its own smoke asserting the refusal
# (assert_by_min_i64: stage0 proves `0 - MIN_I64 > 0` by wrapping; stage1 declines the
# overflowing extremum). The marker keeps the reason next to the program.
#
# `*.neg.elisa` is EXCLUDED too (2026-09-05). A negative fixture that stage0 ACCEPTS is,
# by construction, a place where stage1 is deliberately STRICTER (the effect-row `::` rule,
# for instance) and a dedicated smoke asserts the rejection with its message. Counting it
# here as a "decline" put three such fixtures on this ratchet the day they were written.
#
# `*.xfail.elisa` is EXCLUDED for the same reason as repro/, and it is the same mistake in a
# different costume. test/differential/cases/ names a case `*.xfail.elisa` when the
# divergence is already known, documented in the file's own header, and not yet fixed --
# the sibling runner (test/differential/run_differential.sh) reports it as XFAIL and fails
# the day it starts AGREEING, so the gap stays visible without a red suite. This gate scans
# the same directory with its own ratchet, so an xfail landed here as an unexplained
# MISMATCH: two harnesses over one corpus, disagreeing about what a known gap means. A
# documented divergence is a filed bug, not a regression.
find "${CORPUS_DIRS[@]}" -name '*.elisa' -print0 2>/dev/null \
  | xargs -0 grep -l '^def main' 2>/dev/null \
  | grep -v '/repro/' \
  | grep -v '\.xfail\.elisa$' \
  | grep -v '\.neg\.elisa$' \
  | tr '\n' '\0' | xargs -0 grep -L 'corpus: deliberate-decline' 2>/dev/null \
  | sort > "$WORK/programs.txt"

# ---- one program (worker mode). Prints exactly one line: KIND<TAB>name<TAB>detail
one_program() {
    local src="$1" name work
    name="$(basename "$src" .elisa)"
    # A private work dir per program: two corpus files may share a basename.
    work="$(mktemp -d "$WORK/p.XXXXXX")"
    # ---- stage0 is the ORACLE. If IT cannot produce a running program, this file is not
    # a parity signal (a fixture meant to fail to compile, a driver needing stdin, ...).
    if ! COMPILE "$ELISACORE_BIN" -emit obj -o "$work/s0.o" "$src"; then
        printf 'SKIP\t%s\t\n' "$name"; return 0
    fi
    if ! link_program "$work/s0" "$work/s0.o"; then printf 'SKIP\t%s\t\n' "$name"; return 0; fi
    RUN "$work/s0"; local s0_rc=$?
    # 124 = timeout. An oracle that hangs cannot arbitrate.
    if [ "$s0_rc" -eq 124 ]; then printf 'SKIP\t%s\t\n' "$name"; return 0; fi
    # ---- stage1. A compile or link failure is the ACCEPTANCE gap, not a wrong answer:
    # a declined function is dropped, so the link fails with an undefined symbol.
    if ! COMPILE env ELISA_STAGE1_BIN="$STAGE1" bash "$ROOT/scripts/elisac_stage1.sh" \
            -o "$work/s1.o" "$src"; then
        printf 'DECLINED\t%s\t(compile)\n' "$name"; return 0
    fi
    if ! link_program "$work/s1" "$work/s1.o"; then
        printf 'DECLINED\t%s\t(link: a declined function was dropped)\n' "$name"; return 0
    fi
    RUN "$work/s1"; local s1_rc=$?
    # A disagreement must REPRODUCE before it counts (nondeterministic concurrency smokes in
    # stage0's tree; a stage1 run that timed out under load). Re-running only on
    # disagreement keeps the happy path at one run per compiler.
    if [ "$s0_rc" != "$s1_rc" ]; then
        RUN "$work/s0"; local s0_rc2=$?
        RUN "$work/s1"; local s1_rc2=$?
        # Only an UNSTABLE ORACLE justifies a skip. An unstable STAGE1 is a stage1 defect
        # (an intermittent segfault is worse than a steady wrong answer, not a reason to
        # look away): it is reported as a MISMATCH unless triaged in KNOWN_INTERMITTENT.
        if [ "$s0_rc" != "$s0_rc2" ]; then
            printf 'FLAKY\t%s\t(oracle nondeterministic: stage0 %s/%s)\n' "$name" "$s0_rc" "$s0_rc2"; return 0
        fi
        if [ "$s1_rc" != "$s1_rc2" ] && printf '%s\n' ${KNOWN_INTERMITTENT[@]+"${KNOWN_INTERMITTENT[@]}"} | grep -x "$name" >/dev/null; then
            printf 'INTERMITTENT\t%s\t(stage0 %s, stage1 %s/%s)\n' "$name" "$s0_rc" "$s1_rc" "$s1_rc2"; return 0
        fi
        if [ "$s1_rc" != "$s1_rc2" ]; then
            printf 'MISMATCH\t%s\t%s\n' "$name" "$(printf '%-44s stage0=%-4s stage1=%s/%s (INTERMITTENT)  %s' "$name" "$s0_rc" "$s1_rc" "$s1_rc2" "$src")"; return 0
        fi
        # A reproduced stage1 TIMEOUT is not an answer. Give it one uncontended-sized budget
        # before believing it (see RUN_LONG); the oracle already answered, so only stage1 runs.
        if [ "$s1_rc2" -eq 124 ] && [ "$s0_rc2" -ne 124 ]; then
            RUN_LONG "$work/s1"; local s1_rc3=$?
            if [ "$s1_rc3" -ne 124 ]; then s1_rc2=$s1_rc3; fi
        fi
        s0_rc=$s0_rc2; s1_rc=$s1_rc2
    fi
    if [ "$s0_rc" -eq "$s1_rc" ]; then
        printf 'MATCH\t%s\t\n' "$name"
    else
        if [ "$s1_rc" -eq 124 ]; then
            printf 'MISMATCH\t%s\t%s\n' "$name" "$(printf '%-44s stage0=%-4s stage1=TIMEOUT  %s' "$name" "$s0_rc" "$src")"
        else
            printf 'MISMATCH\t%s\t%s\n' "$name" "$(printf '%-44s stage0=%-4s stage1=%-4s  %s' "$name" "$s0_rc" "$s1_rc" "$src")"
        fi
    fi
}

if [[ "${1:-}" == "--one" ]]; then
    # /dev/null on stdin belongs on the WORKER, never on xargs: `... | xargs ... </dev/null`
    # replaces the pipe with an empty stream and xargs runs the worker once with no program.
    exec </dev/null
    one_program "$3" > "$(mktemp "$WORK/res/r.XXXXXX")"
    exit 0
fi

source "$ROOT/test/parity/host_jobs.sh"
# A long pole: it starts first and sets the gate's makespan, so it takes the wider
# allowance (ELISA_HEAVY_JOBS, exported by run_all) rather than the fair share.
JOBS="${ELISA_CORPUS_JOBS:-${ELISA_HEAVY_JOBS:-$(elisa_host_jobs)}}"
mkdir -p "$WORK/res"
# Workers get /dev/null on stdin (a compiled program that reads input must not drain the
# list) and the corpus as NUL-separated arguments (paths contain spaces).
tr '\n' '\0' < "$WORK/programs.txt" \
  | xargs -0 -P "$JOBS" -n 1 env ELISACORE_BIN="$ELISACORE_BIN" ELISA_STAGE1_BIN="$STAGE1" ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" ELISA_CORE="$ELISA_CORE" LLVM_CONFIG="$LLVM_CONFIG" \
      bash "$0" --one "$WORK"

# Reduce: one line per program, deterministic order.
cat "$WORK/res"/r.* 2>/dev/null | sort > "$WORK/results.txt"
count_kind() { grep -c "^$1"$'\t' "$WORK/results.txt" 2>/dev/null || true; }
match="$(count_kind MATCH)"; mismatch="$(count_kind MISMATCH)"; declined="$(count_kind DECLINED)"
skipped=$(( $(count_kind SKIP) + $(count_kind FLAKY) )); intermittent="$(count_kind INTERMITTENT)"
awk -F'\t' '$1=="MISMATCH"{print $3}' "$WORK/results.txt" > "$WORK/mismatches.txt"
awk -F'\t' '$1=="DECLINED"{print $2" "$3}' "$WORK/results.txt" > "$WORK/declines.txt"
awk -F'\t' '$1=="FLAKY"{print $2" "$3}' "$WORK/results.txt" > "$WORK/flaky.txt"
awk -F'\t' '$1=="INTERMITTENT"{print $2" "$3}' "$WORK/results.txt" > "$WORK/intermittent.txt"

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
if [ "$declined" -gt 0 ]; then
    echo "declined by stage1:" >&2
    cat "$WORK/declines.txt" >&2
fi

# Ratchet. MISMATCH must be 0 — a wrong answer is never acceptable. DECLINED rides a
# baseline that should only ever fall.
#
# The baseline is 1, and that entry is NAMED so it cannot drift into a dumping ground:
#   regular_enum_values — the DELIBERATE policy decline. stage0 lowers a bare `x = v` to a
#     shadowing declaration, so `while i < 3: i = i + 1` compiles into an INFINITE LOOP with
#     no diagnostic; stage1 refuses. Modelling it faithfully would recover one corpus program
#     and reproduce the infinite loop. Recorded in docs/ and memory/stage1-parity-status.
#
# emit_obj_debug_ir was the other entry and is CLOSED: it needed three separate fixes, each
# hidden behind the last — the exact-overload wrong answer (160e4c1), the const-enum extern
# parameter (418be1a), and two externs sharing one C symbol being LLVM-uniquified.
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
