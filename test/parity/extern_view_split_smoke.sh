#!/usr/bin/env bash
# `view[T]` parameters of a C-ABI extern cross as (ptr, len) in both compilers (docs/127
# §3.3): the declared LLVM signatures are byte-identical, an extern without an explicit C
# calling convention keeps %DynArrayView, and a program calling libc strnlen through a
# view runs with the same exit code from both compilers.
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
# `@bounds`: the legacy prototype's (ptr, len) order, runtime, and stage0-identical rejections.
source = root / 'test/differential/cases/extern_bounds.elisa'
codes = []
for stage, compiler in enumerate((stage0, stage1)):
    ll = work / f'bounds{stage}.ll'
    subprocess.run([compiler, '-emit', 'llvm', '-O0', '-o', str(ll), str(source)], check=True, timeout=60)
    assert 'declare i64 @strnlen(ptr, i64)' in ll.read_text(), (compiler, 'declaration')
    obj, exe = work / f'bounds{stage}.o', work / f'bounds{stage}'
    subprocess.run([compiler, '-emit', 'obj', '-O0', '-o', str(obj), str(source)], check=True, timeout=60)
    subprocess.run(['clang', '-Wl,-dead_strip', '-o', str(exe), str(obj), str(work/'hooks.o'), str(root/'build/runtime/elisacore_runtime.o')], check=True)
    codes.append(subprocess.run([str(exe)], timeout=90).returncode)
assert codes == [0, 0], codes
print('extern_bounds: declaration, runtime PASS', flush=True)
main = 'def main() -> i64:\n    t: mutable darray[u8] = []\n    t.push(0)\n    return 0\n'
rejected = {
    'bounds_nocc': '@bounds(p, n)\nextern f(p: u8&, n: usize) -> usize\n',
    'bounds_badptr': '@callconv(c)\n@bounds(p, n)\nextern f(p: usize, n: usize) -> usize\n',
    'bounds_badlen': '@callconv(c)\n@bounds(p, n)\nextern f(p: u8&, n: f32) -> usize\n',
    'bounds_mentions': '@callconv(c)\n@bounds(p, n)\nextern f(p: u8&, n: usize) -> usize requires n > 0\n',
    'bounds_odd': '@callconv(c)\n@bounds(p)\nextern f(p: u8&, n: usize) -> usize\n',
    'bounds_unknown': '@callconv(c)\n@bounds(p, m)\nextern f(p: u8&, n: usize) -> usize\n',
    'bounds_d6': '@callconv(c)\n@bounds(text, cap)\nextern strnlen(text: u8&, cap: usize) -> usize\n\ndef main() -> i64:\n    t: mutable darray[u8] = []\n    t.push(0)\n    return strnlen(t[0:1], 1).i64()\n',
}
for name, decls in rejected.items():
    src = work / (name + '.elisa'); src.write_text(decls + ('\n' + main if 'def main' not in decls else ''))
    results = [subprocess.run([c, '-emit', 'obj', '-o', str(work/'out.o'), str(src)], capture_output=True, timeout=60) for c in (stage0, stage1)]
    assert all(r.returncode != 0 for r in results), (name, [(r.returncode, r.stderr) for r in results])
    assert results[0].stderr == results[1].stderr, (name, results[0].stderr, results[1].stderr)
    print(f'{name}: stage0/stage1 byte-identical rejection PASS', flush=True)

# The C plan SPLITS a view argument into (pointer, length), so it holds only when the emitted
# value really is that aggregate. A packed enum's `tail` payload bound in a match is where the
# two compilers disagree about the bound value's shape: stage0 binds the view
# (`%items = alloca %DynArrayView`) and compiles a correct program; stage1 binds a bare `ptr`,
# and extracting field 0 from a non-aggregate built an LLVM instruction with a NULL type and
# then named it -- dereferencing null INSIDE LLVM and SEGFAULTING the compiler (rc 139). The
# same call without `@callconv(c)` only declined, so the C plan was the whole difference.
#
# What this pins is the invariant that survives the feature gap: NEITHER compiler may crash.
# stage0 accepts and answers 6 (1+2+3 summed on the C side); stage1 declines and names the
# function. That decline is a real gap -- stage1 has no packed tail-view binding, which also
# makes `items.len` decline -- not a rule stage1 is enforcing, so it is asserted as a decline
# and not as a rejection.
TAIL_VIEW = """packed enum Blob:
    Bytes(items: tail f32)

@callconv(c)
extern take_view(xs: view[f32]) -> i64

def through_c(node: Blob, store: Blob.Store[Local]) -> i64:
    in store:
        match node:
            Blob.Bytes(items: items):
                return take_view(items)

def main() -> i64:
    region scratch(1024)
    store: Blob.Store[Local] = Blob.Store(scratch)
    in store:
        node: Blob = new Blob.Bytes(items: [1.0, 2.0, 3.0])
        out: i64 = through_c(node, store)
        destroy scratch
        return out
"""
src = work / 'tail_view.elisa'; src.write_text(TAIL_VIEW)
sumf = work / 'sumf.c'
sumf.write_text('#include <stdint.h>\n'
                'int64_t take_view(const float *xs, int64_t n) {\n'
                '    int64_t total = 0;\n'
                '    for (int64_t i = 0; i < n; i++) total += (int64_t)xs[i];\n'
                '    return total;\n}\n')
subprocess.run(['clang', '-c', '-O0', '-o', str(work / 'sumf.o'), str(sumf)], check=True)
tail_results = [subprocess.run([c, '-emit', 'obj', '-O0', '-o', str(work / f'tail{stage}.o'), str(src)],
                               capture_output=True, timeout=60) for stage, c in enumerate((stage0, stage1))]
for stage, r in enumerate(tail_results):
    assert r.returncode not in (139, -11), (f'stage{stage} CRASHED on a packed tail view crossing to C', r.returncode)
assert tail_results[0].returncode == 0, ('stage0 must still compile the tail view', tail_results[0].stderr)
tail_exe = work / 'tail0'
subprocess.run(['clang', '-Wl,-dead_strip', '-o', str(tail_exe), str(work / 'tail0.o'), str(work / 'sumf.o'),
                str(work / 'hooks.o'), str(root / 'build/runtime/elisacore_runtime.o')], check=True)
assert subprocess.run([str(tail_exe)], timeout=90).returncode == 6, 'stage0 tail view must sum 1+2+3 through C'
assert tail_results[1].returncode != 0, 'stage1 gained packed tail-view binding; promote this to a parity check'
assert b'declined' in tail_results[1].stderr and b'through_c' in tail_results[1].stderr, tail_results[1].stderr
print('extern_view_tail: stage0 runtime 6, stage1 declines by name, neither crashes PASS', flush=True)
PY
