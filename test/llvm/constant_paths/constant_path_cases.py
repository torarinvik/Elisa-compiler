"""IR shapes for the constant integer path folds, shared by their test.

`equality_path` returns a value a loop computes from constants on one edge of an entry
test of the argument; `domain_path` evaluates a loop for each key of a small accepted
interval; `zero_bypass` skips a product that is zero anyway; `boolean_lookup` reads a
0/1 byte table behind a bounds check; `state_table` reads a state table behind a bounds
check every reachable state passes. Each case's expected shape is what the C++ pass left
(see EXPECTED).
"""
DARWIN = 'target triple = "arm64-apple-macosx14.0.0"\n'
X86 = 'target triple = "x86_64-apple-macosx14.0.0"\n'
DECLARATIONS = '''declare i64 @llvm.ctpop.i64(i64)
declare { i64, i1 } @llvm.uadd.with.overflow.i64(i64, i64)
declare i64 @llvm.uadd.sat.i64(i64, i64)
declare void @llvm.assume(i1)
declare i64 @opaque(i64)
'''


def module(body, triple=DARWIN):
    return triple + DECLARATIONS + body


def equality_path(limit=10, step='%s.next = add i64 %s, %i', extra='', predicate='eq', test_operand='%n', attributes='', result='i64', returned='%s.next', other='ret i64 %n'):
    convert = f'  %out = trunc i64 {returned} to {result}\n  ret {result} %out\n' if result != 'i64' else f'  ret i64 {returned}\n'
    other_block = other.replace('ret i64 %n', f'%n.narrow = trunc i64 %n to {result}\n  ret {result} %n.narrow') if result != 'i64' else other
    return f'''define {result} @f(i64 %n) {attributes} {{
entry:
  %c = icmp {predicate} i64 {test_operand}, 0
  br i1 %c, label %loop, label %other
loop:
  %i = phi i64 [ 0, %entry ], [ %i.next, %loop ]
  %s = phi i64 [ 0, %entry ], [ %s.next, %loop ]
{extra}  {step}
  %i.next = add i64 %i, 1
  %done = icmp eq i64 %i.next, {limit}
  br i1 %done, label %exit, label %loop
exit:
{convert}other:
  {other_block}
}}
'''


def domain_path(bias='-5', bound='20', predicate='ult', key_source='%x', results='add i64 %s.next, 0', freeze=False, arguments='i64 %x', loop_bound='%x', loop=True, edges='label %compute, label %bad', extra=''):
    stable = '  %xf = freeze i64 %x\n' if freeze else ''
    source = '%xf' if freeze else key_source
    key = f'  %k = add i64 {source}, {bias}\n' if bias is not None else ''
    compared = '%k' if bias is not None else source
    body = f'''compute:
  br label %loop
loop:
  %i = phi i64 [ 0, %compute ], [ %i.next, %loop ]
  %s = phi i64 [ 0, %compute ], [ %s.next, %loop ]
  %s.next = add i64 %s, %i
{extra}  %i.next = add i64 %i, 1
  %done = icmp ugt i64 %i.next, {loop_bound}
  br i1 %done, label %exit, label %loop
exit:
  %r = {results}
  ret i64 %r
''' if loop else f'''compute:
  %r0 = mul i64 {source}, 3
  br label %exit
exit:
  %r = add i64 %r0, 1
  ret i64 %r
'''
    return f'''define i64 @g({arguments}) {{
entry:
{stable}{key}  %c = icmp {predicate} i64 {compared}, {bound}
  br i1 %c, {edges}
{body}bad:
  ret i64 -1
}}
'''


def zero_bypass(predicate='eq', products=('%p = mul i64 %n, 7', '%q = mul i64 %p, %n'), bypass='0', last='%q'):
    edges = 'label %join, label %product' if predicate == 'eq' else 'label %product, label %join'
    lines = ''.join(f'  {line}\n' for line in products)
    return f'''define i64 @h(i64 %n, i64 %m) {{
entry:
  %c = icmp {predicate} i64 %n, 0
  br i1 %c, {edges}
product:
{lines}  br label %join
join:
  %r = phi i64 [ {bypass}, %entry ], [ {last}, %product ]
  ret i64 %r
}}
'''


def boolean_lookup(table='private unnamed_addr constant [10 x i8] c"\\01\\00\\01\\01\\00\\00\\01\\00\\01\\01"', state='%state = select i1 %c, i64 3, i64 7', offset='add i64 %state, -2', count='10', fallback='0'):
    return f'''@table = {table}
define i32 @b(i1 %c, i64 %arg) {{
entry:
  {state}
  %offset = {offset}
  %ok = icmp ult i64 %offset, {count}
  br i1 %ok, label %lookup, label %join
lookup:
  %addr = getelementptr i8, ptr @table, i64 %offset
  %byte = load i8, ptr %addr, align 1
  %wide = zext i8 %byte to i32
  br label %join
join:
  %r = phi i32 [ {fallback}, %entry ], [ %wide, %lookup ]
  ret i32 %r
}}
'''


def state_table(table='internal constant [4 x i64] [i64 1, i64 2, i64 3, i64 0]', compare='icmp ult i64 %s, 4', initial='0'):
    return f'''@states = {table}
define i64 @t(i64 %n) {{
entry:
  br label %loop
loop:
  %s = phi i64 [ {initial}, %entry ], [ %next, %body ]
  %i = phi i64 [ 0, %entry ], [ %i.next, %body ]
  %ok = {compare}
  br i1 %ok, label %body, label %bad
body:
  %addr = getelementptr i64, ptr @states, i64 %s
  %next = load i64, ptr %addr, align 8
  %i.next = add i64 %i, 1
  %done = icmp eq i64 %i.next, %n
  br i1 %done, label %exit, label %loop
bad:
  ret i64 -1
exit:
  ret i64 %next
}}
'''


GLOBAL_TABLE = '@squares = private unnamed_addr constant [4 x i64] [i64 0, i64 1, i64 4, i64 9]\n'

CASES = {
    'equality-sum': module(equality_path()),
    'equality-ne-edge': module(equality_path(predicate='ne')),
    'equality-long-loop': module(equality_path(limit=100000)),
    'equality-argument-dependent': module(equality_path(step='%s.next = add i64 %s, %n')),
    'equality-opaque-call': module(equality_path(extra='  %o = call i64 @opaque(i64 %i)\n', step='%s.next = add i64 %s, %o')),
    'equality-ctpop': module(equality_path(extra='  %pop = call i64 @llvm.ctpop.i64(i64 %i)\n', step='%s.next = add i64 %s, %pop')),
    'equality-overflow-intrinsic': module(equality_path(extra='  %pair = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %s, i64 %i)\n', step='%s.next = extractvalue { i64, i1 } %pair, 0')),
    'equality-saturating': module(equality_path(extra='  %sat = call i64 @llvm.uadd.sat.i64(i64 %s, i64 %i)\n', step='%s.next = add i64 %sat, 1')),
    'equality-table-load': module(GLOBAL_TABLE + equality_path(limit=4, extra='  %slot = getelementptr [4 x i64], ptr @squares, i64 0, i64 %i\n  %square = load i64, ptr %slot, align 8\n', step='%s.next = add i64 %s, %square')),
    'equality-assume': module(equality_path(extra='  %small = icmp ult i64 %i, 100\n  call void @llvm.assume(i1 %small)\n')),
    'equality-false-assume': module(equality_path(extra='  %small = icmp ugt i64 %i, 100\n  call void @llvm.assume(i1 %small)\n')),
    'equality-select-freeze': module(equality_path(extra='  %even = and i64 %i, 1\n  %is.even = icmp eq i64 %even, 0\n  %pick = select i1 %is.even, i64 %i, i64 0\n  %frozen = freeze i64 %pick\n', step='%s.next = add i64 %s, %frozen')),
    'equality-i32-result': module(equality_path(result='i32')),
    'equality-not-argument': module(equality_path(extra='', test_operand='7')),
    'equality-x86': module(equality_path(), X86),
    'equality-optnone': module(equality_path(attributes='noinline optnone')),
    'equality-optsize': module(equality_path(attributes='optsize')),
    'domain-table': module(domain_path()),
    'domain-mask': module(domain_path(results='and i64 %s.next, 1')),
    'domain-negative': module(domain_path(results='sub i64 0, %s.next')),
    'domain-no-bias': module(domain_path(bias=None, bound='12')),
    'domain-freeze': module(domain_path(freeze=True)),
    'domain-freeze-used': module(domain_path(freeze=True, loop_bound='%xf')),
    'domain-inverse-edge': module(domain_path(predicate='uge', edges='label %bad, label %compute')),
    'domain-too-few-keys': module(domain_path(bound='5')),
    'domain-too-many-keys': module(domain_path(bound='200')),
    'domain-signed-test': module(domain_path(predicate='slt')),
    'domain-two-arguments': module(domain_path(arguments='i64 %x, i64 %y')),
    'domain-cheap-paths': module(domain_path(loop=False)),
    'domain-long-paths': module(domain_path(bound='150', bias='-1000000')),
    # Nine more loop values fill a path's value table on the first iteration and grow it
    # again while the second iteration updates the loop phis.
    'domain-loop-values': module(domain_path(extra=''.join(f'  %e{index} = add i64 %i, {index}\n' for index in range(9)))),
    'zero-bypass': module(zero_bypass()),
    'zero-bypass-ne': module(zero_bypass(predicate='ne')),
    'zero-bypass-unknown-factor': module(zero_bypass(products=('%p = mul i64 %n, %m', '%q = mul i64 %p, 3'))),
    'zero-bypass-add': module(zero_bypass(products=('%p = mul i64 %n, 7', '%q = add i64 %p, 1'))),
    'zero-bypass-nonzero-default': module(zero_bypass(bypass='5')),
    'boolean-lookup': module(boolean_lookup()),
    'boolean-lookup-mutable-table': module(boolean_lookup(table='private global [10 x i8] c"\\01\\00\\01\\01\\00\\00\\01\\00\\01\\01"')),
    'boolean-lookup-byte-two': module(boolean_lookup(table='private unnamed_addr constant [10 x i8] c"\\01\\00\\02\\01\\00\\00\\01\\00\\01\\01"')),
    'boolean-lookup-unbounded-state': module(boolean_lookup(state='%state = add i64 %arg, 0')),
    'boolean-lookup-nsw': module(boolean_lookup(offset='add nsw i64 %state, -2')),
    'boolean-lookup-nonzero-fallback': module(boolean_lookup(fallback='1')),
    'state-table': module(state_table()),
    'state-table-out-of-range': module(state_table(table='internal constant [4 x i64] [i64 1, i64 2, i64 5, i64 0]')),
    'state-table-external': module(state_table(table='constant [4 x i64] [i64 1, i64 2, i64 3, i64 0]')),
    'state-table-samesign': module(state_table(compare='icmp samesign ult i64 %s, 4')),
    'state-table-bad-initial': module(state_table(initial='9')),
}

# Per case: the count, then the conditional branches, returns, lookup tables and
# constant-path blocks left, as the C++ pass left them.
EXPECTED = {
    'boolean-lookup-byte-two': (0, 1, 1, 0, 0),
    'boolean-lookup-mutable-table': (0, 1, 1, 0, 0),
    'boolean-lookup-nonzero-fallback': (0, 1, 1, 0, 0),
    'boolean-lookup-nsw': (0, 1, 1, 0, 0),
    'boolean-lookup-unbounded-state': (0, 1, 1, 0, 0),
    'boolean-lookup': (1, 0, 1, 0, 0),
    'domain-cheap-paths': (0, 1, 2, 0, 0),
    'domain-freeze-used': (1, 1, 2, 1, 0),
    'domain-freeze': (0, 2, 2, 0, 0),
    'domain-inverse-edge': (1, 1, 2, 1, 0),
    'domain-long-paths': (0, 2, 2, 0, 0),
    'domain-loop-values': (1, 1, 2, 1, 0),
    'domain-mask': (1, 1, 2, 0, 0),
    'domain-negative': (1, 1, 2, 1, 0),
    'domain-no-bias': (1, 1, 2, 1, 0),
    'domain-signed-test': (0, 2, 2, 0, 0),
    'domain-table': (1, 1, 2, 1, 0),
    'domain-too-few-keys': (0, 2, 2, 0, 0),
    'domain-too-many-keys': (0, 2, 2, 0, 0),
    'domain-two-arguments': (0, 2, 2, 0, 0),
    'equality-argument-dependent': (0, 2, 2, 0, 0),
    'equality-assume': (1, 1, 2, 0, 1),
    'equality-ctpop': (1, 1, 2, 0, 1),
    'equality-false-assume': (0, 2, 2, 0, 0),
    'equality-i32-result': (1, 1, 2, 0, 1),
    'equality-long-loop': (0, 2, 2, 0, 0),
    'equality-ne-edge': (1, 1, 2, 0, 1),
    'equality-not-argument': (0, 2, 2, 0, 0),
    'equality-opaque-call': (0, 2, 2, 0, 0),
    'equality-optnone': (0, 2, 2, 0, 0),
    'equality-optsize': (0, 2, 2, 0, 0),
    'equality-overflow-intrinsic': (1, 1, 2, 0, 1),
    'equality-saturating': (1, 1, 2, 0, 1),
    'equality-select-freeze': (1, 1, 2, 0, 1),
    'equality-sum': (1, 1, 2, 0, 1),
    'equality-table-load': (1, 1, 2, 0, 1),
    'equality-x86': (0, 2, 2, 0, 0),
    'state-table-bad-initial': (0, 2, 2, 0, 0),
    'state-table-external': (0, 2, 2, 0, 0),
    'state-table-out-of-range': (0, 2, 2, 0, 0),
    'state-table-samesign': (0, 2, 2, 0, 0),
    'state-table': (1, 1, 1, 0, 0),
    'zero-bypass-add': (1, 1, 2, 0, 1),
    'zero-bypass-ne': (1, 0, 1, 0, 0),
    'zero-bypass-nonzero-default': (1, 1, 2, 0, 1),
    'zero-bypass-unknown-factor': (1, 1, 2, 0, 1),
    'zero-bypass': (1, 0, 1, 0, 0),
}
