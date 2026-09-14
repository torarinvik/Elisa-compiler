#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$WORK/hooks.o"
for fixture in differential/cases/region_output_assignment parity/parser_scratch_lifetime; do
    for stage in 0 1; do
        executable="$WORK/${fixture##*/}-$stage"
        compiler="$STAGE0"
        [[ "$stage" == 0 ]] || compiler="$STAGE1"
        "$compiler" -emit obj -O2 -o "$WORK/result.o" "$ROOT/test/$fixture.elisa"
        if [[ "$stage" == 0 && "$fixture" == parity/parser_scratch_lifetime ]]; then
            clang -Wl,-dead_strip -o "$executable" "$WORK/result.o" "$WORK/hooks.o"
        else
            clang -Wl,-dead_strip -o "$executable" "$WORK/result.o" "$WORK/hooks.o" "$ROOT/build/runtime/elisacore_runtime.o"
        fi
        python3 - "$executable" "$WORK/output$stage" <<'PY'
import subprocess, sys
with open(sys.argv[2], 'wb') as out:
    subprocess.run([sys.argv[1]], stdout=out, timeout=90, check=True)
PY
    done
    cmp "$WORK/output0" "$WORK/output1"
    echo "$fixture: stage0/stage1 runtime PASS"
done
# Cached blocks can exceed the explicit request; emitted create/layout capacities
# must agree on the actual block, including when the same header is reused.
clang -c "$ROOT/test/parity/region_capacity_hooks.c" -o "$WORK/capacity-hooks.o"
"$STAGE1" -emit obj -O2 -o "$WORK/capacity.o" "$ROOT/test/parity/region_cached_capacity.elisa"
clang -Wl,-dead_strip -o "$WORK/capacity" "$WORK/capacity.o" "$WORK/capacity-hooks.o" "$WORK/hooks.o" "$ROOT/build/runtime/elisacore_runtime.o"
"$WORK/capacity"
echo 'cached region capacity events PASS'
"$STAGE1" -emit llvm -O0 -o "$WORK/parser.ll" "$ROOT/test/parity/parser_scratch_lifetime.elisa"
python3 - "$WORK/parser.ll" <<'PY'
from pathlib import Path
import sys
blocks=Path(sys.argv[1]).read_text().split('\ndefine ')
body=next(b for b in blocks if '@frontend_parse(' in b.split('\n')[0])
lex=next(line for line in body.splitlines() if 'call ' in line and '@frontend_tokenize(' in line)
parse=next(line for line in body.splitlines() if 'call ' in line and '@Parser.parse_file(' in line)
assert 'ptr %scratch)' in lex, lex
assert 'ptr %scratch' not in parse, parse
PY
echo 'parser token and AST allocation arenas PASS'
