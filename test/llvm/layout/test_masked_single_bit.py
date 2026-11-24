#!/usr/bin/env python3
"""Check the fused single-bit test against its shape and over every 16-bit input.

`x > 0 && ctpop(x) < 2 ? (x & M) != 0 : false`, with the mask test in its own block,
becomes `zext(x & (x - 1) == 0 and (x & M) != 0)`: a value with at most one bit set,
selected by a mask that excludes the sign bit, is already positive.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elisa_llvm_pass import run_pass

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')
TRIPLE = os.environ.get('ELISA_TEST_TRIPLE', 'arm64-apple-darwin')


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=60)


IR = '''target triple = "TRIPLE"
declare i16 @llvm.ctpop.i16(i16)
define i32 @f(i16 %x) {
entry:
  %positive = icmp sgt i16 %x, 0
  %count = call i16 @llvm.ctpop.i16(i16 %x)
  %small = icmp ult i16 %count, 2
  %single = select i1 %positive, i1 %small, i1 false
  br i1 %single, label %mask, label %exit
mask:
  %masked = and i16 %x, 1300
  %nonzero = icmp ne i16 %masked, 0
  %extended = zext i1 %nonzero to i32
  br label %exit
exit:
  %result = phi i32 [ 0, %entry ], [ %extended, %mask ]
  ret i32 %result
}
'''.replace('TRIPLE', TRIPLE)

CASES = {
    'fused': (IR, 1),
    'sign_bit_mask': (IR.replace('and i16 %x, 1300', 'and i16 %x, -32768'), 0),
    'nonnegative_guard': (IR.replace('icmp sgt i16 %x, 0', 'icmp sge i16 %x, 0'), 0),
    'two_bits_allowed': (IR.replace('icmp ult i16 %count, 2', 'icmp ult i16 %count, 3'), 0),
    'nonzero_other_edge': (IR.replace('[ 0, %entry ]', '[ 1, %entry ]'), 0),
    'non_arm': (IR.replace(TRIPLE, 'x86_64-unknown-linux-gnu'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('masked-single-bits', ir)
    assert got == want, (name, got)
    assert ('ctpop' in module.split('define', 1)[1]) != bool(want), (name, module)
    print('PASS', name)

# The fused function agrees with the original on every 16-bit input.
with tempfile.TemporaryDirectory(prefix='masked-single-bit-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    (d / 'input.ll').write_text(IR)
    (d / 'optimized.ll').write_text(run_pass('masked-single-bits', IR)[1].replace('@f(', '@g('))
    (d / 'main.c').write_text(r"""#include <stdint.h>
extern int32_t f(int16_t);
extern int32_t g(int16_t);
int main(void) {
  for (int32_t x = -32768; x < 32768; ++x)
    if (f((int16_t)x) != g((int16_t)x)) return 1;
  return 0;
}
""")
    run([bindir / 'clang', '-O1', d / 'input.ll', d / 'optimized.ll', d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS exhaustive 16-bit equivalence')
