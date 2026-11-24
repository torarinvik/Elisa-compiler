#!/usr/bin/env python3
"""Check the masked split-multiply fold against its shape and by execution.

`(((x & L) * f) + ((((x >> k) * g) & L) << k)) & M`, with L the low k bits, M the low 2k
bits and f, g agreeing in their low k bits, becomes `(x * f) & M` (plus any constant added
before the mask). The limbs may be two simple loads of one address with no write between.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elisa_llvm_pass import run_pass

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=120)


def split(width='i64', half=16, low_factor=40503, high_factor=40503, increment='', between='', loads=False, volatile=False):
    limb = (1 << half) - 1
    full = (1 << (2 * half)) - 1
    if loads:
        params = 'ptr %p'
        body = f'  %a = load {"volatile " if volatile else ""}{width}, ptr %p\n{between}  %b = load {width}, ptr %p\n'
        low_input, high_input = '%a', '%b'
    else:
        params, body, low_input, high_input = f'{width} %x', '', '%x', '%x'
    masked = '%sum'
    if increment:
        body_tail = f'  %inc = add {width} %sum, {increment}\n'
        masked = '%inc'
    else:
        body_tail = ''
    return f'''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
target triple = "arm64-apple-darwin"
declare void @g()
define {width} @f({params}) {{
entry:
{body}  %lo = and {width} {low_input}, {limb}
  %lp = mul {width} %lo, {low_factor}
  %hi = lshr {width} {high_input}, {half}
  %hp = mul {width} %hi, {high_factor}
  %hm = and {width} %hp, {limb}
  %hs = shl {width} %hm, {half}
  %sum = add {width} %lp, %hs
{body_tail}  %r = and {width} {masked}, {full}
  ret {width} %r
}}
'''


BASE = split()
CASES = {
    'base': (BASE, 1),
    'increment': (split(increment='7'), 1),
    'factors_agree_low': (split(high_factor=40503 + 65536 * 5), 1),
    'factors_differ_low': (split(high_factor=40501), 0),
    'same_loads': (split(loads=True), 1),
    'store_between': (split(loads=True, between='  store i64 0, ptr %p\n'), 0),
    'call_between': (split(loads=True, between='  call void @g()\n'), 0),
    'volatile_load': (split(loads=True, volatile=True), 0),
    'width_32': (split(width='i32', half=8, low_factor=77, high_factor=77), 1),
    'width_128': (split(width='i128', half=32, low_factor=3000000019, high_factor=3000000019 + (1 << 40)), 1),
    'mask_odd': (BASE.replace('and i64 %sum, 4294967295', 'and i64 %sum, 2147483647'), 0),
    'shift_fifteen': (BASE.replace('lshr i64 %x, 16', 'lshr i64 %x, 15'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('masked-split-multiplies', ir)
    assert got == want, (name, got)
    # The fold leaves the dead limbs for later cleanup; the return reads the new product.
    assert ('ret' in module and ' %r\n}' not in module) == bool(want), (name, module)
    print('PASS', name)

# The folded functions compute the same masked product over boundary inputs.
with tempfile.TemporaryDirectory(prefix='masked-split-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    variants = (('plain', BASE), ('increment', split(increment='7')), ('agree', split(high_factor=40503 + 65536 * 5)))
    for label, ir in variants:
        (d / f'{label}.ll').write_text(ir.replace('@f(', f'@f_{label}('))
        (d / f'{label}_folded.ll').write_text(run_pass('masked-split-multiplies', ir)[1].replace('@f(', f'@h_{label}('))
    (d / 'main.c').write_text(r"""#include <stdint.h>
extern uint64_t f_plain(uint64_t), h_plain(uint64_t), f_increment(uint64_t), h_increment(uint64_t);
extern uint64_t f_agree(uint64_t), h_agree(uint64_t);
int main(void) {
  const uint64_t values[] = {0, 1, 2, 65535, 65536, 65537, 0xffffffffull, 0x100000000ull,
                             0x123456789abcdefull, 0xffffffffffffffffull, 0x8000000000000000ull};
  for (unsigned i = 0; i < sizeof values / sizeof values[0]; ++i) {
    if (f_plain(values[i]) != h_plain(values[i])) return 1;
    if (f_increment(values[i]) != h_increment(values[i])) return 2;
    if (f_agree(values[i]) != h_agree(values[i])) return 3;
  }
  return 0;
}
""")
    sources = [d / f'{label}{suffix}.ll' for label, _ in variants for suffix in ('', '_folded')]
    run([bindir / 'clang', '-O1', '-Wno-override-module', *sources, d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
