#!/usr/bin/env python3
"""Check the validation-loop passes against their shapes, and run the rewritten code.

Each case's change count, a second run's count, and the loads, stores, selects, freezes,
terminators and calls the module is left with are what the C++ passes did with the same
shapes (validation_loop_cases.py). Each pass's main fixtures, before and after it, must
then agree over many random inputs.
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
from validation_loop_cases import BITS, BITS_SWITCH, BOUNDED, CASES, CHECKED, EXPECTED, INIT, LINUX, MAC, NEST, RECURSION, SCAN, TINY
from elisa_llvm_pass import run_pass

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config' if os.uname().sysname == 'Darwin' else '/usr/lib/llvm-23/bin/llvm-config')
NATIVE = MAC if os.uname().sysname == 'Darwin' else LINUX
RANDOM = r'''#include <stdint.h>
#include <stdio.h>
static uint64_t state = 88172645463325252ULL;
static uint64_t next_random(void) {
    state ^= state << 13; state ^= state >> 7; state ^= state << 17;
    return state;
}
'''
CHECKS = {
    'bits': RANDOM + r'''extern int32_t bits(const char *, int64_t);
int main(void) {
    char input[48];
    uint64_t hash = 0;
    for (int round = 0; round < 50000; ++round) {
        int64_t count = next_random() % 48;
        for (int64_t index = 0; index < count; ++index) input[index] = (char)('0' + next_random() % 3);
        hash = hash * 31 + (uint32_t)bits(input, count);
    }
    printf("%llu\n", (unsigned long long)hash);
    return 0;
}
''',
    'init': RANDOM + r'''extern int32_t init(int64_t, const char *);
int main(void) {
    uint64_t hash = 0;
    for (int round = 0; round < 50000; ++round) {
        char source = (char)next_random();
        int64_t n = (next_random() % 4 == 0) ? 0 : (int64_t)(next_random() % 1024);
        hash = hash * 31 + (uint32_t)init(n, &source);
    }
    printf("%llu\n", (unsigned long long)hash);
    return 0;
}
''',
    'recursion': RANDOM + r'''extern void outer(int64_t *, int64_t);
int main(void) {
    int64_t values[64];
    uint64_t hash = 0;
    for (int round = 0; round < 20000; ++round) {
        for (int index = 0; index < 64; ++index) values[index] = (int64_t)(next_random() % 1000);
        outer(values, (int64_t)(next_random() % 60));
        for (int index = 0; index < 64; ++index) hash = hash * 31 + (uint64_t)values[index];
    }
    printf("%llu\n", (unsigned long long)hash);
    return 0;
}
''',
    'valid': RANDOM + r'''#include <stdbool.h>
extern bool valid(const char *, int64_t);
int main(void) {
    char input[1100];
    uint64_t hash = 0;
    for (int round = 0; round < 20000; ++round) {
        int64_t count = (int64_t)(next_random() % 1100);
        for (int64_t index = 0; index < count; ++index) input[index] = (char)(next_random() % 1000 == 0 ? 200 : next_random() % 128);
        hash = hash * 31 + valid(input, count);
    }
    printf("%llu\n", (unsigned long long)hash);
    return 0;
}
''',
    'scan': RANDOM + r'''extern void scan(int64_t *, int64_t *, int64_t, int64_t);
int main(void) {
    int64_t left[40], right[40];
    uint64_t hash = 0;
    for (int round = 0; round < 20000; ++round) {
        int64_t m = (int64_t)(next_random() % 40), n = 1 + (int64_t)(next_random() % 3);
        for (int index = 0; index < 40; ++index) {
            left[index] = (int64_t)(next_random() % 2000) - 100;
            right[index] = (int64_t)(next_random() % 1200);
        }
        scan(left, right, n, m);
        for (int index = 0; index < 40; ++index) hash = hash * 31 + (uint64_t)right[index];
    }
    printf("%llu\n", (unsigned long long)hash);
    return 0;
}
''',
}
RUNTIME = [
    ('bits', 'private-bit-updates', BITS, 'bits'),
    ('bits-switch', 'private-bit-updates', BITS_SWITCH, 'bits'),
    ('init', 'private-initializations', INIT, 'init'),
    ('recursion', 'small-recursion', RECURSION, 'recursion'),
    ('peel', 'validation-peel', SCAN, 'valid'),
    ('peel-bounded', 'validation-peel', BOUNDED, 'valid'),
    ('peel-tiny', 'validation-peel', TINY, 'valid'),
    ('nested', 'nested-scans', NEST, 'scan'),
    ('nested-checked', 'nested-scans', CHECKED, 'scan'),
]


def shape(count, again, module):
    patterns = [r'= load ', r'^\s+store ', r' = select ', r' = freeze ', r'^\s+(br|switch|ret|unreachable)\b', r'^\s+call ']
    return (count, again) + tuple(len(re.findall(pattern, module, re.M)) for pattern in patterns)


def tool(name):
    bindir = subprocess.run([CONFIG, '--bindir'], capture_output=True, text=True, check=True).stdout.strip()
    return str(Path(bindir) / name)


def run(command):
    return subprocess.run([str(part) for part in command], capture_output=True, text=True, check=True, timeout=120)


def outputs(work, name, pass_name, fixture, check):
    """The check's output linked with the fixture, before and after the pass."""
    count, module = run_pass(pass_name, fixture)
    assert count != 0, name
    harness = work / f'{name}.c'
    harness.write_text(CHECKS[check])
    results = []
    for label, text in [('base', fixture), ('candidate', module)]:
        source = work / f'{name}-{label}.ll'
        source.write_text(text.replace(MAC, NATIVE).replace(LINUX, NATIVE))
        binary = work / f'{name}-{label}'
        run([tool('clang'), '-O1', '-Wno-override-module', source, harness, '-o', binary])
        results.append(run([binary]).stdout)
    return results


def main():
    for name, (pass_name, ir) in CASES.items():
        count, module = run_pass(pass_name, ir)
        again, _ = run_pass(pass_name, module)
        assert shape(count, again, module) == EXPECTED[name], (name, shape(count, again, module), EXPECTED[name])
        print('PASS', name, flush=True)
    if os.uname().machine in ('arm64', 'aarch64'):
        with tempfile.TemporaryDirectory(prefix='elisa-validation-loops-') as temporary:
            for name, pass_name, fixture, check in RUNTIME:
                base, candidate = outputs(Path(temporary), name, pass_name, fixture, check)
                assert base == candidate, (name, base, candidate)
                print('PASS runtime', name, candidate.strip(), flush=True)
    print('validation loops: counts, shapes, second runs and runtime results passed')


if __name__ == '__main__':
    main()
