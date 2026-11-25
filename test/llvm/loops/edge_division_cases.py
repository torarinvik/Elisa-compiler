"""IR shapes for the AArch64 division reuse, shared by its test.

`edge_division` joins two predecessors, one of which already divides the operands the
join divides; `guarded_shift` lets the other edge shift a frozen, guarded dividend instead.
`joined_quotient` divides in a block whose single predecessor already joins both
quotients. `redundant_factor` and `carried_factor` are factor-removal loops whose entry
divided by the factor; `induction_quotient` divides by a cursor whose latch divides by the
next one. `repeated_joins` repeats `edge_division` to reach the per-function cap of four.
"""
MAC = 'arm64-apple-macosx14.0.0'
def module_text(body, triple=MAC, trailer=''):
    return f'target triple = "{triple}"\ndeclare void @use(i64)\n{body}{trailer}'

def edge_division(opcode='sdiv', left_exact='', join_exact='', right='  br label %join\n', left_extra='', operands='phi', integer='i64', metadata='', third=False, both=False, attrs=''):
    phis = f'  %n = phi {integer} [ %a, %left ], [ %a, %right ]{", [ %a, %third ]" if third else ""}\n  %d = phi {integer} [ %b, %left ], [ %b, %right ]{", [ %b, %third ]" if third else ""}\n' if operands == 'phi' else ''
    n, d = ('%n', '%d') if operands == 'phi' else ('%a', '%b')
    right_division = f'  %rq = {opcode} {integer} %a, %b\n' if both else ''
    third_text = 'third:\n  br label %join\n' if third else ''
    entry = '  br i1 %c, label %left, label %right\n' if not third else '  switch i32 %s, label %left [ i32 1, label %right\n i32 2, label %third ]\n'
    return module_text(f'''define {integer} @f({integer} %a, {integer} %b, i1 %c, i1 %e, i32 %s) {attrs} {{
entry:
{entry}left:
  %q = {opcode} {left_exact}{integer} %a, %b
{left_extra}  br label %join
right:
{right_division}{right}{third_text}join:
{phis}  %r = {opcode} {join_exact}{integer} {n}, {d}{metadata}
  ret {integer} %r
bail:
  ret {integer} 0
}}
''')

def guarded_shift(guard='icmp sgt i64 %fx, -1', dividend='%fx', exact=''):
    return module_text(f'''define i64 @f(i64 %x, i1 %c) {{
entry:
  %fx = freeze i64 %x
  br i1 %c, label %left, label %right
left:
  %q = sdiv {exact}i64 {dividend}, 8
  call void @use(i64 %q)
  br label %join
right:
  %g = {guard}
  br i1 %g, label %join, label %bail
join:
  %r = sdiv {exact}i64 {dividend}, 8
  ret i64 %r
bail:
  ret i64 0
}}
''')

def joined_quotient(right_quotient='  %qb = sdiv i64 %x, %y\n', guard_block=False, guard='icmp samesign ult i64 %fx, 100', exact=''):
    guard_text = f'''guard:
  %g = {guard}
  br i1 %g, label %b, label %other
other:
  ret i64 0
''' if guard_block else ''
    to_second = 'label %guard' if guard_block else 'label %b'
    return module_text(f'''define i64 @f(i64 %v, i64 %y, i1 %c) {{
entry:
  %x = freeze i64 %v
  %fx = freeze i64 %v
  br i1 %c, label %a, {to_second}
a:
  %qa = sdiv {exact}i64 %x, %y
  br label %join
{guard_text}b:
{right_quotient}  br label %join
join:
  %q = phi i64 [ %qa, %a ], [ %qb, %b ]
  %xp = phi i64 [ %x, %a ], [ %x, %b ]
  %yp = phi i64 [ %y, %a ], [ %y, %b ]
  call void @use(i64 %q)
  br label %pre
pre:
  %r = sdiv i64 %xp, %yp
  ret i64 %r
}}
''')

def redundant_factor(second='  %q2 = udiv i64 %n, %f\n', factor='%f', compare='icmp eq i64 %rem, %prod', entry_test='icmp eq i64 %n, %pe'):
    return module_text(f'''define i64 @f(i64 %n, i64 %f, i1 %c) {{
start:
  br i1 %c, label %p1, label %p2
p1:
  %q1 = udiv i64 %n, {factor}
  br label %entry2
p2:
{second}  br label %entry2
entry2:
  %qe = phi i64 [ %q1, %p1 ], [ %q2, %p2 ]
  %pe = mul i64 {factor}, %qe
  %te = {entry_test}
  br i1 %te, label %loop, label %exit
loop:
  %rem = phi i64 [ %n, %entry2 ], [ %div, %loop ]
  %div = udiv i64 %rem, {factor}
  %prod = mul i64 {factor}, %div
  %eq = {compare}
  br i1 %eq, label %loop, label %exit
exit:
  %r = phi i64 [ %n, %entry2 ], [ %rem, %loop ]
  ret i64 %r
}}
''')

def carried_factor(second='  %q2 = udiv i64 %n, %f\n', factor='%f', compare='icmp eq i64 %prod, %rem', product='mul i64 %div, {factor}', extra=''):
    return module_text(f'''define i64 @f(i64 %n, i64 %f, i1 %c) {{
start:
  br i1 %c, label %p1, label %p2
p1:
  %q1 = udiv i64 %n, {factor}
  call void @use(i64 %q1)
  br label %join
p2:
{second}  br label %join
join:
  br label %loop
loop:
  %rem = phi i64 [ %n, %join ], [ %div, %loop ]
  %div = udiv i64 %rem, {factor}
{extra}  %prod = {product.format(factor=factor)}
  %eq = {compare}
  br i1 %eq, label %loop, label %exit
exit:
  ret i64 %rem
}}
''')

def induction_quotient(start='2', guard='icmp samesign sgt i64 %fr, 3', test='icmp sle i64 %next, %lq', order='label %header, label %exit', step='1', latch_div='udiv i64 %fr, %next', dividend='%fr'):
    return module_text(f'''define i64 @f(i64 %x) {{
entry:
  %fr = freeze i64 %x
  %g = {guard}
  br i1 %g, label %header, label %exit
header:
  %cursor = phi i64 [ {start}, %entry ], [ %next, %latch ]
  %acc = phi i64 [ 0, %entry ], [ %acc2, %latch ]
  %q = sdiv i64 {dividend}, %cursor
  %acc2 = add i64 %acc, %q
  br label %latch
latch:
  %next = add i64 %cursor, {step}
  %lq = {latch_div}
  %t = {test}
  br i1 %t, {order}
exit:
  %r = phi i64 [ 0, %entry ], [ %acc2, %latch ]
  ret i64 %r
}}
''')

def repeated_joins(count):
    blocks = []
    for k in range(count):
        successor = f'block{k+1}' if k + 1 < count else 'done'
        blocks.append(f'''block{k}:
  br i1 %c, label %l{k}, label %r{k}
l{k}:
  %q{k} = sdiv i64 %a, %b{k}
  call void @use(i64 %q{k})
  br label %j{k}
r{k}:
  br label %j{k}
j{k}:
  %s{k} = sdiv i64 %a, %b{k}
  call void @use(i64 %s{k})
  br label %{successor}
''')
    params = ', '.join(f'i64 %b{k}' for k in range(count))
    return module_text(f'define void @f(i64 %a, i1 %c, {params}) {{\nentry:\n  br label %block0\n' + ''.join(blocks) + 'done:\n  ret void\n}\n')


REUSED = {
    'carry': 1,
    'carry-large': 0,
    'carry-no-reuse': 0,
    'carry-not-equal': 0,
    'carry-shift': 1,
    'carry-swapped': 1,
    'edge-asan': 0,
    'edge-both': 1,
    'edge-conditional': 1,
    'edge-exact': 1,
    'edge-exact-mismatch': 0,
    'edge-far': 0,
    'edge-i32': 0,
    'edge-linux': 1,
    'edge-metadata': 0,
    'edge-near': 1,
    'edge-optsize': 0,
    'edge-plain-operands': 1,
    'edge-sanitizer-flag': 0,
    'edge-sdiv': 1,
    'edge-three-predecessors': 0,
    'edge-udiv': 1,
    'edge-x86': 0,
    'four-cap': 4,
    'induction': 1,
    'induction-greater': 0,
    'induction-inverted': 1,
    'induction-negative-bound': 0,
    'induction-plain-guard': 0,
    'induction-signed-latch': 1,
    'induction-start-four': 1,
    'induction-start-one': 0,
    'induction-start-three': 0,
    'induction-step-two': 0,
    'induction-swapped': 1,
    'induction-unsigned': 1,
    'joined-exact': 0,
    'joined-sdiv': 1,
    'joined-shift': 1,
    'joined-shift-plain-guard': 0,
    'joined-wrong-divisor': 0,
    'redundant': 1,
    'redundant-shift': 1,
    'redundant-wrong-shift': 0,
    'redundant-wrong-test': 0,
    'shift-exact': 1,
    'shift-maybe-negative': 1,
    'shift-nonnegative': 1,
    'shift-not-frozen': 1,
    'shift-other-operand': 1,
    'three-joins': 3,
}

SHAPES = {
 'edge-sdiv': edge_division(), 'edge-udiv': edge_division(opcode='udiv'), 'edge-exact': edge_division(left_exact='exact ', join_exact='exact '),
 'edge-exact-mismatch': edge_division(left_exact='exact '), 'edge-conditional': edge_division(right='  br i1 %e, label %join, label %bail\n'),
 'edge-plain-operands': edge_division(operands='plain'), 'edge-i32': edge_division(integer='i32'), 'edge-metadata': edge_division(metadata=', !note !0') + '!0 = !{}\n',
 'edge-three-predecessors': edge_division(third=True), 'edge-both': edge_division(both=True),
 'edge-far': edge_division(left_extra=''.join(f'  %x{k} = add i64 %a, {k}\n' for k in range(16))),
 'edge-near': edge_division(left_extra=''.join(f'  %x{k} = add i64 %a, {k}\n' for k in range(14))),
 'edge-optsize': edge_division(attrs='optsize'), 'edge-asan': edge_division(attrs='sanitize_address'),
 'edge-x86': edge_division().replace(MAC, 'x86_64-apple-macosx14.0.0'), 'edge-linux': edge_division().replace(MAC, 'aarch64-unknown-linux-gnu'),
 'edge-sanitizer-flag': edge_division() + '!llvm.module.flags = !{!0}\n!0 = !{i32 1, !"SanitizeAddress", i32 1}\n',
 'shift-nonnegative': guarded_shift(), 'shift-maybe-negative': guarded_shift(guard='icmp sgt i64 %fx, -2'), 'shift-not-frozen': guarded_shift(dividend='%x', guard='icmp sgt i64 %x, -1'),
 'shift-exact': guarded_shift(exact='exact '), 'shift-other-operand': guarded_shift(guard='icmp sgt i64 %x, -1'),
 'joined-sdiv': joined_quotient(), 'joined-shift': joined_quotient(right_quotient='  %qb = lshr i64 %fx, 3\n', guard_block=True).replace('%qa = sdiv i64 %x, %y', '%qa = sdiv i64 %fx, 8').replace('%xp = phi i64 [ %x, %a ], [ %x, %b ]', '%xp = phi i64 [ %fx, %a ], [ %fx, %b ]').replace('%yp = phi i64 [ %y, %a ], [ %y, %b ]', '%yp = phi i64 [ 8, %a ], [ 8, %b ]'),
 'joined-shift-plain-guard': joined_quotient(right_quotient='  %qb = lshr i64 %fx, 3\n', guard_block=True, guard='icmp ult i64 %fx, 100').replace('%qa = sdiv i64 %x, %y', '%qa = sdiv i64 %fx, 8').replace('%xp = phi i64 [ %x, %a ], [ %x, %b ]', '%xp = phi i64 [ %fx, %a ], [ %fx, %b ]').replace('%yp = phi i64 [ %y, %a ], [ %y, %b ]', '%yp = phi i64 [ 8, %a ], [ 8, %b ]'),
 'joined-wrong-divisor': joined_quotient(right_quotient='  %qb = sdiv i64 %x, 7\n'), 'joined-exact': joined_quotient(exact='exact '),
 'redundant': redundant_factor(), 'redundant-shift': redundant_factor(second='  %q2 = lshr i64 %n, 2\n', factor='4'),
 'redundant-wrong-shift': redundant_factor(second='  %q2 = lshr i64 %n, 3\n', factor='4'), 'redundant-wrong-test': redundant_factor(entry_test='icmp ne i64 %n, %pe'),
 'carry': carried_factor(), 'carry-shift': carried_factor(second='', factor='8'), 'carry-no-reuse': carried_factor(second='', factor='%f'),
 'carry-swapped': carried_factor(compare='icmp eq i64 %rem, %prod', product='mul i64 {factor}, %div'), 'carry-not-equal': carried_factor(compare='icmp ne i64 %prod, %rem'),
 'carry-large': carried_factor(extra=''.join(f'  %e{k} = add i64 %rem, {k}\n' for k in range(8))),
 'induction': induction_quotient(), 'induction-start-one': induction_quotient(start='1'), 'induction-start-three': induction_quotient(start='3'), 'induction-start-four': induction_quotient(start='4'),
 'induction-plain-guard': induction_quotient(guard='icmp sgt i64 %fr, 3'), 'induction-negative-bound': induction_quotient(guard='icmp samesign sgt i64 %fr, -3'),
 'induction-swapped': induction_quotient(test='icmp sge i64 %lq, %next'), 'induction-inverted': induction_quotient(test='icmp sgt i64 %next, %lq', order='label %exit, label %header'),
 'induction-unsigned': induction_quotient(test='icmp ult i64 %next, %lq'), 'induction-greater': induction_quotient(test='icmp sgt i64 %next, %lq'),
 'induction-step-two': induction_quotient(step='2'), 'induction-signed-latch': induction_quotient(latch_div='sdiv i64 %fr, %next'),
 'four-cap': repeated_joins(5), 'three-joins': repeated_joins(3),
}

# name -> (IR, divisions the C++ pass reused)
CASES = {name: (text, REUSED[name]) for name, text in SHAPES.items()}
