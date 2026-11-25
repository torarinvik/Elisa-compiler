#!/usr/bin/env python3
"""Check the bounded-product proofs against their shapes, and run the proved products.

`bounded-products` drops the overflow checks of a power loop whose every product it
proves to fit. Each case's count, and the checked multiplies, checked adds, assumptions,
`mul nsw` and freezes it leaves, are what the C++ pass did with the same shapes
(bounded_product_cases.py), and so is what a second run changes: the pass assumes a
divided phi's maximum again while a checked counter of its loop is left. Two C++ flaws
are fixed rather than kept: the freeze of a proved base is removed when only the
multiply and instructions it dominates use it, and the product proofs see the
assumptions the first phase adds. On the header-counter fixture the overflow flag of the
counter's final add must stay observable. The scan-power fixture, before and after the
pass and a cleanup, then runs over bounded_product_harness.c's inputs: results and traps
must agree, for the safe base, for a base too large to prove, and for a base bounded
only by the first phase's assumptions.
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
from bounded_product_cases import CASES, EXPECTED, HEADER_COUNTER, LINUX, MAC
from elisa_llvm_pass import run_pass

PASS = 'bounded-products'
CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config' if os.uname().sysname == 'Darwin' else '/usr/lib/llvm-23/bin/llvm-config')
NATIVE = MAC if os.uname().sysname == 'Darwin' else LINUX
# The cleanup the late pipeline runs after the proofs (the Darwin AArch64 one also
# vectorizes the reductions they free).
CLEANUP = 'function(correlated-propagation,instcombine,simplifycfg)'
DARWIN_CLEANUP = 'function(correlated-propagation,instcombine,simplifycfg,loop-simplify,lcssa,loop-vectorize,instcombine,simplifycfg)'


def shape(count, module):
    return (count, len(re.findall(r'call \{ i\d+, i1 \} @llvm\.smul\.with\.overflow', module)),
            len(re.findall(r'call \{ i\d+, i1 \} @llvm\.[su]add\.with\.overflow', module)),
            len(re.findall(r'call void @llvm\.assume\(', module)), len(re.findall(r'= mul nsw ', module)),
            len(re.findall(r'= freeze ', module)))


def tool(name):
    bindir = subprocess.run([CONFIG, '--bindir'], capture_output=True, text=True, check=True).stdout.strip()
    return str(Path(bindir) / name)


def run(command):
    return subprocess.run([str(part) for part in command], capture_output=True, text=True, check=True, timeout=120)


def check_header_counter(work):
    """The final header visit takes no backedge, but its checked add still runs: the
    flag it returns must still be set."""
    _, module = run_pass(PASS, HEADER_COUNTER)
    check = work / 'header-check.c'
    check.write_text('#include <stdint.h>\nextern int64_t header_counter(void);\nint main(void){return header_counter()!=1;}\n')
    for label, text in [('base', HEADER_COUNTER), ('candidate', module)]:
        source = work / f'header-{label}.ll'
        source.write_text(text.replace(MAC, NATIVE))
        run([tool('clang'), '-O0', source, check, '-o', work / f'header-{label}'])
        run([work / f'header-{label}'])
    print('PASS runtime header-counter', flush=True)


def check_scan_power(work, name, modulus):
    """The case before the pass, and after the pass and the cleanup, over the harness."""
    _, module = run_pass(PASS, CASES[name])
    changed = work / f'{name}-changed.ll'
    changed.write_text(module.replace(MAC, NATIVE))
    cleaned = work / f'{name}-clean.ll'
    darwin_aarch64 = NATIVE == MAC and os.uname().machine == 'arm64'
    run([tool('opt'), '-passes=' + (DARWIN_CLEANUP if darwin_aarch64 else CLEANUP), '-S', changed, '-o', cleaned])
    original = work / f'{name}.ll'
    original.write_text(CASES[name].replace(MAC, NATIVE))
    outputs = []
    for label, source in [('base', original), ('candidate', cleaned)]:
        binary = work / f'{name}-{label}'
        run([tool('clang'), '-O0', '-D_POSIX_C_SOURCE=200809L', f'-DMODULUS={modulus}', source, HERE / 'bounded_product_harness.c', '-o', binary])
        outputs.append(run([binary]).stdout.strip())
    assert outputs[0] == outputs[1], (name, outputs)
    print('PASS runtime', name, outputs[1], flush=True)


QUOTIENT_CHECK = r'''#include <stdint.h>
#include <stdio.h>
extern int64_t scan_power(int64_t, int64_t, int64_t);
int main(void) {
    uint64_t state = 88172645463325252ULL, hash = 0;
    for (int round = 0; round < 200000; ++round) {
        state ^= state << 13; state ^= state >> 7; state ^= state << 17;
        int64_t n = (int64_t)(state % 100000000ULL), position = (int64_t)((state >> 40) % 10);
        hash = hash * 31 + (uint64_t)scan_power(n, position, (int64_t)(state >> 20));
    }
    printf("%llu\n", (unsigned long long)hash);
    return 0;
}
'''


def check_base_quotient(work):
    """base-quotient's base is bounded only by the first phase's assumptions (the C++ pass
    lost them and kept the check): before and after the pass, every result must agree."""
    _, module = run_pass(PASS, CASES['base-quotient'])
    harness = work / 'quotient-check.c'
    harness.write_text(QUOTIENT_CHECK)
    outputs = []
    for label, text in [('base', CASES['base-quotient']), ('candidate', module)]:
        source = work / f'quotient-{label}.ll'
        source.write_text(text.replace(MAC, NATIVE))
        binary = work / f'quotient-{label}'
        run([tool('clang'), '-O1', '-Wno-override-module', source, harness, '-o', binary])
        outputs.append(run([binary]).stdout.strip())
    assert outputs[0] == outputs[1], ('base-quotient', outputs)
    print('PASS runtime base-quotient', outputs[1], flush=True)


def main():
    for name, ir in CASES.items():
        count, module = run_pass(PASS, ir)
        again, _ = run_pass(PASS, module)
        assert shape(count, module) + (again,) == EXPECTED[name], (name, shape(count, module) + (again,), EXPECTED[name])
        print('PASS', name, flush=True)
    if os.uname().machine in ('arm64', 'aarch64'):
        with tempfile.TemporaryDirectory(prefix='elisa-bounded-products-') as temporary:
            work = Path(temporary)
            check_header_counter(work)
            check_scan_power(work, 'safe', 10)
            check_scan_power(work, 'large-base', 2147483647)
            check_base_quotient(work)
    print('bounded products: counts, shapes, second runs and runtime results passed')


if __name__ == '__main__':
    main()
