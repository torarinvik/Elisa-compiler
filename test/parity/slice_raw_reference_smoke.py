#!/usr/bin/env python3
"""Slicing a raw scalar reference is rejected with stage0's message, and valid slices still build."""
import os, subprocess, tempfile
from pathlib import Path
ELISAC = os.environ.get('ELISAC') or str(Path(__file__).resolve().parents[2] / 'bin/elisac-stage1')
def build(src):
    with tempfile.TemporaryDirectory(prefix='elisa-slice-') as tmp:
        f = Path(tmp) / 'a.elisa'
        f.write_text(src)
        return subprocess.run([ELISAC, '-emit', 'obj', '-o', str(Path(tmp) / 'a.o'), str(f)], capture_output=True, text=True, timeout=60)
TAIL = 'def use(v: view[i64]) -> i64:\n    return v[0]\n\n'
for prefix, ref in (('', 'i64&'), ('mutable ', 'mutable i64&')):
    p = build(TAIL + f'def f(p: {prefix}i64&, n: usize) -> i64:\n    return use(p[0:n])\n')
    want = f'slicing requires string, array, view, or packed store type, got {ref}'
    if p.returncode == 0 or want not in p.stderr: raise SystemExit(f'raw slice not rejected: {p.stderr[-300:]}')
p = build(TAIL + 'def f(a: view[i64], n: usize) -> i64:\n    return use(a[0:n])\n\ndef g(a: darray[i64]&, n: usize) -> i64:\n    return use(a[0:n])\n')
if p.returncode: raise SystemExit(f'valid slice rejected: {p.stderr[-300:]}')
print('slice raw reference: ok')
