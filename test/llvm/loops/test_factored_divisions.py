#!/usr/bin/env python3
"""Check the factored-divisor split against its shape and by execution.

In a loop, `n udiv ((c ? 3 : 1) * ((i & 1) + 1))` of a dividend with at most 32 active bits
becomes `c ? (n >> b) / 3 : n >> b` on 32 bits, where `b` is the bit (inverted for
`2 - (i & 1)`). Both uses of the product must be such divisions.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elisa_llvm_pass import run_pass

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=120)


IR = '''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
target triple = "arm64-apple-darwin"
define i64 @f(i64 %x, i64 %y, i64 %count, i1 %c) {
entry:
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%i.next, %loop]
  %acc = phi i64 [0, %entry], [%s2, %loop]
  %n = and i64 %x, 4294967295
  %m = and i64 %y, 65535
  %b = and i64 %i, 1
  %even = add i64 %b, 1
  %odd = select i1 %c, i64 3, i64 1
  %d = mul i64 %odd, %even
  %q1 = udiv i64 %n, %d
  %q2 = udiv i64 %m, %d
  %s1 = add i64 %acc, %q1
  %s2 = add i64 %s1, %q2
  %i.next = add i64 %i, 1
  %more = icmp ult i64 %i.next, %count
  br i1 %more, label %loop, label %exit
exit:
  ret i64 %s2
}
'''
INVERTED = IR.replace('%even = add i64 %b, 1', '%even = sub i64 2, %b')
CASES = {
    'split': (IR, 1),
    'inverted': (INVERTED, 1),
    'operands_swapped': (IR.replace('mul i64 %odd, %even', 'mul i64 %even, %odd'), 1),
    'wide_dividend': (IR.replace('and i64 %x, 4294967295', 'and i64 %x, 8589934591'), 0),
    'odd_reversed': (IR.replace('i64 3, i64 1', 'i64 1, i64 3'), 0),
    'exact': (IR.replace('udiv i64 %n', 'udiv exact i64 %n'), 0),
    'size_optimized': (IR.replace('i1 %c) {', 'i1 %c) optsize {'), 0),
    'non_arm': (IR.replace('arm64-apple-darwin', 'x86_64-unknown-linux-gnu'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('factored-divisions', ir)
    assert got == want, (name, got)
    assert ('factored.div.third' in module) == bool(want), (name, module)
    print('PASS', name)

# The split loop computes the same sum over boundary dividends, counts and both selectors.
with tempfile.TemporaryDirectory(prefix='factored-divisions-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    for label, ir in (('plus', IR), ('minus', INVERTED)):
        (d / f'{label}.ll').write_text(ir.replace('@f(', f'@f_{label}('))
        (d / f'{label}_split.ll').write_text(run_pass('factored-divisions', ir)[1].replace('@f(', f'@g_{label}('))
    (d / 'main.c').write_text(r"""#include <stdint.h>
#include <stdbool.h>
extern uint64_t f_plus(uint64_t, uint64_t, uint64_t, bool), g_plus(uint64_t, uint64_t, uint64_t, bool);
extern uint64_t f_minus(uint64_t, uint64_t, uint64_t, bool), g_minus(uint64_t, uint64_t, uint64_t, bool);
int main(void) {
  const uint64_t values[] = {0, 1, 2, 3, 5, 6, 7, 11, 12, 65535, 65536, 4294967293ull,
                             4294967294ull, 4294967295ull, 4294967296ull, 0xffffffffffffffffull};
  const int n = sizeof values / sizeof values[0];
  for (int a = 0; a < n; ++a)
    for (int b = 0; b < n; ++b)
      for (uint64_t count = 1; count < 6; ++count)
        for (int c = 0; c < 2; ++c) {
          if (f_plus(values[a], values[b], count, c) != g_plus(values[a], values[b], count, c)) return 1;
          if (f_minus(values[a], values[b], count, c) != g_minus(values[a], values[b], count, c)) return 2;
        }
  return 0;
}
""")
    sources = [d / f'{label}{suffix}.ll' for label in ('plus', 'minus') for suffix in ('', '_split')]
    run([bindir / 'clang', '-O1', '-Wno-override-module', *sources, d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
