#!/usr/bin/env bash
# The extern POINTER discipline under -strict-externs (docs/127 §3.7, D1 and D12): both
# compilers must reject the same programs with BYTE-IDENTICAL stderr, accept the typed-handle
# and @trusted forms, and leave everything alone when the flag is off.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
python3 - "$STAGE0" "$STAGE1" "$WORK" <<'PY'
from pathlib import Path
import subprocess, sys
stage0, stage1, work = sys.argv[1:]
work = Path(work)
main = 'def main() -> i64:\n    return 0\n'
rejected = {
    'untyped_param': 'extern adsr_process(envelope: mutable void&?, level: f64) -> f64 requires level >= 0.0\n',
    'untyped_const_param': 'extern adsr_busy(envelope: void&) -> bool ensure true\n',
    'untyped_return': 'extern adsr_create(sustain: bool) -> mutable void&? ensure true\n',
    'covers_none': 'extern memcpy(dest: mutable u8&, src: u8&, n: usize) -> void requires n > 0\n',
    'covers_none_cstr': 'extern puts(text: cstr) -> i32 ensure result >= 0\n',
    'unbounded_pair': 'extern read(fd: i32, buf: mutable u8&, count: usize) -> isize requires buf != null\n',
    'unbounded_const_pair': 'extern sum(values: f32&, count: usize) -> f32 requires values != null\n',
}
accepted = {
    'opaque_handle': 'extern Adsr\nextern adsr_process(envelope: mutable Adsr&, level: f64) -> f64 requires level >= 0.0\n',
    'contract_names_pointer': 'extern strnlen(text: cstr, cap: usize) -> usize requires text != null ensure result <= cap\n',
    'trusted': '@trusted("SDL user-data slot: opaque by design")\nextern set_user(handle: mutable void&?) -> void\n',
    'view_param': 'extern take(xs: view[u8]) -> usize ensure result <= xs.count\n',
    'struct_ref_with_int': 'struct Rect layout(c):\n    w: i32\n\nextern area(r: Rect&, scale: i32) -> i32 requires r != null\n',
    'out_param_alone': 'extern get_len(out: mutable i64&) -> void requires out != null\n',
    'bounds_pair': '@callconv(c)\n@bounds(buf, count)\nextern read(fd: i32, buf: mutable u8&, count: usize) -> isize requires buf.count > 0\n',
}
def compile(compiler, source, strict):
    flags = ['-strict-externs'] if strict else []
    return subprocess.run([compiler, '-emit', 'obj', *flags, '-o', str(work/'out.o'), str(source)], capture_output=True, timeout=60)
for name, decls in rejected.items():
    source = work / (name + '.elisa'); source.write_text(decls + '\n' + main)
    results = [compile(c, source, True) for c in (stage0, stage1)]
    assert all(r.returncode != 0 for r in results), (name, [(r.returncode, r.stderr) for r in results])
    assert results[0].stderr == results[1].stderr, (name, results[0].stderr, results[1].stderr)
    assert b'untyped pointer' in results[0].stderr or b'not covered' in results[0].stderr or b'no bounds' in results[0].stderr, (name, results[0].stderr)
    off = [compile(c, source, False) for c in (stage0, stage1)]
    assert all(r.returncode == 0 for r in off), (name, 'must compile without -strict-externs', [(r.returncode, r.stderr) for r in off])
    print(f'{name}: stage0/stage1 byte-identical rejection PASS, accepted with flag off', flush=True)
for name, decls in accepted.items():
    source = work / (name + '.elisa'); source.write_text(decls + '\n' + main)
    results = [compile(c, source, True) for c in (stage0, stage1)]
    assert all(r.returncode == 0 for r in results), (name, [(r.returncode, r.stderr) for r in results])
    print(f'{name}: stage0/stage1 accepted under -strict-externs PASS', flush=True)
PY
