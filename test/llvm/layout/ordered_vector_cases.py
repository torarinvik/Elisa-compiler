"""IR shapes for the ordered conversions and paired counters, shared by their test.

`sum_of_conversions` loads eight consecutive i64s, converts each to double and adds the
first six (or all eight) in order; the casts rewrite loads them in pairs, converts them as
one vector and reduces the first six with an ordered `llvm.vector.reduce.fadd`.
`paired_loop` counts two zero-based i64 counters, one stepping by 1. Each case maps to
the count the C++ passes reported for the same input: the casts and counters count
changed functions, the module entry 0, 1 or 2.
"""
DARWIN = 'target triple = "arm64-apple-macosx14.0.0"\n'
LINUX = 'target triple = "aarch64-unknown-linux-gnu"\n'
X86 = 'target triple = "x86_64-apple-macosx14.0.0"\n'


def sum_of_conversions(name='sum8', attributes='', element=lambda index: index, load=lambda index: 'load', fadd=lambda index: 'fadd',
                       operands=None, between=lambda index: '', after='', count=8, total=8, tail=''):
    body = f'define double @{name}(ptr %p) {attributes} {{\nentry:\n'
    for index in range(count):
        body += f'  %p{index} = getelementptr i64, ptr %p, i64 {element(index)}\n'
        body += f'  %a{index} = {load(index)} i64, ptr %p{index}, align 8\n'
        body += between(index)
        body += f'  %x{index} = sitofp i64 %a{index} to double\n'
        if 0 < index < total:
            left = '%x0' if index == 1 else f'%s{index - 1}'
            pair = (left, f'%x{index}') if operands is None else operands(index, left)
            body += f'  %s{index} = {fadd(index)} double {pair[0]}, {pair[1]}\n'
    result = f'%s{total - 1}' if total > 1 else '%x0'
    return body + after + tail + f'  ret double {result}\n}}\n'


def with_branch_block(loads=3, extra=''):
    lines = ''.join(f'  %q{index}.slot = getelementptr i64, ptr %p, i64 {8 + index}\n  %q{index} = load i64, ptr %q{index}.slot, align 8\n' for index in range(loads))
    return f'  br label %check\ncheck:\n{lines}{extra}  %flag = icmp eq i64 %q0, 0\n  br i1 %flag, label %done, label %done\ndone:\n'


def paired_loop(name='count', a_initial='0', b_initial='0', a_step='1', b_step='%stride', operation='add', width='i64', prelude='', in_loop='',
                result='%sum', extra_phi='', latch_block=True):
    latch_label = 'latch' if latch_block else 'loop'
    body_end = '  br label %latch\nlatch:\n' if latch_block else ''
    return f'''define {width} @{name}({width} %n, {width} %stride, {width} %other) {{
entry:
{prelude}  br label %loop
loop:
  %a = phi {width} [ {a_initial}, %entry ], [ %an, %{latch_label} ]
  %b = phi {width} [ {b_initial}, %entry ], [ %bn, %{latch_label} ]
{extra_phi}  %sum = add {width} %a, %b
{in_loop}{body_end}  %an = {operation} {width} %a, {a_step}
  %bn = add {width} %b, {b_step}
  %cond = icmp ult {width} %an, %n
  br i1 %cond, label %loop, label %exit
exit:
  ret {width} {result}
}}
'''


def nested_pairs():
    return '''define i64 @nested(i64 %n, i64 %stride) {
entry:
  br label %outer
outer:
  %i = phi i64 [ 0, %entry ], [ %in, %outer.latch ]
  %j = phi i64 [ 0, %entry ], [ %jn, %outer.latch ]
  br label %inner
inner:
  %k = phi i64 [ 0, %outer ], [ %kn, %inner.latch ]
  %m = phi i64 [ 0, %outer ], [ %mn, %inner.latch ]
  %t = add i64 %k, %m
  br label %inner.latch
inner.latch:
  %kn = add i64 %k, 1
  %mn = add i64 %m, %stride
  %inner.cond = icmp ult i64 %kn, %n
  br i1 %inner.cond, label %inner, label %outer.body
outer.body:
  %u = add i64 %i, %j
  br label %outer.latch
outer.latch:
  %in = add i64 %i, 1
  %jn = add i64 %j, 3
  %outer.cond = icmp ult i64 %in, %n
  br i1 %outer.cond, label %outer, label %exit
exit:
  %r = add i64 %t, %u
  ret i64 %r
}
'''


def sibling_pairs():
    first = paired_loop(name='siblings')
    second_loop = '''second:
  %c = phi i64 [ 0, %exit ], [ %cn, %second.latch ]
  %d = phi i64 [ 0, %exit ], [ %dn, %second.latch ]
  %w = add i64 %c, %d
  br label %second.latch
second.latch:
  %cn = add i64 %c, 1
  %dn = add i64 %d, 5
  %second.cond = icmp ult i64 %cn, %n
  br i1 %second.cond, label %second, label %finish
finish:
  %r = add i64 %sum, %w
  ret i64 %r
}
'''
    return first.replace('exit:\n  ret i64 %sum\n}\n', 'exit:\n  br label %second\n' + second_loop)


BASE = sum_of_conversions()
DEBUG_UNIT = '''!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!2}
!0 = distinct !DICompileUnit(language: DW_LANG_C, file: !1, emissionKind: NoDebug)
!1 = !DIFile(filename: "a.c", directory: "/")
!2 = !{i32 2, !"Debug Info Version", i32 3}
'''

CAST_CASES = {
    'eligible': BASE,
    'all-eight-summed': sum_of_conversions(total=8),
    'six-summed': sum_of_conversions(total=6, after='  %y6 = fadd double %x6, %x7\n  %z = fadd double %s5, %y6\n'),
    'two-groups': sum_of_conversions(count=16, total=16),
    'fast-flags': sum_of_conversions(fadd=lambda index: 'fadd fast'),
    'mixed-flags': sum_of_conversions(fadd=lambda index: 'fadd contract' if index == 3 else 'fadd'),
    'first-flag-differs': sum_of_conversions(fadd=lambda index: 'fadd nnan' if index == 1 else 'fadd'),
    'volatile': sum_of_conversions(load=lambda index: 'load volatile' if index == 1 else 'load'),
    'atomic': BASE.replace('%a2 = load i64, ptr %p2, align 8', '%a2 = load atomic i64, ptr %p2 unordered, align 8'),
    'strictfp': sum_of_conversions(attributes='strictfp'),
    'optsize': sum_of_conversions(attributes='optsize'),
    'minsize': sum_of_conversions(attributes='minsize'),
    'optnone': sum_of_conversions(attributes='noinline optnone'),
    'sanitize-address': sum_of_conversions(attributes='sanitize_address'),
    'sanitize-thread': sum_of_conversions(attributes='sanitize_thread'),
    'store-between': sum_of_conversions(between=lambda index: '  store i64 4, ptr %p0, align 8\n' if index == 3 else ''),
    'call-between': sum_of_conversions(between=lambda index: '  call void @llvm.donothing()\n' if index == 3 else '') + 'declare void @llvm.donothing()\n',
    'nonadjacent': sum_of_conversions(element=lambda index: 12 if index == 1 else index),
    'reversed-pair': sum_of_conversions(element=lambda index: {0: 1, 1: 0}.get(index, index)),
    'shared-base-offset': sum_of_conversions(element=lambda index: index + 3),
    'swapped-operands': sum_of_conversions(operands=lambda index, left: (f'%x{index}', left) if index == 2 else (left, f'%x{index}')),
    'early-use': sum_of_conversions(between=lambda index: '  %early = fmul double %x1, 2.0\n' if index == 4 else ''),
    'seven-conversions': sum_of_conversions(count=7, total=7),
    'i32-sources': BASE.replace('i64, ptr', 'i32, ptr').replace('sitofp i64', 'sitofp i32').replace('getelementptr i64', 'getelementptr i32'),
    'float-results': BASE.replace('to double', 'to float').replace('double %', 'float %').replace('define double', 'define float').replace('ret double', 'ret float'),
    'branch-pairing': sum_of_conversions(tail=with_branch_block()),
    'branch-two-loads': sum_of_conversions(tail=with_branch_block(loads=2)),
    'branch-store': sum_of_conversions(tail=with_branch_block(extra='  store i64 1, ptr %p, align 8\n')),
}
CAST_CASES = {name: DARWIN + ir for name, ir in CAST_CASES.items()}

COUNTER_CASES = {
    'pair': paired_loop(),
    'pair-b-steps-one': paired_loop(a_step='%stride', b_step='1'),
    'both-one': paired_loop(b_step='1'),
    'nonzero-initial': paired_loop(b_initial='1'),
    'variant-stride': paired_loop(b_step='%sum'),
    'no-unit-step': paired_loop(a_step='%other'),
    'instruction-step': paired_loop(prelude='  %scaled = mul i64 %stride, 3\n', b_step='%scaled'),
    'loop-defined-step': paired_loop(in_loop='  %local = mul i64 %stride, 3\n', b_step='%local'),
    'subtracting': paired_loop(operation='sub'),
    'i32-counters': paired_loop(width='i32'),
    'third-counter-not-in-latch': paired_loop(extra_phi='  %c = phi i64 [ 0, %entry ], [ %cn, %latch ]\n', in_loop='  %cn = add i64 %c, 1\n'),
    'three-counters': paired_loop(extra_phi='  %c = phi i64 [ 0, %entry ], [ %cn, %latch ]\n').replace('  %bn = add i64 %b, %stride\n', '  %bn = add i64 %b, %stride\n  %cn = add i64 %c, 1\n'),
    'phi-user': paired_loop(extra_phi='  %held = phi i64 [ 0, %entry ], [ %a, %latch ]\n'),
    'single-block-loop': paired_loop(latch_block=False),
    'nested': nested_pairs(),
    'siblings': sibling_pairs(),
}
COUNTER_CASES = {name: DARWIN + ir for name, ir in COUNTER_CASES.items()}

ENTRY_LOOP = paired_loop(name='count')
ENTRY_CASES = {
    'entry-eligible': DARWIN + BASE,
    'entry-with-loop': DARWIN + BASE.replace('  ret double %s7\n}\n', '  br label %loop\nloop:\n  %i = phi i64 [ 0, %entry ], [ %in, %latch ]\n  %j = phi i64 [ 0, %entry ], [ %jn, %latch ]\n  br label %latch\nlatch:\n  %in = add i64 %i, 1\n  %jn = add i64 %j, %a0\n  %c = icmp ult i64 %in, %a1\n  br i1 %c, label %loop, label %exit\nexit:\n  %jd = sitofp i64 %jn to double\n  %r = fadd double %s7, %jd\n  ret double %r\n}\n'),
    'entry-linux': LINUX + BASE,
    'entry-two-functions': DARWIN + BASE + ENTRY_LOOP,
    'entry-declaration-only-extra': DARWIN + BASE + 'declare void @external()\n',
    'entry-ineligible': DARWIN + sum_of_conversions(attributes='strictfp'),
    'entry-debug-unit': DARWIN + BASE + DEBUG_UNIT,
    'entry-large': DARWIN + sum_of_conversions(tail=''.join(f'  %pad{index} = add i64 %a0, {index}\n' for index in range(1990))),
}

# Entry cases run with the `generic` CPU: `apple-m1` is not an x86 processor.
GENERIC_ENTRY_CASES = {'entry-x86': X86 + BASE}

# Per case: the count, then the `llvm.vector.reduce.fadd` calls, `<2 x i64>` phis and
# `<2 x i64>` loads in the result, as the C++ passes left them. `entry-no-target` is
# `entry-eligible` run without a target machine.
EXPECTED = {
    'all-eight-summed': (1, 1, 0, 4),
    'atomic': (0, 0, 0, 0),
    'branch-pairing': (1, 1, 0, 5),
    'branch-store': (1, 1, 0, 4),
    'branch-two-loads': (1, 1, 0, 4),
    'call-between': (1, 1, 0, 4),
    'early-use': (0, 0, 0, 0),
    'eligible': (1, 1, 0, 4),
    'fast-flags': (1, 1, 0, 4),
    'first-flag-differs': (0, 0, 0, 0),
    'float-results': (0, 0, 0, 0),
    'i32-sources': (0, 0, 0, 0),
    'minsize': (0, 0, 0, 0),
    'mixed-flags': (0, 0, 0, 0),
    'nonadjacent': (0, 0, 0, 0),
    'optnone': (0, 0, 0, 0),
    'optsize': (0, 0, 0, 0),
    'reversed-pair': (0, 0, 0, 0),
    'sanitize-address': (0, 0, 0, 0),
    'sanitize-thread': (0, 0, 0, 0),
    'seven-conversions': (0, 0, 0, 0),
    'shared-base-offset': (1, 1, 0, 4),
    'six-summed': (1, 1, 0, 4),
    'store-between': (0, 0, 0, 0),
    'strictfp': (0, 0, 0, 0),
    'swapped-operands': (0, 0, 0, 0),
    'two-groups': (1, 1, 0, 4),
    'volatile': (0, 0, 0, 0),
    'both-one': (1, 0, 1, 0),
    'i32-counters': (0, 0, 0, 0),
    'instruction-step': (1, 0, 1, 0),
    'loop-defined-step': (0, 0, 0, 0),
    'nested': (1, 0, 2, 0),
    'no-unit-step': (0, 0, 0, 0),
    'nonzero-initial': (0, 0, 0, 0),
    'pair-b-steps-one': (1, 0, 1, 0),
    'pair': (1, 0, 1, 0),
    'phi-user': (0, 0, 0, 0),
    'siblings': (1, 0, 2, 0),
    'single-block-loop': (0, 0, 0, 0),
    'subtracting': (0, 0, 0, 0),
    'third-counter-not-in-latch': (1, 0, 1, 0),
    'three-counters': (0, 0, 0, 0),
    'variant-stride': (0, 0, 0, 0),
    'entry-debug-unit': (0, 0, 0, 0),
    'entry-declaration-only-extra': (1, 1, 0, 4),
    'entry-eligible': (1, 1, 0, 4),
    'entry-ineligible': (0, 0, 0, 0),
    'entry-large': (0, 0, 0, 0),
    'entry-linux': (1, 1, 0, 4),
    'entry-two-functions': (0, 0, 0, 0),
    'entry-with-loop': (1, 1, 1, 4),
    'entry-x86': (0, 0, 0, 0),
    'entry-no-target': (0, 0, 0, 0),
}
