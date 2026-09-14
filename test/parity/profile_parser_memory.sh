#!/usr/bin/env bash
# Profile the real parser on a source file, preserving its stdin and compiler identity.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPILER="${1:?compiler binary required}"
OUT="${2:?output directory required}"
INPUT="${3:-$ROOT/src/backend/codegen_locals.elisa}"
MODE="${4:-sample}"
mkdir -p "$OUT"
OUT="$(cd -- "$OUT" && pwd)"
PROFILER="${ELISA_PROFILER:-$ROOT/../elisa-profiler/bin/elisa-profiler}"
printf 'using Ast\ninclude "%s"\n' "$ROOT/test/breadth/parse_probe.elisa" > "$OUT/parser_workload.elisa"
export ELISA_COMPILER_ROOT="$ROOT" ELISA_COMPILER_SCRIPT="$ROOT/scripts/elisac_stage1.sh"
export ELISA_STAGE1_BIN="$COMPILER" ELISA_ALLOW_STALE_STAGE1=1
export ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
"$PROFILER" profile "$OUT/parser_workload.elisa" -O2 --stdin "$INPUT" --mode "$MODE" --max-capture-bytes 268435456 \
    --repeat 5 --warmup 1 --format json --output "$OUT/parser.json"
python3 - "$OUT/parser.json" <<'PY'
import json, statistics, sys
p = json.load(open(sys.argv[1]))
s = p['summary']
assert s['capture_complete'] and not s['detail_budget_exceeded']
for key in ('dropped', 'allocation_events_dropped', 'frame_dropped', 'capture_bytes_dropped'):
    assert s[key] == 0, (key, s[key])
rs = p['run']['repetitions']
for r in rs:
    assert r['exit_code'] == 0 and r['capture_complete'] and not r['timed_out']
print(json.dumps({k: statistics.median(r[k] for r in rs)
                  for k in ('peak_rss_bytes', 'cpu_ms', 'execution_ms')}, indent=2))
PY
