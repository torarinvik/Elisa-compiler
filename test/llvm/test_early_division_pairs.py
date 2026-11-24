#!/usr/bin/env python3
"""Check the early quotient/remainder pairing on AArch64.

A function with a remainder gets LLVM's div-rem-pairs, which on AArch64 rewrites a
remainder next to its quotient as `x - (x / y) * y`, unless all its remainders are
scalar `urem`s by a runtime divisor. Optnone functions and other targets are left
alone; off AArch64 the pass reports 0 so that the caller pairs the whole module.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass_with_target

AARCH64 = 'target datalayout = "e-m:e-i8:8:32-i16:16:32-i64:64-i128:128-n32:64-S128-Fn32"\ntarget triple = "aarch64-unknown-linux-gnu"\n'
X86 = 'target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"\ntarget triple = "x86_64-unknown-linux-gnu"\n'


def function(body, attributes='nounwind', element='i64'):
    return f'''define {element} @f({element} %x, {element} %y) {attributes} {{
entry:
{body}}}
'''


SIGNED = '  %q = sdiv i64 %x, %y\n  %r = srem i64 %x, %y\n  %s = add i64 %q, %r\n  ret i64 %s\n'
RUNTIME_UNSIGNED = '  %q = udiv i64 %x, %y\n  %r = urem i64 %x, %y\n  %s = add i64 %q, %r\n  ret i64 %s\n'
MIXED = '  %q = udiv i64 %x, %y\n  %r = urem i64 %x, %y\n  %t = srem i64 %x, 3\n  %u = sdiv i64 %x, 3\n  %s = add i64 %q, %r\n  %v = add i64 %s, %t\n  %w = add i64 %v, %u\n  ret i64 %w\n'
CONSTANT = '  %q = udiv i64 %x, 7\n  %r = urem i64 %x, 7\n  %s = add i64 %q, %r\n  ret i64 %s\n'
VECTOR = '  %q = udiv <2 x i64> %x, %y\n  %r = urem <2 x i64> %x, %y\n  %s = add <2 x i64> %q, %r\n  ret <2 x i64> %s\n'

# name: (module, count, remainder instructions left)
CASES = {
    'signed_pair': (AARCH64 + function(SIGNED), 1, 0),
    'runtime_unsigned_only': (AARCH64 + function(RUNTIME_UNSIGNED), 1, 1),
    'runtime_unsigned_with_signed': (AARCH64 + function(MIXED), 1, 0),
    'constant_divisor': (AARCH64 + function(CONSTANT), 1, 0),
    'vector_remainder': (AARCH64 + function(VECTOR, element='<2 x i64>'), 1, 0),
    'optnone': (AARCH64 + function(SIGNED, attributes='noinline nounwind optnone'), 1, 1),
    'x86': (X86 + function(SIGNED), 0, 1),
}

if __name__ == '__main__':
    for name, (ir, want_count, want_remainders) in CASES.items():
        count, module = run_pass_with_target('early-division-pairs', ir, 'generic', None)
        assert count == want_count, (name, count, module)
        remainders = module.count(' = urem ') + module.count(' = srem ')
        assert remainders == want_remainders, (name, remainders, module)
        print('PASS', name)
