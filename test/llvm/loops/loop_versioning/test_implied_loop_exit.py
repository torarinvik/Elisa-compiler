#!/usr/bin/env python3
"""Check implied loop-exit threading against its shape and by execution.

A jump into a side-effect-free branch block whose condition the guard above the jump
already decides goes straight to the decided successor: a latch `i.next == n` reached
from a block guarded by `i.next < n` jumps back to the loop header.
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
define i64 @f(i64 %n, ptr %a) {
entry:
  br label %header
header:
  %i = phi i64 [0, %entry], [%i.next, %latch]
  %i.next = add nuw i64 %i, 1
  %g = icmp ult i64 %i.next, %n
  br i1 %g, label %body, label %exit
body:
  %p = getelementptr i64, ptr %a, i64 %i
  store i64 %i, ptr %p
  br label %latch
latch:
  %c = icmp eq i64 %i.next, %n
  br i1 %c, label %exit, label %header
exit:
  %r = phi i64 [0, %header], [1, %latch]
  ret i64 %r
}
'''
CASES = {
    'threaded': (IR, 1),
    'undecided': (IR.replace('icmp ult i64 %i.next, %n', 'icmp ne i64 %i.next, %n').replace('icmp eq i64 %i.next, %n', 'icmp ult i64 %i.next, %n'), 0),
    'side_effect': (IR.replace('latch:\n  %c', 'latch:\n  store i64 0, ptr %a\n  %c'), 0),
    'debug_info': (IR + '!llvm.dbg.cu = !{}\n!llvm.module.flags = !{!0}\n!0 = !{i32 2, !"Debug Info Version", i32 3}\n', 0),
    'size_optimized': (IR.replace('ptr %a) {', 'ptr %a) optsize {'), 0),
    'non_arm': (IR.replace('arm64-apple-darwin', 'x86_64-unknown-linux-gnu'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('implied-loop-exits', ir)
    assert got == want, (name, got)
    body = module.split('body:', 1)[1].split('latch:', 1)[0]
    assert ('br label %header' in body) == bool(want), (name, module)
    print('PASS', name)

# The threaded loop stores and returns the same values for every trip count.
with tempfile.TemporaryDirectory(prefix='implied-loop-exit-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    (d / 'input.ll').write_text(IR)
    (d / 'optimized.ll').write_text(run_pass('implied-loop-exits', IR)[1].replace('@f(', '@g('))
    (d / 'main.c').write_text(r"""#include <stdint.h>
#include <string.h>
extern int64_t f(int64_t, int64_t *);
extern int64_t g(int64_t, int64_t *);
int main(void) {
  for (int64_t n = 0; n < 200; ++n) {
    int64_t expected[256], actual[256];
    memset(expected, 0x5a, sizeof expected); memset(actual, 0x5a, sizeof actual);
    if (f(n, expected) != g(n, actual) || memcmp(expected, actual, sizeof expected) != 0) return 1;
  }
  return 0;
}
""")
    run([bindir / 'clang', '-O1', '-Wno-override-module', d / 'input.ll', d / 'optimized.ll', d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
