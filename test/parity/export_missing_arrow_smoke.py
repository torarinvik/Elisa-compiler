#!/usr/bin/env python3
"""`export fn f(...) T = impl` without an arrow is a parse error, not a void export."""
import os, subprocess, tempfile
from pathlib import Path
ELISAC = os.environ.get('ELISAC') or str(Path(__file__).resolve().parents[2] / 'bin/elisac-stage1')
def build(src):
    with tempfile.TemporaryDirectory(prefix='elisa-export-') as tmp:
        f = Path(tmp) / 'a.elisa'
        f.write_text(src)
        return subprocess.run([ELISAC, '-emit', 'obj', '-o', str(Path(tmp) / 'a.o'), str(f)], capture_output=True, text=True, timeout=60)
IMPL = 'def f(n: i64) -> i64:\n    return n\n\ndef v(n: i64) -> void:\n    pass\n\n'
p = build(IMPL + 'export fn g(n: i64) i64 = f\n')
if p.returncode == 0 or 'expected =, got' not in p.stderr: raise SystemExit(f'missing arrow accepted: {p.stderr[-300:]}')
for good in ('export fn g(n: i64) -> i64 = f\n', 'export fn g(n: i64) = v\n'):
    p = build(IMPL + good)
    if p.returncode: raise SystemExit(f'valid export rejected: {good} {p.stderr[-300:]}')
print('export missing arrow: ok')
