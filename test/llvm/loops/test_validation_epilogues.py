#!/usr/bin/env python3
"""Check the validation-epilogue specialization.

After `assume((n & 15) != 0)`, a chain of eight load-and-guard steps, each followed by a
`rem == k` test leaving to one exit, gets clones of the eight steps without the tests,
taken when the remainder is eight. A different mask, a missing assume, a shorter chain,
a phi in the exit, or a non-AArch64 target leaves it alone.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elisa_llvm_pass import run_pass

ARM64 = 'target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"\ntarget triple = "arm64-apple-macosx14.0.0"\n'
LINUX = 'target datalayout = "e-m:e-i64:64-i128:128-n32:64-S128"\ntarget triple = "aarch64-unknown-linux-gnu"\n'
X86 = 'target datalayout = "e-m:e-i64:64-i128:128-n8:16:32:64-S128"\ntarget triple = "x86_64-unknown-linux-gnu"\n'


def chain(mask=15, assume=True, steps=8, exit_phi=False, target=ARM64):
    assumption = '  %nonzero = icmp ne i64 %rem, 0\n  call void @llvm.assume(i1 %nonzero)\n' if assume else ''
    blocks = []
    for k in range(1, steps + 1):
        blocks.append(f'''step{k}:
  %slot{k} = getelementptr i8, ptr %a, i64 {k - 1}
  %byte{k} = load i8, ptr %slot{k}, align 1
  %bad{k} = icmp ugt i8 %byte{k}, 127
  br i1 %bad{k}, label %fail, label %check{k}
check{k}:
  %is{k} = icmp eq i64 %rem, {k}
  br i1 %is{k}, label %done, label %{"step" + str(k + 1) if k < steps else "rest"}
''')
    done = '  %flag = phi i1 ' + ', '.join(f'[ true, %check{k} ]' for k in range(1, steps + 1)) + '\n  ret i1 %flag\n' if exit_phi else '  ret i1 true\n'
    return target + f'''declare void @llvm.assume(i1)
define i1 @valid(ptr %a, i64 %n) nounwind {{
entry:
  %rem = and i64 %n, {mask}
{assumption}  br label %step1
{"".join(blocks)}done:
{done}fail:
  ret i1 false
rest:
  ret i1 true
}}
'''


# name: (module, changes)
CASES = {
    'darwin': (chain(), 1),
    'linux': (chain(target=LINUX), 1),
    'mask_seven': (chain(mask=7), 0),
    'no_assume': (chain(assume=False), 0),
    'seven_steps': (chain(steps=7), 0),
    'exit_phi': (chain(exit_phi=True), 0),
    'x86': (chain(target=X86), 0),
}

if __name__ == '__main__':
    for name, (ir, want) in CASES.items():
        got, module = run_pass('validation-epilogues', ir)
        assert got == want, (name, got, module)
        assert ('step1.fast8' in module) == bool(want), (name, module)
        print('PASS', name)
