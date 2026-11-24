#!/usr/bin/env python3
"""Check the trap exit edges against their shape and by execution.

On AArch64, a `call @llvm.trap(); unreachable` block becomes a cold `brk #0x1` and a branch
to the function's single return block, so shrink-wrapping sees one exit. The return block's
phis take poison from the new edge, and a trap is connected only when every definition the
return block uses from outside it also dominates the trap.
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
declare void @llvm.trap()
define i64 @f(i64 %n, ptr %p) {
entry:
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%i2, %ok]
  %bad = icmp uge i64 %i, 100
  br i1 %bad, label %trap, label %ok
ok:
  %v = load i64, ptr %p
  %i2 = add i64 %i, 1
  %again = icmp ult i64 %i2, %n
  br i1 %again, label %loop, label %exit
trap:
  call void @llvm.trap()
  unreachable
exit:
  %r = phi i64 [%v, %ok]
  %out = add i64 %r, %i
  ret i64 %out
}
'''
CASES = {
    'header_value': (IR, 1),
    'body_value': (IR.replace('add i64 %r, %i', 'add i64 %r, %v'), 0),
    'second_return': (IR.replace('  br i1 %bad, label %trap, label %ok', '  %five = icmp eq i64 %i, 5\n  br i1 %five, label %early, label %check\ncheck:\n  br i1 %bad, label %trap, label %ok\nearly:\n  ret i64 5'), 0),
    'not_trap': (IR.replace('@llvm.trap', '@abort'), 0),
    'optimization_disabled': (IR.replace('ptr %p) {', 'ptr %p) noinline optnone {'), 0),
    'non_arm': (IR.replace('arm64-apple-darwin', 'x86_64-unknown-linux-gnu'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('trap-exit-edges', ir)
    assert got == want, (name, got)
    connected = 'brk #0x1' in module
    assert connected == bool(want), (name, module)
    if connected:
        assert '!prof' in module and 'i32 1, i32 1048575' in module, (name, module)
        assert 'unreachable' not in module and '[ poison, %trap ]' in module, (name, module)
    print('PASS', name)

# Connected, the function returns the same values on inputs that never trap.
with tempfile.TemporaryDirectory(prefix='trap-exit-edges-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    (d / 'original.ll').write_text(IR)
    (d / 'connected.ll').write_text(run_pass('trap-exit-edges', IR)[1].replace('@f(', '@g('))
    (d / 'main.c').write_text(r"""#include <stdint.h>
extern uint64_t f(uint64_t, uint64_t *), g(uint64_t, uint64_t *);
int main(void) {
  uint64_t value = 41;
  for (uint64_t n = 0; n <= 100; ++n) {
    value = value * 6364136223846793005ull + 1442695040888963407ull;
    if (f(n, &value) != g(n, &value)) return 1;
  }
  return 0;
}
""")
    run([bindir / 'clang', '-O1', '-Wno-override-module', d / 'original.ll', d / 'connected.ll', d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
