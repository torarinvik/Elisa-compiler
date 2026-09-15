#!/usr/bin/env bash
# `extern resource` (docs/127 §3.2) in both compilers: the fopen/fclose fixture runs with exit
# 0 from each, the boundary declarations are byte-identical, and D2/D3 reject identically.
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
source = root / 'test/differential/cases/extern_resource.elisa'
declares, codes = [], []
for stage, compiler in enumerate((stage0, stage1)):
    ll = work / f'res{stage}.ll'
    subprocess.run([compiler, '-emit', 'llvm', '-O0', '-o', str(ll), str(source)], check=True, timeout=60)
    declares.append(sorted(re.findall(r'^declare [^\n]*@(?:fopen|fclose|fgetc)\([^\n]*', ll.read_text(), re.M)))
    obj, exe = work / f'res{stage}.o', work / f'res{stage}'
    subprocess.run([compiler, '-emit', 'obj', '-O0', '-o', str(obj), str(source)], check=True, timeout=60)
    subprocess.run(['clang', '-Wl,-dead_strip', '-o', str(exe), str(obj), str(work/'hooks.o'), str(root/'build/runtime/elisacore_runtime.o')], check=True)
    codes.append(subprocess.run([str(exe)], timeout=90).returncode)
assert declares[0] == declares[1], declares
assert 'declare ptr @fopen(ptr, ptr)' in declares[0], declares[0]
assert codes == [0, 0], codes
print('extern_resource: declarations byte-identical, runtime PASS', flush=True)
rejected = {
    'resource_nodrop': 'extern resource NoDrop\n\ndef main() -> i64:\n    return 0\n',
    'resource_borrowed_return': 'extern resource Borrowed\ndef __drop__(self: Borrowed) -> void:\n    pass\n\n@callconv(c)\nextern peek() -> Borrowed&\n\ndef main() -> i64:\n    return 0\n',
}
for name, text in rejected.items():
    src = work / (name + '.elisa'); src.write_text(text)
    results = [subprocess.run([c, '-emit', 'obj', '-o', str(work/'out.o'), str(src)], capture_output=True, timeout=60) for c in (stage0, stage1)]
    assert all(r.returncode != 0 for r in results), (name, [(r.returncode, r.stderr) for r in results])
    assert results[0].stderr == results[1].stderr, (name, results[0].stderr, results[1].stderr)
    print(f'{name}: stage0/stage1 byte-identical rejection PASS', flush=True)
PY
