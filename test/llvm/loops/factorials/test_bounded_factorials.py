#!/usr/bin/env python3
"""Check the bounded-factorial proofs against their shapes, and run the proved loops.

Each case's count, the checked calls it leaves, the `nsw` instructions it makes, and what
a second run changes are what the C++ pass did with the same shapes
(bounded_factorial_cases.py). The factorial fixture, before and after the pass, must
then compute every factorial up to 20! and reject 21 and -1; the interval fixture, before
and after, must agree over many random sample vectors.
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
from bounded_factorial_cases import CASES, EXPECTED, FACTORIAL, INTERVAL, LINUX, MAC
from elisa_llvm_pass import run_pass

PASS = 'bounded-factorials'
CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config' if os.uname().sysname == 'Darwin' else '/usr/lib/llvm-23/bin/llvm-config')
NATIVE = MAC if os.uname().sysname == 'Darwin' else LINUX
FACTORIAL_CHECK = r'''#include <stdint.h>
#include <stdio.h>
extern int64_t fact(int64_t);
int main(void) {
    if (fact(21) != -1 || fact(-1) != -1 || fact(0) != 1 || fact(1) != 1) return 1;
    int64_t want = 1;
    for (int64_t n = 2; n <= 20; ++n) {
        want *= n;
        if (fact(n) != want) { printf("%lld\n", (long long)n); return 1; }
    }
    return 0;
}
'''
INTERVAL_CHECK = r'''#include <stdint.h>
#include <stdio.h>
extern int64_t interval(const int64_t *, int64_t);
int main(void) {
    int64_t samples[15];
    uint64_t state = 88172645463325252ULL, hash = 0;
    for (int round = 0; round < 20000; ++round) {
        int count = (state >> 7) % 16;
        for (int index = 0; index < 15; ++index) {
            state ^= state << 13; state ^= state >> 7; state ^= state << 17;
            samples[index] = (int64_t)(state % 10);
        }
        hash = hash * 31 + (uint64_t)interval(samples, count);
    }
    printf("%llu\n", (unsigned long long)hash);
    return 0;
}
'''


def shape(count, module):
    return (count, len(re.findall(r'call \{ i\d+, i1 \} @llvm\.s(add|sub|mul)\.with\.overflow', module)), len(re.findall(r' nsw ', module)))


def tool(name):
    bindir = subprocess.run([CONFIG, '--bindir'], capture_output=True, text=True, check=True).stdout.strip()
    return str(Path(bindir) / name)


def run(command):
    return subprocess.run([str(part) for part in command], capture_output=True, text=True, check=True, timeout=120)


def outputs(work, name, fixture, check):
    """The check's output linked with the fixture, before and after the pass."""
    _, module = run_pass(PASS, fixture)
    harness = work / f'{name}.c'
    harness.write_text(check)
    results = []
    for label, text in [('base', fixture), ('candidate', module)]:
        source = work / f'{name}-{label}.ll'
        source.write_text(text.replace(MAC, NATIVE))
        binary = work / f'{name}-{label}'
        run([tool('clang'), '-O1', '-Wno-override-module', source, harness, '-o', binary])
        results.append(run([binary]).stdout)
    return results


def main():
    for name, ir in CASES.items():
        count, module = run_pass(PASS, ir)
        again, _ = run_pass(PASS, module)
        assert shape(count, module) + (again,) == EXPECTED[name], (name, shape(count, module) + (again,), EXPECTED[name])
        print('PASS', name, flush=True)
    if os.uname().machine in ('arm64', 'aarch64'):
        with tempfile.TemporaryDirectory(prefix='elisa-bounded-factorials-') as temporary:
            work = Path(temporary)
            outputs(work, 'factorial', FACTORIAL, FACTORIAL_CHECK)
            print('PASS runtime factorial', flush=True)
            base, candidate = outputs(work, 'interval', INTERVAL, INTERVAL_CHECK)
            assert base == candidate, (base, candidate)
            print('PASS runtime interval', candidate.strip(), flush=True)
    print('bounded factorials: counts, shapes, second runs and runtime results passed')


if __name__ == '__main__':
    main()
