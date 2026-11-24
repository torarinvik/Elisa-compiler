#!/usr/bin/env python3
"""Check the AArch64 range-check tuning against its shapes.

- `(x + bias) <u limit` with a register-sized bias becomes `(x + lower') >u ~limit` when the
  new subtraction fits a 12-bit immediate and the new limit fits 32 bits.
- With CSSC, the symmetric check `x - (B + 1) <u ~(2B)` becomes `abs(x) >u B`, except in
  loops holding four or more such checks.
- On Apple M5, a function whose loop clamps a running extremum gets CSSC turned off.
The pass needs a target machine: each case passes a CPU and features to `elisac llvm-pass`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass_with_target

LINUX = 'aarch64-unknown-linux-gnu'
MAC = 'arm64-apple-macosx14.0.0'


def symmetric(triple=LINUX, attributes='nounwind', flags='', checks=1, in_loop=False):
    """`x - 101 <u -201` (accepting [-100, 100]) branching to a trap, CHECKS times."""
    body = ''.join(f' %s{k} = add {flags}i64 %x{k}, -101\n %c{k} = icmp ult i64 %s{k}, -201\n'
                   f' br i1 %c{k}, label %ok{k}, label %bad\nok{k}:\n' for k in range(checks))
    parameters = ', '.join(f'i64 %x{k}' for k in range(checks))
    if in_loop:
        return f'''target triple = "{triple}"
define i64 @f(i64 %n, {parameters}) {attributes} {{
entry: br label %loop
loop:
 %i = phi i64 [0, %entry], [%next, %ok{checks - 1}]
{body} %next = add i64 %i, 1
 %done = icmp eq i64 %next, %n
 br i1 %done, label %exit, label %loop
exit: ret i64 0
bad: ret i64 1
}}
'''
    return f'''target triple = "{triple}"
define i64 @f({parameters}) {attributes} {{
entry:
{body} ret i64 0
bad: ret i64 1
}}
'''


def immediate_bias(guarded=False, bias=-5000, limit=-4000):
    """`(x + bias) <u limit`, optionally as the second test of a `select c, true, d` guard."""
    test = f' %s = add i64 %x, {bias}\n %c = icmp ult i64 %s, {limit}\n'
    if guarded:
        test += ' %e = icmp eq i64 %y, 7\n %g = select i1 %e, i1 true, i1 %c\n br i1 %g, label %a, label %b\n'
    else:
        test += ' br i1 %c, label %a, label %b\n'
    return f'''target triple = "{LINUX}"
define i64 @f(i64 %x, i64 %y) nounwind {{
entry:
{test}a: ret i64 0
b: ret i64 1
}}
'''


def running_maximum(triple=MAC, attributes='nounwind'):
    """A loop keeping `m = umax(m, x)` clamped by `umin(m, cap)` in the same block."""
    return f'''target triple = "{triple}"
declare i32 @llvm.umax.i32(i32, i32)
declare i32 @llvm.umin.i32(i32, i32)
define i32 @f(ptr %p, i64 %n, i32 %cap) {attributes} {{
entry: br label %loop
loop:
 %i = phi i64 [0, %entry], [%next, %loop]
 %m = phi i32 [0, %entry], [%running, %loop]
 %c = phi i32 [0, %entry], [%clamped, %loop]
 %a = getelementptr i32, ptr %p, i64 %i
 %x = load i32, ptr %a
 %running = call i32 @llvm.umax.i32(i32 %m, i32 %x)
 %clamped = call i32 @llvm.umin.i32(i32 %running, i32 %cap)
 %next = add i64 %i, 1
 %done = icmp eq i64 %next, %n
 br i1 %done, label %exit, label %loop
exit:
 %r = add i32 %clamped, %running
 ret i32 %r
}}
'''


CSSC = ('generic', '+cssc')
PLAIN = ('generic', '')
# name: (module, cpu and features, changes, expected text, unexpected text)
CASES = {
    'abs_fold': (symmetric(), CSSC, 1, '@llvm.abs.i64(i64 %x0, i1 false)', 'add i64 %x0, -101'),
    'abs_fold_value': (symmetric(), CSSC, 1, 'icmp ugt i64 %range.abs, 100', 'icmp ult'),
    'no_cssc': (symmetric(), PLAIN, 0, 'icmp ult i64 %s0, -201', 'llvm.abs'),
    'nsw_add': (symmetric(flags='nsw '), CSSC, 0, 'icmp ult i64 %s0, -201', 'llvm.abs'),
    'size_optimized': (symmetric(attributes='nounwind optsize'), CSSC, 0, 'icmp ult', 'llvm.abs'),
    'own_target_cpu': (symmetric(attributes='nounwind "target-cpu"="generic"'), CSSC, 0, 'icmp ult', 'llvm.abs'),
    'x86': (symmetric(triple='x86_64-unknown-linux-gnu'), ('generic', ''), 0, 'icmp ult', 'llvm.abs'),
    'three_in_loop': (symmetric(checks=3, in_loop=True), CSSC, 3, 'range.abs', 'icmp ult i64 %s'),
    'wide_scan': (symmetric(checks=4, in_loop=True), CSSC, 0, 'icmp ult i64 %s3, -201', 'llvm.abs'),
    'four_outside_loops': (symmetric(checks=4), CSSC, 4, 'range.abs', 'icmp ult i64 %s'),
    'immediate_bias': (immediate_bias(), PLAIN, 1, 'icmp ugt i64 %s, 3999', 'icmp ult'),
    'immediate_bias_add': (immediate_bias(), PLAIN, 1, 'add i64 %x, -1000', '-5000'),
    'guarded_bias': (immediate_bias(guarded=True), PLAIN, 1, 'icmp ugt i64 %s, 3999', 'icmp ult'),
    'small_bias': (immediate_bias(bias=-4000, limit=-3000), PLAIN, 0, 'icmp ult i64 %s, -3000', 'icmp ugt'),
    'shifted_bias': (immediate_bias(bias=-8192, limit=-7000), PLAIN, 0, 'icmp ult i64 %s, -7000', 'icmp ugt'),
    'wide_new_limit': (immediate_bias(bias=-9000000000, limit=-8999999000), PLAIN, 0, 'icmp ult', 'icmp ugt'),
    'm5_extrema': (running_maximum(), ('apple-m5', '+neon,+cssc'), 1, '"target-features"="+neon,-cssc"', 'llvm.abs'),
    'm5_default_features': (running_maximum(), ('apple-m5', ''), 1, '"target-features"="-cssc"', 'llvm.abs'),
    'm4_extrema': (running_maximum(), ('apple-m4', '+cssc'), 0, '@llvm.umin.i32', 'target-features'),
    'linux_extrema': (running_maximum(triple=LINUX), ('apple-m5', '+cssc'), 0, '@llvm.umin.i32', 'target-features'),
}

if __name__ == '__main__':
    for name, (ir, (cpu, features), want, expected, unexpected) in CASES.items():
        got, module = run_pass_with_target('cssc-range-checks', ir, cpu, features)
        assert got == want, (name, got, module)
        assert expected in module, (name, expected, module)
        assert unexpected not in module, (name, unexpected, module)
        print('PASS', name)
    got, module = run_pass_with_target('cssc-range-checks', symmetric(), None, None)
    assert got == 0 and 'llvm.abs' not in module, ('no_target_machine', got)
    print('PASS no_target_machine')
