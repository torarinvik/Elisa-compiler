#!/usr/bin/env bash
# BOOTSTRAP CLOSURE — the check the 123-smoke gate cannot make.
#
# `scripts/self_host_gen2.sh` proves only that gen1 can build a gen2 that compiles
# `def main() -> i64: return 42`. That is not self-hosting. Four separate stage1 backend
# miscompiles have shipped behind a fully green fixture gate precisely because nothing
# asked gen2 to compile anything real:
#
#   1758519  a multi-target `<-` rebound the name to a fresh slot, so a not-taken assign
#            left later reads on uninitialized stack   (gen2 died on any fn-type parameter)
#   05b3c03  a payload-free packed variant returned its ORDINAL as if it were a handle
#            (gen2 trapped on any `when`)
#   abddf8f  short-circuit `and`/`or` temporaries alloca'd once PER LOOP ITERATION, so a
#            flat loop over ~200k tokens walked into the stack guard page
#            an OR-chain of `is` tests gave each alternative its OWN binding slot, so a
#            short-circuited alternative left the body reading a slot nothing ever stored
#            (the garbage AST handle that reached ctx_aos_store_record)
#            block-local declarations outlived their block, so a later sibling block
#            resolved a shared name to the inner, never-stored slot
#
# Every one of those needed real input to surface. This script provides it.
#
# BOOTSTRAP IS CLOSED as of the scope/binding fixes: gen2 compiles the whole compiler and
# gen3 reproduces itself byte-for-byte. All three stages are hard assertions now — this is
# named *_smoke.sh so the aggregate gate runs it, and any regression turns the gate red.
#
# Stage A is a hard regression guard on the fixed blockers.
# Stage B requires gen2 to compile the compiler itself.
# Stage C requires the FIXPOINT: gen3.o == gen4.o, byte-identical.
set -uo pipefail
set +m   # a crashing gen2 is an EXPECTED outcome here; don't let job control narrate it
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
GEN2_DIR="${SELF_HOST_GEN2_DIR:-$ROOT/build/self_host_gen2}"
GEN2="$GEN2_DIR/elisac-stage1-gen2"
WORK="$ROOT/build/gen3_check"

# EXCLUSIVE, because every leg of this check shares mutable state under build/ with
# anything else that drives this worktree: $BIN (which `scripts/elisac_stage1.sh --seed`
# rewrites in place), $GEN2_DIR, and $WORK. A second smoke, or an elisa-ui build calling
# this worktree's elisac_stage1.sh, can therefore swap the compiler out from under a
# run in flight -- gen2 then gets built by one binary and gen3 by another, and stage C
# reports `gen3.o != gen4.o` for a divergence that does not exist. That false failure
# has already been chased once as if it were a miscompile; take the lock instead.
SMOKE_LOCK="$ROOT/build/.self_host_gen3.lock"
mkdir -p "$ROOT/build"
if ! mkdir "$SMOKE_LOCK" 2>/dev/null; then
    lock_pid=""
    [ -f "$SMOKE_LOCK/pid" ] && lock_pid="$(<"$SMOKE_LOCK/pid")"
    if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
        echo "self_host_gen3_smoke FAIL: another run holds $SMOKE_LOCK (pid $lock_pid); a concurrent run corrupts this check" >&2
        exit 1
    fi
    # Only the recorded owner being gone makes the lock stale; reclaim just this directory.
    rm -f "$SMOKE_LOCK/pid"
    rmdir "$SMOKE_LOCK" 2>/dev/null && mkdir "$SMOKE_LOCK" 2>/dev/null || {
        echo "self_host_gen3_smoke FAIL: could not acquire $SMOKE_LOCK" >&2
        exit 1
    }
fi
echo "$$" >"$SMOKE_LOCK/pid"
trap 'rm -f "$SMOKE_LOCK/pid"; rmdir "$SMOKE_LOCK" 2>/dev/null || true' EXIT INT TERM HUP

rm -rf "$WORK"; mkdir -p "$WORK"

# The exit code stage B must produce. 0 = bootstrap closed; anything else is a REGRESSION
# and must be investigated, not silently re-baselined.
BASELINE_GEN3_RC="${BASELINE_GEN3_RC:-0}"

fail() { echo "self_host_gen3_smoke FAIL: $1" >&2; exit 1; }

terminate_guarded_pid() {
    local pid="$1" ticks=0
    kill -TERM "$pid" 2>/dev/null || true
    while kill -0 "$pid" 2>/dev/null && [[ "$ticks" -lt 20 ]]; do
        sleep 0.1
        ticks=$((ticks + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
}

# Stage B/C feed the 11 MB flattened compiler through stdin. A shell pipeline cannot observe
# the compiler child reliably, so keep these two self-hosting legs under the same RSS ceiling as
# scripts/elisac_stage1.sh. This is an operational safety boundary, not a semantic fallback:
# crossing it fails the smoke and leaves the compiler bug visible instead of freezing the host.
run_guarded_request() {
    local binary="$1" request="$2" output="$3" pid rss peak=0 max_rss="${ELISA_STAGE1_MAX_RSS_KB:-4194304}"
    "$binary" <"$request" >"$output" 2>&1 &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        rss="$(ps -o rss= -p "$pid" 2>/dev/null | awk '{print $1}')" || rss=""
        if [[ -n "$rss" && "$rss" -gt "$peak" ]]; then
            peak="$rss"
        fi
        if [[ -n "$rss" && "$rss" -gt "$max_rss" ]]; then
            echo "self_host_gen3_smoke: memory guard stopped pid $pid at ${rss} KB (limit ${max_rss} KB; peak ${peak} KB)" >&2
            terminate_guarded_pid "$pid"
            return 125
        fi
        sleep "${ELISA_STAGE1_RSS_POLL_SECONDS:-0.05}"
    done
    wait "$pid"
}

[ -x "$BIN" ] || { echo "self_host_gen3_smoke SKIP: no seed ($BIN); run scripts/elisac_stage1.sh --seed"; exit 0; }
# The seed is a CACHED artifact and nothing rebuilds it automatically — `self_host_gen2.sh`
# happily builds gen2 from a stale gen1, which silently tests old code (this bit during
# development: stage A read 0/4 purely because the seed predated the fixes). Same failure
# shape as the 8-day-old build/emit_obj_debug_ir binary that hid a broken driver from the
# gate. Refuse to report on a seed older than the sources it claims to represent.
if [ -n "$(find "$ROOT/src" -name '*.elisa' -newer "$BIN" -print -quit 2>/dev/null)" ]; then
    fail "seed $BIN is OLDER than src/*.elisa — rebuild it (scripts/elisac_stage1.sh --seed) or this check reports on stale code"
fi
bash "$ROOT/scripts/self_host_gen2.sh" "$GEN2_DIR" >"$WORK/gen2.log" 2>&1 \
  || fail "self_host_gen2.sh did not produce a working gen2 (see $WORK/gen2.log)"
[ -x "$GEN2" ] || fail "no gen2 binary at $GEN2"

# ---- Stage A: gen2 must still compile the constructs the fixed blockers covered ----
# gen2 reads "<output path>\n<source>" on stdin.
run_gen2() { printf '%s\n%b' "$WORK/$1.o" "$2" | "$GEN2" >/dev/null 2>&1; }

a_pass=0; a_total=0
guard() {
    a_total=$((a_total + 1))
    if run_gen2 "$1" "$2"; then a_pass=$((a_pass + 1)); else echo "  FAIL gen2_$1 (regression: $3)"; fi
}
guard fn_type_param \
  'def take(body: fn(i64) -> i64) -> i64:\n    return 0\n\ndef main() -> i64:\n    return 42\n' \
  '1758519 — uninitialized slot from a not-taken multi-target assign'
guard fn_type_generic \
  'struct Slice[T]:\n    base: usize\n    count: usize\n\ndef each[T](s: Slice[T], body: fn(Slice[T]) -> i64, w: usize) -> void:\n    return\n\ndef main() -> i64:\n    return 42\n' \
  '1758519 / bare bracketed fn-type parameter'
guard when_table \
  'def f(n: i64) -> i64:\n    return when n:\n        0 -> 10\n        _ -> 20\n\ndef main() -> i64:\n    return f(0)\n' \
  '05b3c03 — payload-free packed variant returned its ordinal as a handle'
# MULTI-COLUMN `when`. This guard was green for a long time WITHOUT the backend having any
# lowering for it: gen2 exited 0 while dropping `f`, and `main` still called it, so the object
# it "successfully" produced could never link (`nm -u` showed `_f`; clang refuses it). It was
# reading a compile exit code that, before the driver rejected a program dropping a called
# body, meant nothing. Backed by the answer-checking fixture test/repro/when_multi_column.elisa
# now that the table is actually emitted.
guard when_or_columns \
  'def f(a: i64, b: i64) -> i64:\n    return when a, b:\n        0, 0 -> 10\n        _, _ -> 20\n\ndef main() -> i64:\n    return f(0, 0)\n' \
  'multi-column `when` — wildcard/or columns in a decision table'
guard when_string_columns \
  'def f(text: sview, enabled: bool) -> i64:\n    return when text, enabled:\n        "module" | "extend", _ -> 10\n        "ghost", true -> 20\n        _, _ -> 30\n\ndef main() -> i64:\n    return f("extend", false)\n' \
  'multi-column `when` — sview content equality and string alternation'

[ "$a_pass" -eq "$a_total" ] || fail "stage A regression: $a_pass/$a_total (a previously FIXED self-host blocker is back)"
echo "self_host_gen3_smoke stage A OK: $a_pass/$a_total (fixed blockers still fixed)"

# ---- Stage B: gen2 compiles the compiler itself ----
# Flattened the same way scripts/elisac_stage1.sh does, so this is exactly the gen3 input.
python3 - "$ROOT/src/driver/elisac.elisa" >"$WORK/flat.elisa" <<'PY' || fail "could not flatten the driver"
import re, pathlib, sys
path = pathlib.Path(sys.argv[1]).resolve()
include_re = re.compile(r'^[ \t]*(?:#\s*)?include[ \t]+"([^"]+)"[ \t]*$')
seen = set()
def flatten(p, out):
    ap = p.resolve()
    if ap in seen: return
    seen.add(ap)
    for line in p.read_text(encoding="utf-8").splitlines(keepends=True):
        m = include_re.match(line.rstrip("\n"))
        if m: flatten(p.parent / m.group(1), out)
        else: out.append(line)
out = []; flatten(path, out); sys.stdout.write("".join(out))
PY

{ printf '%s\n' "$WORK/gen3.o"; cat "$WORK/flat.elisa"; } >"$WORK/gen3.request"
rc=0
run_guarded_request "$GEN2" "$WORK/gen3.request" "$WORK/gen3.log" || rc=$?

[ "$rc" -eq "$BASELINE_GEN3_RC" ] \
  || fail "stage B exit $rc, baseline $BASELINE_GEN3_RC — bootstrap closure BROKE. Re-diagnose (lldb bt on the gen3 input); do not just re-baseline."
[ -s "$WORK/gen3.o" ] || fail "gen2 exited 0 but wrote no gen3 object"
echo "self_host_gen3_smoke stage B OK: gen2 compiled the compiler into gen3 ($(wc -c <"$WORK/gen3.o") bytes)."

# ---- Stage C: the FIXPOINT — gen3 must reproduce itself exactly ----
# Compiling is only half the claim. If gen2 and gen3 disagree about any emission, gen3's
# own output differs from what built it, and the compiler is not a fixed point of itself.
# gen4 is built from the SAME input file and the SAME output path as gen3, so a byte diff
# here is a real semantic difference, not a path or timestamp artifact.
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$LLVM_CONFIG" ]; then
    echo "self_host_gen3_smoke stage C SKIP: no llvm-config at $LLVM_CONFIG"
    exit 0
fi
LIBDIR="$("$LLVM_CONFIG" --libdir)"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
[ -f "$RUNTIME_OBJ" ] || fail "no runtime object at $RUNTIME_OBJ (run scripts/build_runtime_object.sh)"
clang -Wl,-dead_strip -o "$WORK/elisac-stage1-gen3" "$WORK/gen3.o" "$RUNTIME_OBJ" \
      -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" >"$WORK/gen3.link.log" 2>&1 \
  || fail "gen3 object did not link (see $WORK/gen3.link.log)"

{ printf '%s\n' "$WORK/gen4.o"; cat "$WORK/flat.elisa"; } >"$WORK/gen4.request"
rc4=0
run_guarded_request "$WORK/elisac-stage1-gen3" "$WORK/gen4.request" "$WORK/gen4.log" || rc4=$?
[ "$rc4" -eq 0 ] || fail "gen3 could not compile the compiler (exit $rc4) — gen2 and gen3 disagree"
# A mismatch here has TWO very different causes and the old message named only one.
# Either gen2 and gen3 genuinely disagree (a miscompile -- what this gate exists to
# catch), or a generation was not reproducible on this run, in which case comparing any
# two objects proves nothing about the compiler. Two mismatches have already been chased
# as miscompiles without the evidence to tell those apart, so on the failure path only,
# re-run BOTH generations on the same input and report what was actually observed.
# Deliberately no verdict: this prints the four sizes and lets the reader judge.
if ! cmp -s "$WORK/gen3.o" "$WORK/gen4.o"; then
    echo "self_host_gen3_smoke: gen3.o != gen4.o; re-running both generations to see which one is unstable" >&2
    { printf '%s\n' "$WORK/gen3.again.o"; cat "$WORK/flat.elisa"; } >"$WORK/again.request"
    run_guarded_request "$GEN2" "$WORK/again.request" "$WORK/gen3.again.log" || true
    { printf '%s\n' "$WORK/gen4.again.o"; cat "$WORK/flat.elisa"; } >"$WORK/again4.request"
    run_guarded_request "$WORK/elisac-stage1-gen3" "$WORK/again4.request" "$WORK/gen4.again.log" || true
    describe() { if [ -s "$1" ]; then printf '%s bytes' "$(wc -c <"$1" | tr -d ' ')"; else printf 'MISSING'; fi; }
    echo "  gen2 -> gen3.o        $(describe "$WORK/gen3.o")" >&2
    echo "  gen2 -> gen3.again.o  $(describe "$WORK/gen3.again.o")   (differs from gen3.o => gen2 is not reproducible)" >&2
    echo "  gen3 -> gen4.o        $(describe "$WORK/gen4.o")" >&2
    echo "  gen3 -> gen4.again.o  $(describe "$WORK/gen4.again.o")   (differs from gen4.o => gen3 is not reproducible)" >&2
    echo "  artifacts kept in $WORK" >&2
    fail "gen3.o != gen4.o — the compiler does not reproduce itself; read the four sizes above before assuming a miscompile"
fi
echo "self_host_gen3_smoke stage C OK: gen3.o == gen4.o byte-identical (FIXPOINT)."

# ---- Stage D: gen3 must be REPRODUCIBLE, not merely a fixed point ----
# A fixed point is a statement about TWO objects; it says nothing about whether either
# generation answers the same way twice. The compiler spent a day being non-reproducible
# underneath a gate that could only see the disagreement about one run in ten, and each
# time it showed up it looked like a fresh miscompile.
#
# What it was: `handle == zeroed` on an opaque LLVM handle lowered to `ctx_streq` -- a
# CONTENT compare -- with only two of the runtime's argument registers set, so the answer
# depended on leftover register contents. `register_struct_names` decides whether to create
# a struct's LLVM type with exactly that test, so a wrong answer left the type null and
# silently dropped the `sret` attribute from every function returning it: a different but
# entirely self-consistent ABI, which is why the compiler still worked and only the
# fixpoint noticed. Fixed in codegen_expr_binary_tail.elisa; test/differential/cases/
# opaque_handle_identity.elisa pins the lowering.
#
# This stage makes the same class of bug fail EVERY run instead of one in ten. It needs a
# stage1-BUILT compiler (the stage0-built seed never reproduced it) and an aggregate over
# the 1024-byte indirect-return threshold, which is the decision that flipped. Cheap: the
# program is a few KB, so forty runs cost a couple of seconds.
DET_SRC="$WORK/determinism.elisa"
{
    echo "struct Wide:"
    field=0
    while [ "$field" -lt 200 ]; do echo "    f$field: i64"; field=$((field + 1)); done
    printf '\n\ndef make_wide() -> Wide:\n    return Wide{'
    field=0; sep=""
    while [ "$field" -lt 200 ]; do printf '%sf%d: %d' "$sep" "$field" "$field"; sep=", "; field=$((field + 1)); done
    printf '}\n\n\ndef main() -> i64:\n    value: Wide = make_wide()\n    return value.f0\n'
} >"$DET_SRC"

det_runs="${SELF_HOST_DETERMINISM_RUNS:-40}"
det_first=""
det_run=1
while [ "$det_run" -le "$det_runs" ]; do
    { printf '%s\n' "$WORK/det.o"; cat "$DET_SRC"; } >"$WORK/det.request"
    "$WORK/elisac-stage1-gen3" <"$WORK/det.request" >"$WORK/det.log" 2>&1
    [ -s "$WORK/det.o" ] || fail "stage D: gen3 wrote no object on run $det_run (see $WORK/det.log)"
    det_sum="$(cksum <"$WORK/det.o" | awk '{print $1}')"
    if [ -z "$det_first" ]; then
        det_first="$det_sum"
        cp "$WORK/det.o" "$WORK/det.first.o"
    elif [ "$det_sum" != "$det_first" ]; then
        cp "$WORK/det.o" "$WORK/det.differing.o"
        echo "  run 1  -> $(wc -c <"$WORK/det.first.o" | tr -d ' ') bytes, cksum $det_first" >&2
        echo "  run $det_run -> $(wc -c <"$WORK/det.differing.o" | tr -d ' ') bytes, cksum $det_sum" >&2
        echo "  both kept in $WORK; compare per-symbol sizes (nm -n) before anything else" >&2
        fail "stage D: gen3 emitted a DIFFERENT object for the SAME input on run $det_run — the compiler is not reproducible"
    fi
    det_run=$((det_run + 1))
done
echo "self_host_gen3_smoke stage D OK: gen3 emitted the same object on all $det_runs runs."
exit 0
