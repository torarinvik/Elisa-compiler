#!/usr/bin/env bash
# `view[T]` parameters of a C-ABI extern cross as (ptr, len) in both compilers (docs/127
# §3.3): the declared LLVM signatures are byte-identical, an extern without an explicit C
# calling convention keeps %DynArrayView, and a program calling libc strnlen through a
# view runs with the same exit code from both compilers.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$WORK/hooks.o"
ROOT="$ROOT" python3 - "$STAGE0" "$STAGE1" "$WORK" <<'PY'
from pathlib import Path
import os, re, subprocess, sys
stage0, stage1, work = sys.argv[1:]
work = Path(work); root = Path(os.environ['ROOT'])
source = root / 'test/differential/cases/extern_view_split.elisa'
declares = []
for stage, compiler in enumerate((stage0, stage1)):
    ll = work / f'split{stage}.ll'
    subprocess.run([compiler, '-emit', 'llvm', '-O0', '-o', str(ll), str(source)], check=True, timeout=60)
    text = ll.read_text()
    found = sorted(re.findall(r'^declare [^\n]*@(?:strnlen|scale_samples|take_elisa)\([^\n]*', text, re.M))
    declares.append(found)
    print(f'stage{stage}:', ' | '.join(found), flush=True)
assert declares[0] == declares[1], declares
assert any('@strnlen(ptr, i64)' in d for d in declares[0]), declares[0]
assert any('@scale_samples(ptr, i64, float)' in d for d in declares[0]), declares[0]
assert any('@take_elisa(%DynArrayView)' in d for d in declares[0]), declares[0]
codes = []
for stage, compiler in enumerate((stage0, stage1)):
    obj, exe = work / f'split{stage}.o', work / f'split{stage}'
    subprocess.run([compiler, '-emit', 'obj', '-O0', '-o', str(obj), str(source)], check=True, timeout=60)
    subprocess.run(['clang', '-Wl,-dead_strip', '-o', str(exe), str(obj), str(work/'hooks.o'), str(root/'build/runtime/elisacore_runtime.o')], check=True)
    codes.append(subprocess.run([str(exe)], timeout=90).returncode)
assert codes == [0, 0], codes
print('extern_view_split: declarations byte-identical, runtime PASS', flush=True)
PY
