#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
# Compile ordinary executables, then time paired runs without trace hooks.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPILER="${1:?compiler binary required}"
OUT="${2:?output directory required}"
mkdir -p "$OUT"
OUT="$(cd -P -- "$OUT" && pwd)"
if [[ -n "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "output directory is not empty: $OUT (choose a fresh directory)" >&2
    exit 2
fi
source "$ROOT/scripts/benchmark_host_lock.sh"
elisa_benchmark_lock_acquire "$OUT"
trap elisa_benchmark_finish EXIT
elisa_benchmark_host_qualification "$ROOT" "$OUT"
elisa_benchmark_load_check "before compiler and workload builds" 1
python3 - "$ROOT" "$OUT" <<'PY'
from pathlib import Path
import sys
root,out=map(Path,sys.argv[1:])
s=(root/'test/breadth/parse_probe.elisa').read_text().split('def main()')[0]
s='using Ast\n'+s.replace('../../src/parser/parser.elisa',str(root/'src/parser/parser.elisa'))
s+='''
def parse_shared(source: u8&) -> Ast::File:
    tokens: darray[Token] = frontend_tokenize(source, source)
    return frontend_parser_parse_file(source, tokens)
def run_batch(source: u8&) -> i64:
    files: mutable darray[Ast::File] = []
    for i in 0..<10 |files|:
        files.push(PARSE_ENTRY(source))
    for file in files:
        return 1 if file.errors.count != 0 or file.top_decls.count != 1
    return 0
def main() -> i64 can[Console, Memory.Allocate, Memory.Release, Abort.Panic, Unsafe.PointerCast]:
    source: darray[u8] = read_all()
    for round in 0..<20:
        return 2 if run_batch(&source[0]) != 0
    return 0
'''
for name,entry in [('baseline','parse_shared'),('candidate','frontend_parse')]:
    (out/f'parser-{name}.elisa').write_text(s.replace('PARSE_ENTRY',entry))
PY
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$OUT/hooks.o"
for variant in baseline candidate; do
    "$COMPILER" -emit obj -O2 -o "$OUT/parser-$variant.o" "$OUT/parser-$variant.elisa"
    clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$OUT/parser-$variant" "$OUT/parser-$variant.o" "$OUT/hooks.o" "$ROOT/build/runtime/elisacore_runtime.o"
done
elisa_benchmark_load_check "after compiler and workload builds"
elisa_benchmark_load_check "before parser runtime samples"
python3 "$ROOT/../elisa-profiler/scripts/benchmark-native.py" \
    --baseline "$OUT/parser-baseline" --candidate "$OUT/parser-candidate" \
    --stdin "$ROOT/src/backend/codegen_locals.elisa" --repeat 15 --warmup 2 --timeout 120 --output "$OUT/parser-timing.json"
elisa_benchmark_load_check "after parser runtime samples"
date -u '+completed_at_utc=%Y-%m-%dT%H:%M:%SZ' >"$OUT/AUXILIARY_COMPLETE"
