#!/usr/bin/env bash
# Runtime benchmark for GENERATED code: each program is built by stage1 -O2, stage0 -O2 and
# (as the floor) the equivalent C at clang -O2, exit codes are cross-checked, then each binary
# is timed (best of REPEAT runs, child CPU time) and, with CALLGRIND=1, counted (instructions, noise-free).
#   test/bench/codegen_perf/run.sh <outdir> [bench ...]
# Env: ELISACORE_BIN (stage0), REPEAT (default 7), SKIP_S0=1, SKIP_C=1, CALLGRIND=1,
#      S1_BIN (call this stage1 product directly instead of the wrapper, e.g. a gen2 candidate),
#      ELISA_RUNTIME_OBJ (runtime object to link stage1 products against).
set -uo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$HERE/../../.." && pwd)"
OUT="${1:?outdir}"; shift
mkdir -p "$OUT"; OUT="$(cd -- "$OUT" && pwd)"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
S0="${ELISACORE_BIN:-}"
REPEAT="${REPEAT:-7}"
benches=("$@"); [[ ${#benches[@]} -eq 0 ]] && benches=($(cd "$HERE" && ls *.elisa | sed 's/\.elisa$//'))
best() { python3 - "$REPEAT" "$@" <<'PY'
import resource, subprocess, sys
# CPU time (user+sys) of the child, best of n: far steadier than wall time on a shared box.
n=int(sys.argv[1]); cmd=sys.argv[2:]; t=[]
for _ in range(n):
    a=resource.getrusage(resource.RUSAGE_CHILDREN); r=subprocess.run(cmd)
    b=resource.getrusage(resource.RUSAGE_CHILDREN)
    t.append((b.ru_utime-a.ru_utime)+(b.ru_stime-a.ru_stime))
print(f"{min(t):.4f} rc={r.returncode}")
PY
}
irs() { valgrind --tool=callgrind --callgrind-out-file=/dev/null "$@" 2>&1 >/dev/null | awk '/Collected/{print $4}'; }
printf '%-14s %-8s %10s %6s %14s\n' bench variant cpu_s rc instr
for b in "${benches[@]}"; do
  src="$HERE/$b.elisa"
  if [[ -n "${S1_BIN:-}" ]]; then s1=("$S1_BIN" -emit obj); else s1=(bash "$ROOT/scripts/elisac_stage1.sh"); fi
  "${s1[@]}" -O2 -o "$OUT/$b.s1.o" "$src" >"$OUT/$b.s1.log" 2>&1 &&
    clang -Wl,-dead_strip -o "$OUT/$b.s1" "$OUT/$b.s1.o" "$RUNTIME" >>"$OUT/$b.s1.log" 2>&1 || echo "$b: stage1 build failed (see $OUT/$b.s1.log)"
  if [[ -z "${SKIP_S0:-}" && -n "$S0" ]]; then
    "$S0" -emit obj -O2 -o "$OUT/$b.s0.o" "$src" >"$OUT/$b.s0.log" 2>&1 &&
      clang -Wl,-dead_strip -o "$OUT/$b.s0" "$OUT/$b.s0.o" "$RUNTIME" >>"$OUT/$b.s0.log" 2>&1 || echo "$b: stage0 build failed"
    # (Always with the runtime object: on Linux the clang shim ignores unresolved symbols,
    # so a runtime-less link "succeeds" and the program calls address 0.)
  fi
  [[ -n "${SKIP_C:-}" ]] || clang -O2 -o "$OUT/$b.c" "$HERE/$b.c" 2>"$OUT/$b.c.log" || echo "$b: C build failed"
  for v in c s0 s1; do
    [[ -x "$OUT/$b.$v" ]] || continue
    r="$(best "$OUT/$b.$v")"; ir="-"
    [[ -n "${CALLGRIND:-}" ]] && ir="$(irs "$OUT/$b.$v")"
    printf '%-14s %-8s %10s %6s %14s\n' "$b" "$v" "${r% *}" "${r#* }" "$ir"
  done
done
