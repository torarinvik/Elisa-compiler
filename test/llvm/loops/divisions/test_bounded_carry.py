#!/usr/bin/env python3
"""Check the bounded carry narrowing against its shape and by execution.

In a loop `carry' = (carry + freeze(product)) / divisor`, a product scalar evolution keeps
below 2^31 and a carry seeded at most UINT32_MAX/2 keep every sum below 2^32, so the
64-bit division becomes a 32-bit unsigned one (`carry.quotient`) on AArch64.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from elisa_llvm_pass import run_pass

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=60)


IR = '''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
target triple = "arm64-apple-darwin"
define i64 @f(ptr %in, ptr %out, i64 %n) {
entry:
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%i.next, %loop]
  %carry = phi i64 [SEED, %entry], [%q, %loop]
  %p = getelementptr i16, ptr %in, i64 %i
  %v = load i16, ptr %p
  %w = zext i16 %v to i64
  %m = mul nuw i64 %w, SCALE
  %fr = freeze i64 %m
  %s = add i64 %carry, %fr
  %q = udiv i64 %s, 10
  %r = urem i64 %s, 10
  %o = getelementptr i64, ptr %out, i64 %i
  store i64 %r, ptr %o
  %i.next = add i64 %i, 1
  %c = icmp ult i64 %i.next, %n
  br i1 %c, label %loop, label %exit
exit:
  ret i64 %q
}
'''
BASE = IR.replace('SEED', '7').replace('SCALE', '32768')
CASES = {
    'narrowed': (BASE, 1),
    'seed_over_half': (IR.replace('SEED', '2147483648').replace('SCALE', '32768'), 0),
    'product_32_bits': (IR.replace('SEED', '7').replace('SCALE', '65537'), 0),
    'unfrozen': (BASE.replace('%fr = freeze i64 %m', '%fr = add i64 %m, 0'), 0),
    'exact': (BASE.replace('udiv i64 %s, 10', 'udiv exact i64 %s, 10'), 0),
    'non_arm': (BASE.replace('arm64-apple-darwin', 'x86_64-unknown-linux-gnu'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('bounded-carries', ir)
    assert got == want, (name, got)
    assert ('carry.quotient' in module) == bool(want), (name, module)
    if want:
        assert 'udiv i32' in module and 'carry.product' in module and 'freeze i31' in module, module
    print('PASS', name)

# The narrowed loop computes the same quotients and remainders for random inputs.
with tempfile.TemporaryDirectory(prefix='bounded-carry-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    (d / 'input.ll').write_text(BASE)
    (d / 'optimized.ll').write_text(run_pass('bounded-carries', BASE)[1].replace('@f(', '@g('))
    (d / 'main.c').write_text(r"""#include <stdint.h>
#include <string.h>
extern int64_t f(const uint16_t *, int64_t *, int64_t);
extern int64_t g(const uint16_t *, int64_t *, int64_t);
int main(void) {
  uint32_t seed = 12345;
  for (int round = 0; round < 2000; ++round) {
    uint16_t in[64]; int64_t expected[64], actual[64];
    for (int k = 0; k < 64; ++k) { seed = seed * 1103515245u + 12345u; in[k] = (round & 1) ? 65535 : (uint16_t)(seed >> 8); }
    int64_t n = 1 + round % 64;
    if (f(in, expected, n) != g(in, actual, n) || memcmp(expected, actual, (size_t)n * 8) != 0) return 1;
  }
  return 0;
}
""")
    run([bindir / 'clang', '-O1', '-Wno-override-module', d / 'input.ll', d / 'optimized.ll', d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
