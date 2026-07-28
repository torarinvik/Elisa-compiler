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
#   OPEN     `ctx_aos_store_record` returns 0 inside Backend.disjoint_scan_expr — see
#            memory `self-host-fixpoint-gap.md` and the tracked task
#
# Every one of those needed real input to surface. This script provides it.
#
# Deliberately NOT named *_smoke.sh: the aggregate gate runner globs `*_smoke.sh`, and
# bootstrap closure is still open, so wiring this in would leave the gate permanently red
# and train everyone to ignore it. Run it directly, and RENAME it to
# self_host_gen3_smoke.sh the moment stage B reaches rc=0.
#
# Stage A is a hard regression guard on the three fixed blockers.
# Stage B is a ratchet on how far gen2 gets compiling the compiler itself.
set -uo pipefail
set +m   # a crashing gen2 is an EXPECTED outcome here; don't let job control narrate it
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
GEN2="$ROOT/build/self_host_gen2/elisac-stage1-gen2"
WORK="$ROOT/build/gen3_check"; rm -rf "$WORK"; mkdir -p "$WORK"

# The exit code stage B currently produces. 0 means the fixpoint CLOSED.
# Any other value is a CHANGE and must be investigated, not silently re-baselined.
BASELINE_GEN3_RC="${BASELINE_GEN3_RC:-139}"

fail() { echo "self_host_gen3_check FAIL: $1" >&2; exit 1; }

[ -x "$BIN" ] || { echo "self_host_gen3_check SKIP: no seed ($BIN); run scripts/elisac_stage1.sh --seed"; exit 0; }
# The seed is a CACHED artifact and nothing rebuilds it automatically — `self_host_gen2.sh`
# happily builds gen2 from a stale gen1, which silently tests old code (this bit during
# development: stage A read 0/4 purely because the seed predated the fixes). Same failure
# shape as the 8-day-old build/emit_obj_debug_ir binary that hid a broken driver from the
# gate. Refuse to report on a seed older than the sources it claims to represent.
if [ -n "$(find "$ROOT/src" -name '*.elisa' -newer "$BIN" -print -quit 2>/dev/null)" ]; then
    fail "seed $BIN is OLDER than src/*.elisa — rebuild it (scripts/elisac_stage1.sh --seed) or this check reports on stale code"
fi
bash "$ROOT/scripts/self_host_gen2.sh" >"$WORK/gen2.log" 2>&1 \
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
guard when_or_columns \
  'def f(a: i64, b: i64) -> i64:\n    return when a, b:\n        0, 0 -> 10\n        _, _ -> 20\n\ndef main() -> i64:\n    return f(0, 0)\n' \
  '05b3c03 — wildcard/or patterns in a when table'

[ "$a_pass" -eq "$a_total" ] || fail "stage A regression: $a_pass/$a_total (a previously FIXED self-host blocker is back)"
echo "self_host_gen3_check stage A OK: $a_pass/$a_total (fixed blockers still fixed)"

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

rc=0
{ ( { printf '%s\n' "$WORK/gen3.o"; cat "$WORK/flat.elisa"; } | "$GEN2" >"$WORK/gen3.log" 2>&1 ) || rc=$?; } 2>/dev/null

if [ "$rc" -eq 0 ]; then
    [ -s "$WORK/gen3.o" ] || fail "gen2 exited 0 but wrote no gen3 object"
    echo "self_host_gen3_check: BOOTSTRAP CLOSED — gen2 compiled the compiler into gen3 ($(wc -c <"$WORK/gen3.o") bytes)."
    echo "  Next: link gen3, diff it against gen2 (ideally byte-identical), rename this to *_smoke.sh, set BASELINE_GEN3_RC=0."
    exit 0
fi

[ "$rc" -eq "$BASELINE_GEN3_RC" ] \
  || fail "stage B exit $rc, baseline $BASELINE_GEN3_RC — the bootstrap failure CHANGED. Re-diagnose (lldb bt on the gen3 input); do not just re-baseline."
echo "self_host_gen3_check stage B: gen2 still cannot compile the compiler (exit $rc == known baseline)."
echo "  Open blocker: see memory self-host-fixpoint-gap.md. Stage A proves no regression."
exit 0
