#!/usr/bin/env bash
# `extern resource` (docs/127 §3.2) in both compilers: the fopen/fclose fixture runs with exit
# 0 from each, the boundary declarations are byte-identical, and D2/D3 reject identically.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0" || exit $?
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
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

# docs/127 D4 — no use after native release. The handle is consumed by fclose and then read.
# stage1 used to ACCEPT this. Two causes, both fixed: its `extern resource` desugar left the
# struct affinity "" (unrestricted), so the resource never reached struct_affine_owner; and its
# affine walker reported on a Field/Index object's root without ever DESCENDING into it, so the
# `move` inside `fgetc(file).i64()` was never recorded as a consumption at all.
#
# BOTH compilers now reject it. They do not yet agree on the sentence or the span:
#   stage0  …:18:18-22: linear value "file" cannot be used: usage facts were consumed by
#                       argument to call "fclose"
#   stage1  …:18:       linear handle value "file" cannot be used after ownership was consumed
# Closing the sentence needs the consuming call's name threaded into stage1's diagnostic (its
# renderer already has the shape, for the `match over affine enum` case); closing the span needs
# Ast::Pos threaded through the affine walker, which still reports line-only here. Until then
# this asserts rejection only — deliberately, and not by loosening any existing assertion.
D4_USE_AFTER_RELEASE = '''extern resource CFile

def __drop__(self: CFile) -> void:
    _ = fclose(move self)

@callconv(c)
extern fopen(path: cstr, mode: cstr) -> CFile?

@callconv(c)
extern fclose(file: CFile) -> i32

@callconv(c)
extern fgetc(file: CFile&) -> i32

def read_after_close(path: cstr) -> i64:
    file: CFile = get fopen(path, "r") else return -1
    _ = fclose(move file)
    return fgetc(file).i64()

def main() -> i64:
    return read_after_close("/etc/hosts")
'''
src = work / 'use_after_release.elisa'; src.write_text(D4_USE_AFTER_RELEASE)
d4_results = [subprocess.run([c, '-emit', 'obj', '-o', str(work/'d4.o'), str(src)], capture_output=True, timeout=60) for c in (stage0, stage1)]
assert all(r.returncode != 0 for r in d4_results), ('D4 use-after-release must be REJECTED by both',
                                                    [(r.returncode, r.stderr) for r in d4_results])
for stage, r in enumerate(d4_results):
    assert b'cannot be used' in r.stderr, (f'stage{stage} rejected for the wrong reason', r.stderr)
print('resource_use_after_release: rejected by both (wording/span gap noted above) PASS', flush=True)
PY
