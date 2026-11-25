#!/usr/bin/env python3
"""Check the bounded-division-sum elision against its shapes, and run the proved loops.

Each case's count, the checked adds and subtractions it leaves, the `proved.digit.sum`
adds it makes, and a second run's count are what the C++ pass did with the same shapes
(digit_sum_cases.py). The proved loops, before and after the pass, must then agree on
every input of a wide sample, negative and extreme values included, and the exhaustive
fixture on every signed 8-bit input for each divisor from 2 to 20.
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
from digit_sum_cases import CASES, EXHAUSTIVE, EXPECTED, HERE, TRIPLE
from elisa_llvm_pass import run_pass

PASS = 'bounded-division-sums'
CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config' if os.uname().sysname == 'Darwin' else '/usr/lib/llvm-23/bin/llvm-config')
NATIVE = TRIPLE if os.uname().sysname == 'Darwin' else 'aarch64-unknown-linux-gnu'
CHECK = r'''#include <stdint.h>
#include <stdio.h>
extern TYPE digits(TYPE);
int main(void) {
    uint64_t state = 88172645463325252ULL, hash = 0;
    TYPE extremes[] = {0, 1, -1, (TYPE)(((uint64_t)1 << (sizeof(TYPE) * 8 - 1)) - 1), (TYPE)((uint64_t)1 << (sizeof(TYPE) * 8 - 1))};
    for (int index = 0; index < 5; ++index) hash = hash * 31 + (uint64_t)digits(extremes[index]);
    for (int round = 0; round < 200000; ++round) {
        state ^= state << 13; state ^= state >> 7; state ^= state << 17;
        hash = hash * 31 + (uint64_t)digits((TYPE)(state >> (state % 64)));
    }
    printf("%llu\n", (unsigned long long)hash);
    return 0;
}
'''
RUNTIME = [('digits', 'int64_t'), ('memory', 'int64_t'), ('nested', 'int64_t'), ('base-largest', 'int64_t'), ('i8-base-19', 'int8_t'), ('i32-base-10', 'int32_t')]


def shape(count, module):
    checked = len(re.findall(r'= call \{ i\d+, i1 \} @llvm\.s(add|sub)\.with\.overflow', module))
    return (count, checked, len(re.findall(r'%proved\.digit\.sum\d* = add ', module)))


def tool(name):
    bindir = subprocess.run([CONFIG, '--bindir'], capture_output=True, text=True, check=True).stdout.strip()
    return str(Path(bindir) / name)


def run(command):
    return subprocess.run([str(part) for part in command], capture_output=True, text=True, check=True, timeout=120)


def outputs(work, name, type_name):
    """The check's output linked with the case, before and after the pass."""
    fixture = CASES[name]
    count, module = run_pass(PASS, fixture)
    assert count != 0, name
    harness = work / f'{name}.c'
    harness.write_text(CHECK.replace('TYPE', type_name))
    results = []
    for label, text in [('base', fixture), ('candidate', module)]:
        source = work / f'{name}-{label}.ll'
        source.write_text(text.replace(TRIPLE, NATIVE))
        binary = work / f'{name}-{label}'
        run([tool('clang'), '-O1', '-Wno-override-module', source, harness, '-o', binary])
        results.append(run([binary]).stdout)
    return results


def exhaustive_outputs(work):
    """digit_sum_exhaustive.c's output linked with the exhaustive fixture, before and after
    the pass, at -O0 so the checks the pass keeps stay in the binary."""
    _, module = run_pass(PASS, EXHAUSTIVE)
    results = []
    for label, text in [('base', EXHAUSTIVE), ('candidate', module)]:
        source = work / f'exhaustive-{label}.ll'
        source.write_text(text)
        binary = work / f'exhaustive-{label}'
        run([tool('clang'), '-O0', '-Wno-override-module', HERE / 'digit_sum_exhaustive.c', source, '-o', binary])
        results.append(run([binary]).stdout)
    return results


def main():
    for name, ir in CASES.items():
        count, module = run_pass(PASS, ir)
        again, _ = run_pass(PASS, module)
        assert shape(count, module) + (again,) == EXPECTED[name], (name, shape(count, module) + (again,), EXPECTED[name])
        print('PASS', name, flush=True)
    if os.uname().machine in ('arm64', 'aarch64'):
        with tempfile.TemporaryDirectory(prefix='elisa-digit-sums-') as temporary:
            for name, type_name in RUNTIME:
                base, candidate = outputs(Path(temporary), name, type_name)
                assert base == candidate, (name, base, candidate)
                print('PASS runtime', name, candidate.strip(), flush=True)
            base, candidate = exhaustive_outputs(Path(temporary))
            values = candidate.split()
            assert base == candidate and len(values) == 4865 and values[-1] == '-999', (len(values), values[-1:])
            print('PASS runtime exhaustive', flush=True)
    print('bounded division sums: counts, shapes, second runs and runtime results passed')


if __name__ == '__main__':
    main()
