#!/usr/bin/env bash
# Uninstrumented control for profiler observer overhead. Run on an otherwise idle host.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BEFORE="${1:?baseline compiler required}"
AFTER="${2:?candidate compiler required}"
OUT="${3:?output directory required}"
mkdir -p "$OUT"
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$OUT/hooks.o"
for version in before after; do
    compiler="$BEFORE"
    [[ "$version" == before ]] || compiler="$AFTER"
    "$compiler" -emit obj -O2 -o "$OUT/$version.o" "$ROOT/test/bench/loop_region_timing.elisa"
    clang -Wl,-dead_strip -o "$OUT/$version" "$OUT/$version.o" "$OUT/hooks.o" \
        "${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
done
python3 - "$OUT" <<'PY'
import json, pathlib, resource, statistics, subprocess, sys, time
root = pathlib.Path(sys.argv[1]).resolve()
samples = {v: [] for v in ('before', 'after')}
for version in samples:
    subprocess.run([str(root / version)], check=True, timeout=60)
for repetition in range(7):
    for version in (('before', 'after') if repetition % 2 == 0 else ('after', 'before')):
        old = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.perf_counter()
        subprocess.run([str(root / version)], check=True, timeout=60)
        wall = (time.perf_counter() - start) * 1000
        new = resource.getrusage(resource.RUSAGE_CHILDREN)
        samples[version].append(dict(wall_ms=wall, cpu_ms=1000 *
            (new.ru_utime + new.ru_stime - old.ru_utime - old.ru_stime)))
result = dict(samples=samples, medians={v: {metric: statistics.median(r[metric] for r in rows)
    for metric in ('wall_ms', 'cpu_ms')} for v, rows in samples.items()})
(root / 'uninstrumented.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result['medians'], indent=2))
PY
