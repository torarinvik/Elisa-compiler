#!/usr/bin/env bash
# Hold ten parsed ASTs while discarding each lexer's temporary state and tokens.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPILER="${1:?compiler binary required}"
OUT="${2:?output directory required}"
INPUT="${3:-$ROOT/src/backend/codegen_locals.elisa}"
mkdir -p "$OUT"
OUT="$(cd -- "$OUT" && pwd)"
python3 - "$ROOT" "$OUT" <<'PY'
from pathlib import Path
import sys
root, out = map(Path, sys.argv[1:])
s=(root/'test/breadth/parse_probe.elisa').read_text().split('def main()')[0]
s='using Ast\n'+s.replace('../../src/parser/parser.elisa', str(root/'src/parser/parser.elisa'))
s+='''
def parse_shared(source: u8&) -> Ast::File:
    tokens: darray[Token] = frontend_tokenize(source, source)
    return frontend_parser_parse_file(source, tokens)
def main() -> i64 can[Console, Memory.Allocate, Memory.Release, Abort.Panic, Unsafe.PointerCast]:
    source: darray[u8] = read_all()
    files: mutable darray[Ast::File] = []
    for i in 0..<10 |files|:
        files.push(PARSE_ENTRY(&source[0]))
    count: usize = files[0].top_decls.count
    return 1 if count == 0
    for file in files:
        return 2 if file.errors.count != 0 or file.top_decls.count != count
    _ = printf("files=%lld decls=%lld\\n", files.count.i64(), count.i64()) can Console
    return 0
'''
for name,entry in [('shared','parse_shared'),('scratch','frontend_parse')]:
    (out/f'{name}.elisa').write_text(s.replace('PARSE_ENTRY',entry))
PY
export ELISA_COMPILER_ROOT="$ROOT" ELISA_COMPILER_SCRIPT="$ROOT/scripts/elisac_stage1.sh"
export ELISA_STAGE1_BIN="$COMPILER" ELISA_ALLOW_STALE_STAGE1=1
export ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
PROFILER="${ELISA_PROFILER:-$ROOT/../elisa-profiler/bin/elisa-profiler}"
for name in shared scratch; do
    "$PROFILER" profile "$OUT/$name.elisa" -O2 --stdin "$INPUT" --mode full --max-capture-bytes 268435456 \
        --repeat 5 --warmup 1 --format json --output "$OUT/$name.json"
    python3 "$ROOT/../elisa-profiler/scripts/analyze-allocation-sites.py" "$OUT/$name.json" --output "$OUT/$name-sites.json"
done
python3 - "$OUT" <<'PY'
import json,pathlib,sys
p=pathlib.Path(sys.argv[1])
for name in ('shared','scratch'):
    for r in json.loads((p/f'{name}.json').read_text())['run']['repetitions']:
        assert r['exit_code']==0 and r['capture_complete'] and not r['timed_out'], (name,r['exit_code'])
    for r in json.loads((p/f'{name}-sites.json').read_text())['repetitions']:
        assert r['lifetime_status']=='available', (name,r['lifetime_reason'])
        print(name,r['repetition'],r['metrics'])
PY
