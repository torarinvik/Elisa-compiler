#!/usr/bin/env python3
"""Check the shared-divisibility fold against its shape and by execution.

`n % A == 0 || (n & (2^b - 1) == 0 && n % B != 0)`, with A = odd * 2^a and B = odd * 2^b for
a > b, becomes one block testing `n & (2^b - 1) == 0 && (n & (2^a - 1) == 0 || n % odd != 0)`
(the leap-year test with A = 400, B = 100). The chain's middle and last blocks go away.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=120)


def chain(width='i32', large=400, small=100, mask=3, one='1', triple='arm64-apple-darwin'):
    return f'''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
target triple = "{triple}"
define i32 @f({width} %n) {{
start:
  %r1 = urem {width} %n, {large}
  %c1 = icmp eq {width} %r1, 0
  br i1 %c1, label %exit, label %middle
middle:
  %m = and {width} %n, {mask}
  %c2 = icmp eq {width} %m, 0
  br i1 %c2, label %last, label %exit
last:
  %r2 = urem {width} %n, {small}
  %c3 = icmp ne {width} %r2, 0
  %z = zext i1 %c3 to i32
  br label %exit
exit:
  %p = phi i32 [{one}, %start], [0, %middle], [%z, %last]
  ret i32 %p
}}
'''


LEAP = chain()
THIRDS = chain(large=48, small=12)
ODD = chain(large=50, small=25, mask=0)
CASES = {
    'leap': (LEAP, 1),
    'thirds': (THIRDS, 1),
    'odd_small': (ODD, 1),
    'leap_i128': (chain(width='i128'), 1),
    'odd_small_wrong_mask': (chain(large=50, small=25, mask=5), 0),
    'power_of_two': (chain(large=16, small=4), 0),
    'odd_parts_differ': (chain(large=400, small=300), 0),
    'mask_wrong': (chain(mask=7), 0),
    'start_not_one': (chain(one='2'), 0),
    'non_arm': (chain(triple='x86_64-unknown-linux-gnu'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('shared-divisibility', ir)
    assert got == want, (name, got)
    assert ('middle:' in module) != bool(want), (name, module)
    print('PASS', name)

# The folded functions agree with the chains on every 32-bit input pattern sampled.
with tempfile.TemporaryDirectory(prefix='shared-divisibility-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    variants = (('leap', LEAP), ('thirds', THIRDS), ('odd', ODD))
    for label, ir in variants:
        (d / f'{label}.ll').write_text(ir.replace('@f(', f'@f_{label}('))
        (d / f'{label}_folded.ll').write_text(run_pass('shared-divisibility', ir)[1].replace('@f(', f'@g_{label}('))
    (d / 'main.c').write_text(r"""#include <stdint.h>
extern int f_leap(uint32_t), g_leap(uint32_t), f_thirds(uint32_t), g_thirds(uint32_t);
extern int f_odd(uint32_t), g_odd(uint32_t);
int main(void) {
  for (uint64_t n = 0; n <= 0xffffffffull; n += (n < 100000 ? 1 : 9973)) {
    if (f_leap(n) != g_leap(n)) return 1;
    if (f_thirds(n) != g_thirds(n)) return 2;
    if (f_odd(n) != g_odd(n)) return 3;
  }
  return 0;
}
""")
    sources = [d / f'{label}{suffix}.ll' for label, _ in variants for suffix in ('', '_folded')]
    run([bindir / 'clang', '-O1', '-Wno-override-module', *sources, d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
