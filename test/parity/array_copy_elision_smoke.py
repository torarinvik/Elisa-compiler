#!/usr/bin/env python3
"""Array round-trip elision must match -O0 and remove copies. Set ELISAC to test another compiler."""
import os, re, subprocess, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parent
ELISAC = os.environ.get('ELISAC') or str(HERE.parents[1] / 'bin/elisac-stage1')
FIXTURE, CHECK = HERE / 'array_copy_elision_fixture.elisa', HERE / 'array_copy_elision_check.c'
def run(*args):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True, text=True, timeout=60).stdout
with tempfile.TemporaryDirectory(prefix='elisa-ace-') as tmp:
    work, out = Path(tmp), {}
    for level in ('-O0', '-O3'):
        obj, exe = work / f'{level}.o', work / f'{level}.exe'
        run(ELISAC, level, '-emit', 'obj', '-o', obj, FIXTURE)
        run('cc', CHECK, obj, '-o', exe)
        out[level] = run(exe)
    if out['-O0'] != out['-O3']: raise SystemExit('elided results differ from -O0')
    ir = work / 'o3.ll'
    run(ELISAC, '-O3', '-emit', 'llvm', '-o', ir, FIXTURE)
    text = ir.read_text()
    for name in ('t1', 't5'):
        body = re.search(r'define[^@\n]*@' + name + r'\(.*?\n}\n', text, re.S).group(0)
        if '@llvm.memcpy' in body: raise SystemExit(f'{name} kept a round-trip copy')
    for name in ('t3', 't4'):
        body = re.search(r'define[^@\n]*@' + name + r'\(.*?\n}\n', text, re.S).group(0)
        if '@llvm.memcpy' not in body: raise SystemExit(f'{name} lost a needed copy')
print('array copy elision: ok')
