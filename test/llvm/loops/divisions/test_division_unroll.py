#!/usr/bin/env python3
"""Check the bounded-division unroll against its shapes, and run what it unrolled.

`bounded-division-unroll` unrolls small loops that divide a value by a constant. Each
case's count, and the divisions, assumes, checked adds, `add nsw` counters and traps it
leaves, are what the C++ pass did with the same shapes (division_unroll_cases.py). A
second run changes nothing. The digit-count loops, before and after the pass, then run
next to each other over inputs at the edges of their range and of their counters'
overflow: results and traps must agree.
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
from division_unroll_cases import CASES, EXPECTED, MAC, MAXIMUM, MINIMUM
from elisa_llvm_pass import run_pass

PASS = 'bounded-division-unroll'
CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config' if os.uname().sysname == 'Darwin' else '/usr/lib/llvm-23/bin/llvm-config')
NATIVE = MAC if os.uname().sysname == 'Darwin' else 'aarch64-unknown-linux-gnu'
# The pass stops after 32 screened functions, so a second run takes the rest.
BUDGETED = {'functions-33'}
HARNESS = r'''
#include <inttypes.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
extern int64_t count_with_offset(int64_t, int64_t);
static void caught(int signal_number) { (void)signal_number; _Exit(77); }
int main(int argc, char **argv) {
  if (argc != 3) return 2;
  signal(SIGILL, caught);
  signal(SIGTRAP, caught);
  printf("%" PRId64 "\n", count_with_offset(strtoimax(argv[1], 0, 10), strtoimax(argv[2], 0, 10)));
  return 0;
}
'''
INPUTS = [(1, MAXIMUM), (10, MAXIMUM), (100, MAXIMUM - 1), (99999999, MAXIMUM - 7), (99999999, MAXIMUM - 6),
          (99, MINIMUM), (0, MAXIMUM), (135, 0), (10000000, 0), (100000000, 0), (999, 5)]


def shape(count, module):
    return (count, len(re.findall(r'= udiv ', module)), len(re.findall(r'call void @llvm\.assume\(', module)),
            len(re.findall(r'= call \{ i\d+, i1 \} @llvm\.[su]add\.with\.overflow', module)),
            len(re.findall(r'= add nsw i\d+ %', module)), len(re.findall(r'call void @llvm\.trap\(\)', module)))


def without_header(module):
    return [line for line in module.splitlines() if not line.startswith(('; ModuleID', 'source_filename'))]


def run_side_by_side(name):
    """Build the case before and after the pass and run both over INPUTS."""
    _, module = run_pass(PASS, CASES[name])
    clang = Path(subprocess.run([CONFIG, '--bindir'], capture_output=True, text=True, check=True).stdout.strip()) / 'clang'
    with tempfile.TemporaryDirectory(prefix='elisa-division-unroll-') as temporary:
        work = Path(temporary)
        harness = work / 'main.c'
        harness.write_text(HARNESS)
        binaries = []
        for label, text in [('baseline', CASES[name]), ('candidate', module)]:
            source = work / f'{label}.ll'
            source.write_text(text.replace(MAC, NATIVE))
            binary = work / label
            subprocess.run([str(clang), '-O1', str(source), str(harness), '-o', str(binary)], check=True, capture_output=True, timeout=60)
            binaries.append(binary)
        for n, offset in INPUTS:
            results = [subprocess.run([str(binary), str(n), str(offset)], capture_output=True, text=True, timeout=5) for binary in binaries]
            outcomes = [(result.returncode, result.stdout) for result in results]
            assert outcomes[0] == outcomes[1], (name, n, offset, outcomes)
    print('PASS runtime', name, flush=True)


def main():
    for name, ir in CASES.items():
        count, module = run_pass(PASS, ir)
        assert shape(count, module) == EXPECTED[name], (name, shape(count, module), EXPECTED[name])
        again_count, again = run_pass(PASS, module)
        assert name in BUDGETED or again_count == 0 and without_header(again) == without_header(module), (name, 'not idempotent')
        print('PASS', name, flush=True)
    if os.uname().machine in ('arm64', 'aarch64'):
        for name in ['base', 'positive', 'negative', 'maximum-safe', 'maximum-trap', 'minimum-safe', 'minimum-trap', 'zero-test-defined']:
            run_side_by_side(name)
    print('bounded division unroll: counts, shapes, idempotence and runtime results passed')


if __name__ == '__main__':
    main()
