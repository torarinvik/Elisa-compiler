#!/usr/bin/env bash
# Same compiler, runtime, source and -O2 flags; one optimization at a time.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPILER="${1:?compiler binary required}"
OUT="${2:?output directory required}"
mkdir -p "$OUT"
OUT="$(cd -- "$OUT" && pwd)"
python3 - "$OUT" <<'PY'
from pathlib import Path
import sys
out=Path(sys.argv[1])
helper='''def work(input_count: i64) -> i64:
    temporary: mutable darray[i64] = []
    for position in 0..<input_count |temporary|:
        temporary.push(position + 1)
    subtotal: mutable i64 = 0
    for value in temporary |subtotal|:
        subtotal <- subtotal + value
    return subtotal
'''
stack='''def work(input_count: i64) -> i64:
    temporary: darray[i64] = [input_count, input_count + 1, input_count + 2, input_count + 3]
    return temporary[0] + temporary[1] + temporary[2] + temporary[3]
'''
for name,body,rounds,size in [('helper',helper,500000,64),('reserve',helper,200000,128),('stack',stack,2000000,64)]:
    source='extern printf(format: cstr, ...) -> i32\nextern memory_benchmark_consume(value: i64) -> i64\n'+body
    source+=f'''def main() -> i64:
    total: mutable i64 = 0
    for iteration in 0..<{rounds} |total|:
        measured: i64 = work({size} + iteration % 4)
        total <- total + memory_benchmark_consume(measured)
    _ = printf("%lld\\n", total) can Console
    return 0
'''
    (out/f'{name}.elisa').write_text(source)
PY
clang -O2 -c "$ROOT/test/parity/profile_hooks.c" -o "$OUT/hooks.o"
clang -O2 -c "$ROOT/test/parity/memory_speed_benchmark_hooks.c" -o "$OUT/benchmark-hooks.o"
for policy in helper reserve stack; do
    for variant in baseline candidate; do
        helper=1; reserve=1; stack=1
        if [[ "$variant" == candidate ]]; then
            case "$policy" in helper) helper=0;; reserve) reserve=0;; stack) stack=0;; esac
        fi
        ELISA_DISABLE_MEMORY_HELPER="$helper" ELISA_DISABLE_MEMORY_RESERVE="$reserve" ELISA_DISABLE_MEMORY_STACK="$stack" \
            "$COMPILER" -emit obj -O2 -o "$OUT/$policy-$variant.o" "$OUT/$policy.elisa"
        clang -Wl,-dead_strip -o "$OUT/$policy-$variant" "$OUT/$policy-$variant.o" "$OUT/hooks.o" "$OUT/benchmark-hooks.o" "$ROOT/build/runtime/elisacore_runtime.o"
    done
done
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
for policy in helper reserve stack; do
    "$STAGE0" -emit obj -O2 -o "$OUT/$policy-oracle.o" "$OUT/$policy.elisa"
    clang -Wl,-dead_strip -o "$OUT/$policy-oracle" "$OUT/$policy-oracle.o" "$OUT/hooks.o" "$OUT/benchmark-hooks.o" "$ROOT/build/runtime/elisacore_runtime.o"
    python3 - "$OUT" "$policy" <<'PY_ORACLE'
from pathlib import Path
import subprocess,sys
out,name=Path(sys.argv[1]),sys.argv[2]
results=[]
for variant in ('oracle','baseline','candidate'):
    run=subprocess.run([str(out/f'{name}-{variant}')],capture_output=True,timeout=120,check=True)
    results.append((run.stdout,run.stderr))
assert results[0]==results[1]==results[2],(name,results)
(out/f'{name}-oracle.txt').write_bytes(results[0][0])
PY_ORACLE
    python3 "$ROOT/../elisa-profiler/scripts/benchmark-native.py" \
        --baseline "$OUT/$policy-baseline" --candidate "$OUT/$policy-candidate" \
        --repeat "${ELISA_BENCH_REPEAT:-15}" --warmup 2 --timeout 120 --output "$OUT/$policy-timing.json"
done
