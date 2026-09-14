#!/usr/bin/env bash
# Record parser allocation evidence. To compare source changes, run once before
# and once after the edit with the same pinned compiler and input, then compare
# the emitted memory-sites.json files. Full-mode CPU/RSS includes observer cost.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPILER="${1:?compiler binary required}"
OUT="${2:?output directory required}"
INPUT="${3:-$ROOT/src/backend/codegen_locals.elisa}"
bash "$ROOT/test/parity/profile_parser_memory.sh" "$COMPILER" "$OUT" "$INPUT" full
python3 "$ROOT/../elisa-profiler/scripts/analyze-allocation-sites.py" "$OUT/parser.json" --output "$OUT/memory-sites.json"
python3 - "$OUT/memory-sites.json" <<'PY'
import json,sys
for repetition in json.load(open(sys.argv[1]))['repetitions']:
    assert repetition['lifetime_status']=='available', repetition['lifetime_reason']
    print(repetition['repetition'], repetition['metrics'])
PY
