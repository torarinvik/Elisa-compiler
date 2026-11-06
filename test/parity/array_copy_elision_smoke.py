#!/usr/bin/env python3
"""Array round-trip elision must match -O0 and remove copies. Set ELISAC to test another compiler."""
import os, subprocess, tempfile
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
    copies = sum('call void @llvm.memcpy' in line for line in ir.read_text().splitlines())
    # rebind and scratch_kept elide; reads_original, early_out and conditional_back keep theirs.
    if copies != 4: raise SystemExit(f'expected 4 surviving memcpy calls, found {copies}')
print('array copy elision: ok')
