#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPILER="${1:?compiler binary required}"
OUT="${2:?output directory required}"
mkdir -p "$OUT"
OUT="$(cd -- "$OUT" && pwd)"
PROFILER="${ELISA_PROFILER:-$ROOT/../elisa-profiler/bin/elisa-profiler}"
export ELISA_COMPILER_ROOT="$ROOT" ELISA_COMPILER_SCRIPT="$ROOT/scripts/elisac_stage1.sh"
export ELISA_STAGE1_BIN="$COMPILER" ELISA_ALLOW_STALE_STAGE1=1
export ELISA_RUNTIME_OBJ="$ROOT/build/runtime/elisacore_runtime.o"
for entry in helper:memory_speed_helper_reuse reserve:memory_speed_capacity stack:memory_speed_stack; do
    policy="${entry%%:*}"
    fixture="${entry#*:}"
    for variant in baseline candidate; do
        export ELISA_DISABLE_MEMORY_HELPER=1 ELISA_DISABLE_MEMORY_RESERVE=1 ELISA_DISABLE_MEMORY_STACK=1
        if [[ "$variant" == candidate ]]; then
            case "$policy" in
                helper) export ELISA_DISABLE_MEMORY_HELPER=0;;
                reserve) export ELISA_DISABLE_MEMORY_RESERVE=0;;
                stack) export ELISA_DISABLE_MEMORY_STACK=0;;
            esac
        fi
        "$PROFILER" profile "$ROOT/test/differential/cases/$fixture.elisa" -O2 --mode full \
            --max-capture-bytes 268435456 --repeat 3 --warmup 1 --format json --output "$OUT/$policy-$variant.json"
        python3 "$ROOT/../elisa-profiler/scripts/analyze-allocation-sites.py" "$OUT/$policy-$variant.json" --output "$OUT/$policy-$variant-sites.json"
    done
done
python3 - "$OUT" <<'PY'
import json,pathlib,sys
out=pathlib.Path(sys.argv[1])
for p in sorted(out.glob('*-sites.json')):
    capture=json.loads(p.with_name(p.name.replace('-sites','')).read_text())
    for r in capture['run']['repetitions']:
        assert r['exit_code']==0 and r['capture_complete'] and not r['timed_out'], (p,r['exit_code'])
    for r in json.loads(p.read_text())['repetitions']:
        # A fully stack-eliminated program may have no allocation events.
        assert r['lifetime_status']=='available', (p,r['lifetime_reason'])
        print(p.name,r['repetition'],r['metrics'])
PY
