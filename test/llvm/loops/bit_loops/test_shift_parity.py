#!/usr/bin/env python3
"""Check the shift-parity loop fold against its shape and by execution.

A self-loop `w = phi(x, w >> 1); c = phi(0, c + t)` exiting when the shifted word is zero,
where `t` is `w` or `w & 1` and the only result used is `c & 1`, becomes `ctpop(x) & 1`
and its block is deleted (AArch64, i64 words).
"""
import os, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from elisa_llvm_pass import run_pass

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=120)


IR = '''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
target triple = "arm64-apple-darwin"
define i64 @f(i64 %x) {
entry:
  br label %body
body:
  %w = phi i64 [%x, %entry], [%s, %body]
  %c = phi i64 [0, %entry], [%sum, %body]
  %lb = and i64 %w, 1
  %sum = add i64 %c, %lb
  %s = lshr i64 %w, 1
  %done = icmp eq i64 %s, 0
  br i1 %done, label %exit, label %body
exit:
  %p = and i64 %sum, 1
  ret i64 %p
}
'''
WORD = IR.replace('  %lb = and i64 %w, 1\n', '').replace('add i64 %c, %lb', 'add i64 %c, %w')
NOT_EQUAL = IR.replace('icmp eq i64 %s, 0', 'icmp ne i64 %s, 0').replace('label %exit, label %body', 'label %body, label %exit')
CASES = {
    'low_bit': (IR, 1),
    'word': (WORD, 1),
    'not_equal': (NOT_EQUAL, 1),
    'sum_swapped': (IR.replace('add i64 %c, %lb', 'add i64 %lb, %c'), 1),
    'shift_two': (IR.replace('lshr i64 %w, 1', 'lshr i64 %w, 2'), 0),
    'compare_one': (IR.replace('icmp eq i64 %s, 0', 'icmp eq i64 %s, 1'), 0),
    'seed_one': (IR.replace('[0, %entry]', '[1, %entry]'), 0),
    'low_mask_three': (IR.replace('and i64 %w, 1', 'and i64 %w, 3'), 0),
    'parity_mask_three': (IR.replace('and i64 %sum, 1', 'and i64 %sum, 3'), 0),
    'sum_escapes': (IR.replace('  ret i64 %p', '  %r = add i64 %p, %sum\n  ret i64 %r'), 0),
    'size_optimized': (IR.replace('i64 %x) {', 'i64 %x) optsize {'), 0),
    'non_arm': (IR.replace('arm64-apple-darwin', 'x86_64-unknown-linux-gnu'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('shift-parity-loops', ir)
    assert got == want, (name, got)
    assert ('bit.parity' in module) == bool(want), (name, module)
    assert ('body:' in module) != bool(want), (name, module)
    print('PASS', name)

# The folded functions return the loop's parity for boundary words.
with tempfile.TemporaryDirectory(prefix='shift-parity-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    for label, ir in (('low', IR), ('word', WORD), ('ne', NOT_EQUAL)):
        (d / f'{label}.ll').write_text(ir.replace('@f(', f'@f_{label}('))
        (d / f'{label}_folded.ll').write_text(run_pass('shift-parity-loops', ir)[1].replace('@f(', f'@g_{label}('))
    (d / 'main.c').write_text(r"""#include <stdint.h>
extern uint64_t f_low(uint64_t), g_low(uint64_t), f_word(uint64_t), g_word(uint64_t);
extern uint64_t f_ne(uint64_t), g_ne(uint64_t);
int main(void) {
  const uint64_t values[] = {0, 1, 2, 3, 7, 8, 255, 256, 0x5555555555555555ull, 0x8000000000000000ull,
                             0x7fffffffffffffffull, 0xffffffffffffffffull, 0x123456789abcdefull};
  for (unsigned i = 0; i < sizeof values / sizeof values[0]; ++i) {
    if (f_low(values[i]) != g_low(values[i])) return 1;
    if (f_word(values[i]) != g_word(values[i])) return 2;
    if (f_ne(values[i]) != g_ne(values[i])) return 3;
  }
  return 0;
}
""")
    sources = [d / f'{label}{suffix}.ll' for label in ('low', 'word', 'ne') for suffix in ('', '_folded')]
    run([bindir / 'clang', '-O1', '-Wno-override-module', *sources, d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
