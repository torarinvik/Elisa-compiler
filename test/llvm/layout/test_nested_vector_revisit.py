#!/usr/bin/env python3
"""Check the late nested-vector revisit: its bounded eligibility and the macOS unroll request.

Small optimized AArch64 modules with a vector load inside a nested loop get a second O3
pipeline. On macOS a single-block vectorized recurrence over two-lane pairs, with four
such loads and stores, first has its runtime-unroll suppression replaced by an unroll
count of two.
"""
import os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elisa_llvm_pass import run_pass

TRIPLE = os.environ.get('ELISA_TEST_TRIPLE', 'arm64-apple-darwin')
UNROLL_COUNT = '!{!"llvm.loop.unroll.count", i32 2}'

NESTED = '''target triple = "TRIPLE"
define void @f(ptr %p, i64 %n) nounwind {
entry: br label %outer
outer:
 %i = phi i64 [0, %entry], [%next, %outer_latch]
 br label %inner
inner:
 %j = phi i64 [0, %outer], [%jnext, %inner]
 %v = load <2 x i64>, ptr %p, align 8
 %jnext = add i64 %j, 1
 %jc = icmp ult i64 %jnext, %n
 br i1 %jc, label %inner, label %outer_latch
outer_latch:
 %next = add i64 %i, 1
 %ic = icmp ult i64 %next, %n
 br i1 %ic, label %outer, label %exit
exit: ret void
}
'''.replace('TRIPLE', TRIPLE)


def recurrence(loads=4, store='store', properties='!1, !2', triple=TRIPLE):
    """A nested single-block recurrence over `<2 x i64>` pairs with LOADS loads."""
    body = ''.join(f' %a{k} = getelementptr <2 x i64>, ptr %p, i64 {k}\n' for k in range(loads))
    body += ''.join(f' %l{k} = load <2 x i64>, ptr %a{k}, align 8\n' for k in range(loads))
    body += ' %sh = shufflevector <2 x i64> %l0, <2 x i64> %acc, <2 x i32> <i32 1, i32 2>\n'
    body += ''.join(f' %b{k} = getelementptr <2 x i64>, ptr %q, i64 {k}\n {store} <2 x i64> %sh, ptr %b{k}, align 8\n'
                    for k in range(4))
    return f'''target triple = "{triple}"
define void @f(ptr %p, ptr %q, i64 %n) nounwind {{
entry: br label %outer
outer:
 %i = phi i64 [0, %entry], [%next, %outer_latch]
 br label %inner
inner:
 %j = phi i64 [0, %outer], [%jnext, %inner]
 %acc = phi <2 x i64> [zeroinitializer, %outer], [%sh, %inner]
{body} %jnext = add i64 %j, 1
 %jc = icmp ult i64 %jnext, %n
 br i1 %jc, label %inner, label %outer_latch, !llvm.loop !0
outer_latch:
 %next = add i64 %i, 1
 %ic = icmp ult i64 %next, %n
 br i1 %ic, label %outer, label %exit
exit: ret void
}}
!0 = distinct !{{!0, {properties}}}
!1 = !{{!"llvm.loop.isvectorized", i32 1}}
!2 = !{{!"llvm.loop.unroll.runtime.disable"}}
!3 = !{{!"llvm.loop.vectorize.width", i32 2}}
'''


# name: (module, revisit, unroll count requested)
CASES = {
    'nested_vector': (NESTED, 1, False),
    'scalar': (NESTED.replace('load <2 x i64>', 'load i64'), 0, False),
    'non_arm': (NESTED.replace(TRIPLE, 'x86_64-unknown-linux-gnu'), 0, False),
    'sanitized': (NESTED.replace('nounwind {', 'nounwind sanitize_address {'), 0, False),
    'size_opt': (NESTED.replace('nounwind {', 'nounwind optsize {'), 0, False),
    'optnone': (NESTED.replace('nounwind {', 'nounwind noinline optnone {'), 0, False),
    'five_functions': (NESTED + '\n'.join('define void @extra%d() { ret void }' % i for i in range(4)), 0, False),
    'large': (NESTED.replace('exit: ret void', 'exit:\n' + ''.join(' %%t%d = add i64 %%n, %d\n' % (i, i) for i in range(2001)) + ' ret void'), 0, False),
    'debug_info': (NESTED + '!llvm.dbg.cu = !{}\n!llvm.module.flags = !{!9}\n!9 = !{i32 2, !"Debug Info Version", i32 3}\n', 0, False),
    'pair_recurrence': (recurrence(), 1, True),
    'linux_recurrence': (recurrence(triple='aarch64-unknown-linux-gnu'), 1, False),
    'three_loads': (recurrence(loads=3), 1, False),
    'volatile_store': (recurrence(store='store volatile'), 1, False),
    'runtime_unroll_allowed': (recurrence(properties='!1, !3'), 1, False),
    'two_properties_only': (recurrence(properties='!1'), 1, False),
}

if __name__ == '__main__':
    for name, (ir, revisit, unrolled) in CASES.items():
        got, module = run_pass('nested-vector-loops', ir)
        assert got == revisit, (name, got)
        assert (UNROLL_COUNT in module) == unrolled, (name, module)
        if unrolled:
            assert 'llvm.loop.unroll.runtime.disable' not in module, (name, module)
            assert '!"llvm.loop.isvectorized", i32 1' in module, (name, module)
        print('PASS', name)
