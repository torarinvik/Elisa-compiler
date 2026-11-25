#!/usr/bin/env python3
"""Check the AArch64 signed range masks against their shapes.

Inside a loop, `x + ((x >> 31) & 2^32)` over a loaded x that a dominating check keeps in
the signed 32-bit range becomes `freeze(x) & 0xFFFFFFFF`: one freeze per load, placed
right after it, which every mask and the range check then read. The expected counts are
the ones the C++ pass reported for the same shapes (signed_range_mask_cases.py). On an
AArch64 host each rewritten Darwin module is also linked and run against the original.
"""
import ctypes
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass
from signed_range_mask_cases import CASES, MAC

PASS = 'signed-range-masks'


def check_shape(name, module, sums):
    """One frozen load read by every mask, and no sign shift or modulus mask left."""
    freezes = re.findall(r'%signed\.range\.value = freeze i64 %x', module)
    masks = re.findall(r'= and i64 %signed\.range\.value, 4294967295', module)
    assert len(freezes) == 1, (name, 'freezes', len(freezes))
    assert len(masks) == sums, (name, 'masks', len(masks), sums)
    assert 'lshr i64 %x' not in module and 'and i64 %high' not in module, (name, 'sign parts left')
    load = module.index('%x = load i64')
    assert load < module.index('%signed.range.value = freeze') < module.index('%biased = add i64 %signed.range.value'), (name, 'freeze placement')


def compile_shared(ir, library):
    config = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config' if os.uname().sysname == 'Darwin' else '/usr/lib/llvm-23/bin/llvm-config')
    bindir = Path(subprocess.run([config, '--bindir'], capture_output=True, text=True, check=True).stdout.strip())
    subprocess.run([bindir / 'clang', '-O2', '-shared', '-fPIC', ir, '-o', library], check=True, capture_output=True, timeout=60)
    function = ctypes.CDLL(str(library)).f
    function.argtypes = [ctypes.POINTER(ctypes.c_int64), ctypes.POINTER(ctypes.c_int64), ctypes.c_int64]
    function.restype = None
    return function


def check_execution(name, original, rewritten, directory, generator):
    """The original and rewritten functions store the same value for the same arrays."""
    functions = []
    for label, text in (('original', original), ('rewritten', rewritten)):
        source = directory / f'{name}-{label}.ll'
        source.write_text(text)
        functions.append(compile_shared(source, directory / f'{name}-{label}.so'))
    boundaries = [-(2 ** 31) - 1, -(2 ** 31), -(2 ** 31) + 1, -1001, -1000, -1, 0, 1, 999, 1000, 2 ** 31 - 1, 2 ** 31, 2 ** 63 - 1, -(2 ** 63)]
    for trial in range(3000):
        count = generator.randrange(1, 9)
        values = [generator.choice(boundaries) if trial % 3 == 0 else generator.randrange(-(2 ** 31), 2 ** 31) for _ in range(count)]
        stored = []
        for function in functions:
            data = (ctypes.c_int64 * count)(*values)
            result = ctypes.c_int64(0x5A5A)
            function(data, ctypes.byref(result), count)
            stored.append(result.value)
        assert stored[0] == stored[1], (name, values, stored)


def main():
    executes = os.uname().machine in ('arm64', 'aarch64') and os.uname().sysname == 'Darwin'
    generator = random.Random(20261124)
    with tempfile.TemporaryDirectory(prefix='elisa-signed-range-masks-') as temporary:
        directory = Path(temporary)
        for name, (ir, sums) in CASES.items():
            changes, module = run_pass(PASS, ir)
            assert changes == sums, (name, changes, sums)
            again, _ = run_pass(PASS, module)
            assert again == 0, (name, 'not idempotent', again)
            if sums:
                check_shape(name, module, sums)
                if executes and MAC in ir:
                    check_execution(name, ir, module, directory, generator)
            print('PASS', name, flush=True)
    print('signed range masks: counts, shapes and linked results passed')


if __name__ == '__main__':
    main()
