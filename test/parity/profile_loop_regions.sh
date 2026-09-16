#!/usr/bin/env bash
# Profile two pinned compiler binaries against identical source/runtime inputs.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BEFORE="${1:?baseline compiler binary required}"
AFTER="${2:?candidate compiler binary required}"
OUT="${3:?output directory required}"
PROFILER="${ELISA_PROFILER:-$ROOT/../elisa-profiler/bin/elisa-profiler}"
mkdir -p "$OUT"
export ELISA_COMPILER_ROOT="$ROOT" ELISA_COMPILER_SCRIPT="$ROOT/scripts/elisac_stage1.sh"
# ELISA_ALLOW_STALE_STAGE1: this check compares a BEFORE and an AFTER binary, so one of
# them is older than the sources by construction. Not the blanket opt-out.
export ELISA_ALLOW_STALE_STAGE1=1
export ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
for fixture in explicit inferred helpers reduction output module; do
    for version in before after; do
        export ELISA_STAGE1_BIN="$BEFORE"
        [[ "$version" == before ]] || export ELISA_STAGE1_BIN="$AFTER"
        "$PROFILER" profile "$ROOT/test/bench/loop_region_$fixture.elisa" -O2 --mode full \
            --repeat 5 --warmup 1 --format json --output "$OUT/$fixture-$version.json"
    done
done
python3 - "$OUT" <<'PY'
import collections, json, pathlib, statistics, sys
root = pathlib.Path(sys.argv[1])
rows = []
for fixture in ('explicit', 'inferred', 'helpers', 'reduction', 'output', 'module'):
    for version in ('before', 'after'):
        p = json.loads((root / f'{fixture}-{version}.json').read_text())
        summary = p['summary']
        assert summary['capture_complete'] and not summary['detail_budget_exceeded']
        for key in ('dropped', 'allocation_events_dropped', 'frame_dropped', 'capture_bytes_dropped'):
            assert summary[key] == 0, (fixture, version, key, summary[key])
        counts, rss, cpu, wall = [], [], [], []
        for r in p['run']['repetitions']:
            assert r['exit_code'] == 0 and r['capture_complete'] and not r['timed_out']
            assert r['allocation_events_dropped'] == 0
            c = collections.Counter(e['kind'] for e in r['allocation_events'])
            assert c['alloc'] == (201 if fixture == 'output' else 200), c
            if version == 'after':
                assert c['region_create'] == (2 if fixture == 'output' else 1) and c['region_reset'] == 200, c
            counts.append(dict(c))
            rss.append(r['peak_rss_bytes']); cpu.append(r['cpu_ms']); wall.append(r['execution_ms'])
        assert all(c == counts[0] for c in counts)
        rows.append(dict(fixture=fixture, version=version, events_per_run=counts[0],
                         median_peak_rss_bytes=statistics.median(rss),
                         median_cpu_ms=statistics.median(cpu), median_wall_ms=statistics.median(wall)))
(root / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
print(json.dumps(rows, indent=2))
PY
