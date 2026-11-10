#!/usr/bin/env python3
"""Slicing a raw scalar reference is rejected with stage0's message, and valid slices still build."""
import os, subprocess, tempfile
from pathlib import Path
ELISAC = os.environ.get('ELISAC') or str(Path(__file__).resolve().parents[2] / 'bin/elisac-stage1')
def build(src):
    with tempfile.TemporaryDirectory(prefix='elisa-slice-') as tmp:
        f = Path(tmp) / 'a.elisa'
        f.write_text(src)
        return subprocess.run([ELISAC, '-emit', 'obj', '-o', str(Path(tmp) / 'a.o'), str(f)], capture_output=True, text=True, timeout=30)
TAIL = 'def use(v: view[i64]) -> i64:\n    return v[0]\n\n'
for prefix, ref in (('', 'i64&'), ('mutable ', 'mutable i64&')):
    p = build(TAIL + f'def f(p: {prefix}i64&, n: usize) -> i64:\n    return use(p[0:n])\n')
    want = f'slicing requires string, array, view, or packed store type, got {ref}'
    if p.returncode == 0 or want not in p.stderr: raise SystemExit(f'raw slice not rejected: {p.stderr[-300:]}')
p = build(TAIL + 'def f(a: view[i64], n: usize) -> i64:\n    return use(a[0:n])\n\ndef g(a: darray[i64]&, n: usize) -> i64:\n    return use(a[0:n])\n')
if p.returncode: raise SystemExit(f'valid slice rejected: {p.stderr[-300:]}')
raw_byte_error = "slicing an unbounded raw `u8&` into `sview` requires an explicit"
for src in (
    'def f(p: u8&, n: usize) -> sview:\n    return p[0:n]\n',
    'def f(p: mutable u8&, n: usize) -> sview:\n    return p[0:n]\n',
    'def f(p: u8&, n: usize) -> sview can[Unsafe.PointerCast]:\n    return p[0:n]\n',
    'def f(p: u8&, n: usize) -> sview:\n    trusted Unsafe.PointerCast:\n        granted: sview = p[0:n]\n    return p[0:n]\n',
    'def f(p: u8&, q: u8&, n: usize) -> sview can[Unsafe.PointerCast]:\n    granted: sview = p[0:n] can Unsafe.PointerCast\n    return q[0:n]\n',
):
    p = build(src)
    if p.returncode == 0 or raw_byte_error not in p.stderr:
        raise SystemExit(f'ungranted byte slice not rejected: {p.stderr[-500:]}')
for src in (
    'def f(p: u8&, n: usize) -> sview can[Unsafe.PointerCast]:\n    return p[0:n] can Unsafe.PointerCast\n',
    'def f(p: u8&, n: usize) -> sview:\n    trusted Unsafe.PointerCast:\n        return p[0:n]\n',
    'def f(p: view[i64], n: usize) -> view[i64]:\n    return p[0:n]\n',
):
    p = build(src)
    if p.returncode:
        raise SystemExit(f'valid or granted slice rejected: {p.stderr[-500:]}')
print('slice raw reference: ok')
