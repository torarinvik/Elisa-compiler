#!/usr/bin/env python3
"""Check the bounded-sum proofs against their shapes, and run the proved sums.

`bounded-sums` drops the overflow checks of sums it proves cannot overflow. Each
case's count, and the checked adds, checked subtractions, `add nuw nsw`, `sub nsw`
and traps it leaves, are what the C++ pass did with the same shapes
(bounded_sum_cases.py). The pass is idempotent. The fixture's functions, before and
after the pass, are then linked into two libraries, and bounded_sum_harness.c runs
both over many inputs: every result and every trap must agree.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from bounded_sum_cases import CASES, EXPECTED, FIXTURE
from elisa_llvm_pass import run_pass

PASS = 'bounded-sums'
# The pass proves at most 32 functions a run, so a second run takes the 33rd.
BUDGETED = {'functions-33'}
CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config' if os.uname().sysname == 'Darwin' else '/usr/lib/llvm-23/bin/llvm-config')


def shape(count, module):
    checked_adds = len(re.findall(r'= call \{ i\d+, i1 \} @llvm\.sadd\.with\.overflow', module))
    checked_subtractions = len(re.findall(r'= call \{ i\d+, i1 \} @llvm\.ssub\.with\.overflow', module))
    proved_adds = len(re.findall(r'= add nuw nsw ', module))
    proved_subtractions = len(re.findall(r'= sub nsw ', module))
    traps = len(re.findall(r'call void @llvm\.trap\(\)', module))
    return count, checked_adds, checked_subtractions, proved_adds, proved_subtractions, traps


def without_header(module):
    return [line for line in module.splitlines() if not line.startswith(('; ModuleID', 'source_filename'))]


def run_linked(proved):
    """Link the fixture before and after the pass and run both through the harness."""
    bindir = Path(subprocess.run([CONFIG, '--bindir'], capture_output=True, text=True, check=True).stdout.strip())
    with tempfile.TemporaryDirectory(prefix='elisa-bounded-sums-') as temporary:
        work = Path(temporary)
        libraries = []
        for label, text in [('baseline', FIXTURE), ('candidate', proved)]:
            source = work / f'{label}.ll'
            source.write_text(text)
            library = work / f'{label}.so'
            subprocess.run([str(bindir / 'clang'), '-O3', '-shared', '-fPIC', str(source), '-o', str(library)], check=True, capture_output=True, timeout=60)
            libraries.append(str(library))
        harness = work / 'check'
        extra = ['-ldl'] if sys.platform.startswith('linux') else []
        subprocess.run([str(bindir / 'clang'), '-O2', str(HERE / 'bounded_sum_harness.c'), *extra, '-o', str(harness)], check=True, capture_output=True, timeout=60)
        result = subprocess.run([str(harness), *libraries], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        print(result.stdout.strip(), flush=True)


def main():
    for name, ir in CASES.items():
        count, module = run_pass(PASS, ir)
        assert shape(count, module) == EXPECTED[name], (name, shape(count, module), EXPECTED[name])
        again_count, again = run_pass(PASS, module)
        assert name in BUDGETED or again_count == 0 and without_header(again) == without_header(module), (name, 'not idempotent')
        print('PASS', name, flush=True)
    run_linked(run_pass(PASS, FIXTURE)[1])
    print('bounded sums: counts, shapes, idempotence and linked results passed')


if __name__ == '__main__':
    main()
