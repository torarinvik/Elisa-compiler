#!/usr/bin/env bash
# Exercise a real split-add rewrite and its O0/debug and cache boundaries.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
source "$ROOT/scripts/platform.sh"
T=$(mktemp -d "${TMPDIR:-/tmp}/stage1-split-half.XXXXXX")
trap 'rm -rf "$T"' EXIT
SRC="$ROOT/test/parity/stage1_split_half_smoke.elisa"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
TIMEOUT=$(command -v gtimeout || command -v timeout)
run() { "$TIMEOUT" -k 1s 29s "$@"; }
export ELISA_RUNTIME_OBJ=none
run "$STAGE1" -O0 -emit llvm -o "$T/o0.ll" "$SRC"
run "$STAGE1" -O3 -emit llvm -o "$T/o3.ll" "$SRC"
run "$STAGE1" -O3 -g -emit llvm -o "$T/debug.ll" "$SRC"
python3 - "$T" "$LLVM_CONFIG" "$ELISA_HOST_OS" <<'PY'
import pathlib, re, subprocess, sys
p = pathlib.Path(sys.argv[1]); major = int(subprocess.check_output([sys.argv[2], '--version'], text=True).split('.')[0])
def body(file, name):
    text = (p/file).read_text()
    m = re.search(r'define\s+[^\n]*@' + name + r'\([^\n]*\).*?\n\}', text, re.S)
    if not m: raise SystemExit(f'{file}: missing {name}')
    return m.group(0)
o0 = body('o0.ll','split_add'); debug = body('debug.ll','split_add'); opt = body('o3.ll','split_add'); near = body('o3.ll','split_near')
assert 'and i64' in o0 and 'lshr i64' in o0 and 'split.native' not in o0
assert 'split.native' not in debug and '!dbg' in debug
assert 'split.native' not in near
if major == 23 and sys.argv[3] == "Darwin": assert 'split.native' in opt
elif major != 23 or sys.argv[3] != "Linux": assert 'split.native' not in opt
PY
run env ELISA_STAGE1_CACHE=1 ELISA_STAGE1_CACHE_DIR="$T/cache" "$STAGE1" -O3 -o "$T/first.o" "$SRC" >"$T/first.out" 2>"$T/first.err"
run env ELISA_STAGE1_CACHE=1 ELISA_STAGE1_CACHE_DIR="$T/cache" "$STAGE1" -O3 -o "$T/second.o" "$SRC" >"$T/second.out" 2>"$T/second.err"
cmp "$T/first.o" "$T/second.o"
cmp "$T/first.out" "$T/second.out"
cmp "$T/first.err" "$T/second.err"
find "$T/cache" -name '*.o.json' -print | grep -q .
cat >"$T/check.c" <<'C'
#include <stdint.h>
#include <stdio.h>
extern uint64_t split_add(uint64_t, uint64_t);
int main(void) {
  uint64_t x=0x4d595df4d0f33173ULL;
  uint64_t e[]={0,1,UINT64_MAX,0xffffffffULL,0x100000000ULL,0x7fffffffffffffffULL,0x8000000000000000ULL};
  for (unsigned i=0;i<7;i++) for(unsigned j=0;j<7;j++) if(split_add(e[i],e[j]) != e[i]+e[j]) return 1;
  for (unsigned i=0;i<100000;i++) { x^=x<<13; x^=x>>7; x^=x<<17; uint64_t a=x; x^=x<<13; x^=x>>7; x^=x<<17; uint64_t b=x; if(split_add(a,b)!=a+b) return 2; }
  return 0;
}
C
run "${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}" "$T/check.c" "$T/second.o" -o "$T/check"
run "$T/check"
echo 'stage1 split-half smoke passed'
