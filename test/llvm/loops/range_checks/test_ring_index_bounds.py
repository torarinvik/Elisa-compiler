#!/usr/bin/env python3
"""Check the ring-index bounds fold against its shape and by execution.

A zero-seeded loop-header index that steps by one and wraps to zero on reaching an
invariant limit stays below that limit, so `index < capacity` folds to true when the limit
is proven nonzero, at most the capacity and not poison on entry to the loop.
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
declare void @llvm.trap()
define i64 @f(ptr %a, i64 noundef %lim, i64 %n) {
entry:
  %ok = icmp ule i64 %lim, 16
  %nz = icmp ne i64 %lim, 0
  %both = and i1 %ok, %nz
  br i1 %both, label %pre, label %out
pre:
  br label %header
header:
  %idx = phi i64 [0, %pre], [%wrapped, %latch]
  %k = phi i64 [0, %pre], [%k.next, %latch]
  %in = icmp ult i64 %idx, 16
  br i1 %in, label %latch, label %trap
trap:
  call void @llvm.trap()
  unreachable
latch:
  %p = getelementptr i64, ptr %a, i64 %idx
  store i64 %k, ptr %p
  %next = add i64 %idx, 1
  %w = icmp eq i64 %next, %lim
  %wrapped = select i1 %w, i64 0, i64 %next
  %k.next = add i64 %k, 1
  %c = icmp ult i64 %k.next, %n
  br i1 %c, label %header, label %out
out:
  ret i64 0
}
'''
CASES = {
    'proven': (IR, 1),
    'limit_over_capacity': (IR.replace('icmp ule i64 %lim, 16', 'icmp ule i64 %lim, 17'), 0),
    'limit_may_be_zero': (IR.replace('and i1 %ok, %nz', 'and i1 %ok, true'), 0),
    'limit_may_be_poison': (IR.replace('i64 noundef %lim', 'i64 %lim'), 0),
    'wraps_to_one': (IR.replace('select i1 %w, i64 0,', 'select i1 %w, i64 1,'), 0),
    'size_optimized': (IR.replace('i64 %n) {', 'i64 %n) optsize {'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('ring-index-bounds', ir)
    assert got == want, (name, got)
    assert ('br i1 true, label %latch, label %trap' in module) == bool(want), (name, module)
    print('PASS', name)

# Wherever the original does not trap, the folded loop writes the same slots.
with tempfile.TemporaryDirectory(prefix='ring-index-bounds-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    (d / 'input.ll').write_text(IR)
    (d / 'optimized.ll').write_text(run_pass('ring-index-bounds', IR)[1].replace('@f(', '@g('))
    (d / 'main.c').write_text(r"""#include <stdint.h>
#include <string.h>
extern int64_t f(int64_t *, int64_t, int64_t);
extern int64_t g(int64_t *, int64_t, int64_t);
int main(void) {
  for (int64_t lim = -2; lim < 20; ++lim) for (int64_t n = 0; n < 40; ++n) {
    int64_t expected[16], actual[16];
    memset(expected, 0, sizeof expected); memset(actual, 0, sizeof actual);
    f(expected, lim, n); g(actual, lim, n);
    if (memcmp(expected, actual, sizeof expected) != 0) return 1;
  }
  return 0;
}
""")
    run([bindir / 'clang', '-O1', '-Wno-override-module', d / 'input.ll', d / 'optimized.ll', d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
