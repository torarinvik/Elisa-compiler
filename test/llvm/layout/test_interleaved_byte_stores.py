#!/usr/bin/env python3
"""Check the interleaved halfword-byte store rewrite against its shape and by execution.

A store of `trunc(shuffle(x, x >> 8, <0, n, 1, n+1, ...>))` writes each halfword's low byte
then its high byte, which on a little-endian target is `x` itself; the store keeps its
address, alignment and metadata but stores `bitcast x`.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elisa_llvm_pass import run_pass

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')
LAYOUT = 'e-m:o-i64:64-i128:128-n32:64-S128'
MASK = ', '.join(f'i32 {lane}, i32 {8 + lane}' for lane in range(8))
MASK_AFTER = ', '.join(f'i32 {lane}, i32 {16 + lane}' for lane in range(16))


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=60)


BEFORE = f'''target datalayout = "{LAYOUT}"
define void @f(<8 x i16> %x, ptr %p) {{
  %h = lshr <8 x i16> %x, splat (i16 8)
  %lo = trunc <8 x i16> %x to <8 x i8>
  %hi = trunc <8 x i16> %h to <8 x i8>
  %b = shufflevector <8 x i8> %lo, <8 x i8> %hi, <16 x i32> <{MASK}>
  store <16 x i8> %b, ptr %p, align 1, !nontemporal !0
  ret void
}}
!0 = !{{i32 1}}
'''

AFTER = f'''target datalayout = "{LAYOUT}"
define void @f(<16 x i16> %x, ptr %p) {{
  %h = lshr <16 x i16> %x, splat (i16 8)
  %s = shufflevector <16 x i16> %x, <16 x i16> %h, <32 x i32> <{MASK_AFTER}>
  %b = trunc <32 x i16> %s to <32 x i8>
  store <32 x i8> %b, ptr %p, align 2
  ret void
}}
'''

CASES = {
    'truncate_first': (BEFORE, 1),
    'truncate_last': (AFTER, 1),
    'big_endian': (BEFORE.replace(LAYOUT, 'E-m:e-i64:64-n32:64'), 0),
    'no_layout': (BEFORE.replace(f'target datalayout = "{LAYOUT}"\n', ''), 0),
    'shift_seven': (BEFORE.replace('splat (i16 8)', 'splat (i16 7)'), 0),
    'volatile': (BEFORE.replace('store <16', 'store volatile <16'), 0),
    'high_first': (BEFORE.replace('%lo, <8 x i8> %hi', '%hi, <8 x i8> %lo'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('interleaved-byte-stores', ir)
    assert got == want, (name, got)
    body = module.split('define', 1)[1]
    assert ('shufflevector' in body) != bool(want), (name, module)
    if name == 'truncate_first':
        assert 'bitcast <8 x i16> %x to <16 x i8>' in body and '!nontemporal' in body, module
    print('PASS', name)

# The rewritten store writes the same 16 bytes as the original for many inputs.
with tempfile.TemporaryDirectory(prefix='interleaved-byte-stores-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    (d / 'input.ll').write_text(BEFORE)
    (d / 'optimized.ll').write_text(run_pass('interleaved-byte-stores', BEFORE)[1].replace('@f(', '@g('))
    (d / 'main.c').write_text(r"""#include <stdint.h>
#include <string.h>
typedef uint16_t halfwords __attribute__((ext_vector_type(8)));
extern void f(halfwords, uint8_t *);
extern void g(halfwords, uint8_t *);
int main(void) {
  uint32_t seed = 12345;
  for (int round = 0; round < 100000; ++round) {
    halfwords x;
    for (int lane = 0; lane < 8; ++lane) { seed = seed * 1103515245u + 12345u; x[lane] = (uint16_t)(seed >> 8); }
    uint8_t expected[16], actual[16];
    f(x, expected);
    g(x, actual);
    if (memcmp(expected, actual, 16) != 0) return 1;
  }
  return 0;
}
""")
    run([bindir / 'clang', '-O1', '-Wno-override-module', d / 'input.ll', d / 'optimized.ll', d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
