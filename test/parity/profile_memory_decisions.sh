#!/usr/bin/env bash
# Reproducible full captures. Run baseline and candidate with pinned binaries,
# serially, on a quiet host; capacity is not RSS or committed physical pages.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPILER="${1:?compiler binary required}"
OUT="${2:?output directory required}"
mkdir -p "$OUT"
OUT="$(cd -- "$OUT" && pwd)"
PROFILER="${ELISA_PROFILER:-$ROOT/../elisa-profiler/bin/elisa-profiler}"
export ELISA_COMPILER_ROOT="$ROOT" ELISA_COMPILER_SCRIPT="$ROOT/scripts/elisac_stage1.sh"
# ELISA_ALLOW_STALE_STAGE1: this check PROFILES a binary named on the command line, which
# is often deliberately an older build. It is not the blanket opt-out the env files used to
# carry -- every other check runs against the newest product.
export ELISA_STAGE1_BIN="$COMPILER" ELISA_ALLOW_STALE_STAGE1=1
export ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
for entry in lifecycle:repro/arena_lifetime_evidence; do
    name="${entry%%:*}"; fixture="${entry#*:}"
    "$PROFILER" profile "$ROOT/test/$fixture.elisa" -O2 --mode full --max-capture-bytes 268435456 \
        --repeat 5 --warmup 1 --format json --output "$OUT/$name.json"
    python3 "$ROOT/../elisa-profiler/scripts/analyze-allocation-sites.py" "$OUT/$name.json" --output "$OUT/$name-sites.json"
done
python3 - "$OUT" <<'PY'
import json,pathlib,sys
for name in ('lifecycle',):
    p=pathlib.Path(sys.argv[1])
    for r in json.loads((p/f'{name}.json').read_text())['run']['repetitions']:
        assert r['exit_code']==0 and r['capture_complete'] and not r['timed_out'], (name,r['exit_code'])
    for r in json.loads((p/f'{name}-sites.json').read_text())['repetitions']:
        assert r['lifetime_status']=='available', (name,r['lifetime_reason'])
        print(name,r['repetition'],r['metrics'])
PY
