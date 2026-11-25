#!/usr/bin/env python3
"""Check the halving-run fold against its shape and by execution.

A single-block loop that steps `w` to `w / 2` when even and `3w + 1` when odd, counting steps
until `w == 1`, takes the odd step (if any) and then every following halving at once:
`cttz` of the even value, masked to 63, is both the shift and the number of steps added.
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
  %start = icmp eq i64 %x, 1
  br i1 %start, label %exit, label %body
body:
  %w = phi i64 [%x, %entry], [%n, %body]
  %c = phi i64 [0, %entry], [%c.next, %body]
  %half = lshr i64 %w, 1
  %bit = and i64 %w, 1
  %even = icmp eq i64 %bit, 0
  %triple = mul i64 %w, 3
  %odd = add i64 %triple, 1
  %n = select i1 %even, i64 %half, i64 %odd
  %c.next = add i64 %c, 1
  %done = icmp eq i64 %n, 1
  br i1 %done, label %exit, label %body
exit:
  %r = phi i64 [0, %entry], [%c.next, %body]
  ret i64 %r
}
'''
CASES = {
    'folded': (IR, 1),
    'parity_inverted': (IR.replace('icmp eq i64 %bit, 0', 'icmp ne i64 %bit, 0').replace('i64 %half, i64 %odd', 'i64 %odd, i64 %half'), 1),
    'times_five': (IR.replace('mul i64 %w, 3', 'mul i64 %w, 5'), 0),
    'arithmetic_shift': (IR.replace('lshr i64 %w, 1', 'ashr i64 %w, 1'), 0),
    'counts_by_two': (IR.replace('add i64 %c, 1', 'add i64 %c, 2'), 0),
    'size_optimized': (IR.replace('@f(i64 %x) {', '@f(i64 %x) optsize {'), 0),
    'non_arm': (IR.replace('arm64-apple-darwin', 'x86_64-unknown-linux-gnu'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('halving-runs', ir)
    assert got == want, (name, got)
    assert ('llvm.cttz.i64' in module) == bool(want), (name, module)
    print('PASS', name)

# The folded loop counts the same number of steps for every start below 200000.
with tempfile.TemporaryDirectory(prefix='halving-runs-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    (d / 'input.ll').write_text(IR)
    (d / 'optimized.ll').write_text(run_pass('halving-runs', IR)[1].replace('@f(', '@g('))
    (d / 'main.c').write_text(r"""#include <stdint.h>
extern int64_t f(int64_t);
extern int64_t g(int64_t);
int main(void) {
  for (int64_t x = 1; x < 200000; ++x) if (f(x) != g(x)) return 1;
  return 0;
}
""")
    run([bindir / 'clang', '-O1', '-Wno-override-module', d / 'input.ll', d / 'optimized.ll', d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
