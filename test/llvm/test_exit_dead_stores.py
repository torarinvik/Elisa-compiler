#!/usr/bin/env python3
"""Check the exit dead-store removal against its shape and by execution.

A simple store is dead when every object its address may point into is a local alloca and
no instruction that may read memory can run after it: the object dies at the return.
Lifetime markers do not count as reads.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=120)


def program(after='', exit_read='', volatile='', target='%cell'):
    return f'''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
target triple = "arm64-apple-darwin"
@g = global i64 0
declare void @llvm.lifetime.start.p0(ptr)
declare void @llvm.lifetime.end.p0(ptr)
define i64 @f(i64 %i, i64 %v, i1 %c) {{
entry:
  %cells = alloca [8 x i64]
  %spare = alloca [8 x i64]
  call void @llvm.lifetime.start.p0(ptr %cells)
  %first = getelementptr [8 x i64], ptr %cells, i64 0, i64 0
  store i64 5, ptr %first
  %read = load i64, ptr %first
  br i1 %c, label %left, label %right
left:
  %l = getelementptr [8 x i64], ptr %cells, i64 0, i64 %i
  br label %merge
right:
  %r = getelementptr [8 x i64], ptr %spare, i64 0, i64 2
  br label %merge
merge:
  %cell = phi ptr [%l, %left], [%r, %right]
  store {volatile}i64 %v, ptr {target}
{after}  call void @llvm.lifetime.end.p0(ptr %cells)
  br label %exit
exit:
{exit_read}  ret i64 %read
}}
'''


BASE = program()
CASES = {
    'phi_over_cells': (BASE, 1),
    'read_after': (program(after='  %late = load i64, ptr %first\n'), 0),
    'read_in_exit': (program(exit_read='  %late = load i64, ptr %first\n'), 0),
    'volatile': (program(volatile='volatile '), 0),
    'global_object': (program(target='@g'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('exit-dead-stores', ir)
    assert got == want, (name, got)
    assert ('store i64 %v' not in module and 'store volatile i64 %v' not in module) == bool(want), (name, module)
    print('PASS', name)

with tempfile.TemporaryDirectory(prefix='exit-dead-stores-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    (d / 'original.ll').write_text(BASE)
    (d / 'removed.ll').write_text(run_pass('exit-dead-stores', BASE)[1].replace('@f(', '@h(').replace('@g ', '@g2 ').replace('@g\n', '@g2\n'))
    (d / 'main.c').write_text(r"""#include <stdbool.h>
#include <stdint.h>
extern int64_t f(int64_t, int64_t, bool), h(int64_t, int64_t, bool);
int main(void) {
  for (int64_t i = 0; i < 8; ++i)
    for (int c = 0; c < 2; ++c)
      if (f(i, 40 + i, c) != h(i, 40 + i, c)) return 1;
  return 0;
}
""")
    run([bindir / 'clang', '-O0', '-Wno-override-module', d / 'original.ll', d / 'removed.ll', d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
