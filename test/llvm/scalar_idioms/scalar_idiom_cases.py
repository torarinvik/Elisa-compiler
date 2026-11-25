"""IR shapes for the AArch64 scalar idiom folds, shared by their test.

`carry_addition` is the `while carry: (sum, carry) = (x ^ y, (x & y) << 1)` loop;
`trailing_zero_loop` shifts a nonzero value right until its low (or, testing before the
shift, second) bit is set; `threshold_search` is the unsigned lower-bound search;
`bit_spread` smears the highest set bit downward and adds one; `nibble_population` sums a
population table over eight nibbles; `odd_trailing_zero_select` selects zero for an odd
value around `cttz`. Each case maps to its pass and the rewrite count the C++ passes
reported for the same input.
"""
MAC = 'arm64-apple-macosx14.0.0'
X86 = 'x86_64-apple-macosx14.0.0'
IDIOMS = 'scalar-loop-idioms'
SELECTS = 'odd-trailing-zero-selects'


def module_text(body, triple=MAC):
    return f'target triple = "{triple}"\n{body}'


def filler_blocks(count):
    return ''.join(f'filler{index}:\n  br label %filler{index + 1}\n' for index in range(count))


def entry_blocks(padding):
    if not padding:
        return 'entry:\n  br label %preheader\n'
    return f'entry:\n  br label %filler0\n{filler_blocks(padding)}filler{padding}:\n  br label %preheader\n'


def carry_addition(integer='i64', predicate='eq', swap_phis=False, swap_and=False, swap_xor=False, padding=0, extra_use=False, attributes=''):
    exit_on_true = predicate == 'eq'
    branch = 'br i1 %done, label %exit, label %loop' if exit_on_true else 'br i1 %done, label %loop, label %exit'
    phis = [f'  %x = phi {integer} [ %a, %preheader ], [ %sum, %loop ]', f'  %y = phi {integer} [ %b, %preheader ], [ %carry, %loop ]']
    if swap_phis:
        phis.reverse()
    both = f'and {integer} %y, %x' if swap_and else f'and {integer} %x, %y'
    sum_value = f'xor {integer} %y, %x' if swap_xor else f'xor {integer} %x, %y'
    extra = f'  %extra = add {integer} %carry, 1\n' if extra_use else ''
    return module_text(f'''define {integer} @f({integer} %a, {integer} %b) {attributes} {{
{entry_blocks(padding)}preheader:
  br label %loop
loop:
{chr(10).join(phis)}
  %sum = {sum_value}
  %both = {both}
  %carry = shl {integer} %both, 1
{extra}  %done = icmp {predicate} {integer} %carry, 0
  {branch}
exit:
  ret {integer} %sum
}}
''')


TRAILING_ZERO_ENTRIES = {
    'nonzero': '  %nonzero = icmp ne TYPE %s, 0\n  br i1 %nonzero, label %loop, label %zero\n',
    'odd': '  %odd = or TYPE %seed, 1\n  br label %loop\n',
    'none': '  br label %loop\n',
    'assume': '  %nonzero = icmp ne TYPE %s, 0\n  call void @llvm.assume(i1 %nonzero)\n  br label %loop\n',
}


def trailing_zero_loop(integer='i64', test_before_shift=False, counter=True, guard='nonzero', exact=None, result='%w', extra=''):
    exact = test_before_shift if exact is None else exact
    tested_bit = 2 if test_before_shift else 1
    shift = f'lshr {"exact " if exact else ""}{integer} %w, 1'
    entry = TRAILING_ZERO_ENTRIES[guard].replace('TYPE', integer)
    initial = '%odd' if guard == 'odd' else '%s'
    counter_phi = f'  %c = phi {integer} [ 0, %entry ], [ %inc, %loop ]\n' if counter else ''
    counter_step = f'  %inc = add {integer} %c, 1\n' if counter else ''
    return module_text(f'''declare void @llvm.assume(i1)
define {integer} @f({integer} %s, {integer} %seed) {{
entry:
{entry}loop:
  %w = phi {integer} [ {initial}, %entry ], [ %shifted, %loop ]
{counter_phi}  %shifted = {shift}
{counter_step}{extra}  %bit = and {integer} %w, {tested_bit}
  %clear = icmp eq {integer} %bit, 0
  br i1 %clear, label %loop, label %exit
exit:
  ret {integer} {result if counter else '%w'}
zero:
  ret {integer} 0
}}
''')


def threshold_search(split='ult', test='icmp ult i64 %next.low, %next.high', order='label %loop, label %exit', target='%t', guard='icmp ult i64 %first, %last', padding=0):
    if split == 'ult':
        updates = '  %next.low = select i1 %split, i64 %step, i64 %low\n  %next.high = select i1 %split, i64 %high, i64 %mid\n'
    else:
        updates = '  %next.low = select i1 %split, i64 %low, i64 %step\n  %next.high = select i1 %split, i64 %mid, i64 %high\n'
    return module_text(f'''define i64 @f(i64 %first, i64 %last, i64 %t) {{
{entry_blocks(padding)}preheader:
  %nonempty = {guard}
  br i1 %nonempty, label %loop, label %exit
loop:
  %low = phi i64 [ %first, %preheader ], [ %next.low, %loop ]
  %high = phi i64 [ %last, %preheader ], [ %next.high, %loop ]
  %width = sub i64 %high, %low
  %half = lshr i64 %width, 1
  %mid = add i64 %low, %half
  %split = icmp {split} i64 %mid, {target}
  %step = add i64 %mid, 1
{updates}  %continue = {test}
  br i1 %continue, {order}
exit:
  %result = phi i64 [ %first, %preheader ], [ %next.low, %loop ]
  ret i64 %result
}}
''')


def bit_spread(integer='i64', operand='and TYPE %x, 1023', first_shift=None, swap=False, addend=1, used=True, missing_shift=None):
    shifts = []
    shift = first_shift or int(integer[1:]) // 2
    while shift:
        shifts.append(shift)
        shift //= 2
    lines = [f'  %v = {operand.replace("TYPE", integer)}']
    previous = '%v'
    for shift in reversed(shifts):
        if shift == missing_shift:
            continue
        lines.append(f'  %shifted{shift} = lshr {integer} {previous}, {shift}')
        lines.append(f'  %spread{shift} = or {integer} %shifted{shift}, {previous}' if swap else f'  %spread{shift} = or {integer} {previous}, %shifted{shift}')
        previous = f'%spread{shift}'
    lines.append(f'  %next = add {integer} {previous}, {addend}')
    returned = '%next' if used else '0'
    return module_text(f'define {integer} @f({integer} %x) {{\nentry:\n' + '\n'.join(lines) + f'\n  ret {integer} {returned}\n}}\n')


POPULATION_TABLE = '[16 x i32] [' + ', '.join(f'i32 {bin(index).count("1")}' for index in range(16)) + ']'


def nibble_population(integer='i32', table=POPULATION_TABLE, linkage='constant', two_indices=False, duplicate_nibble=False, duplicate_lane=False, volatile=''):
    lines = []
    previous = 'poison'
    for lane in range(8):
        shift = 4 * (6 if duplicate_nibble and lane == 7 else lane)
        source = f'%shifted{lane}' if shift else '%x'
        if shift:
            lines.append(f'  %shifted{lane} = lshr {integer} %x, {shift}')
        lines.append(f'  %nibble{lane} = and {integer} {source}, 15')
        address = f'getelementptr [16 x i32], ptr @table, i64 0, {integer} %nibble{lane}' if two_indices else f'getelementptr i32, ptr @table, {integer} %nibble{lane}'
        lines.append(f'  %entry{lane} = {address}')
        lines.append(f'  %count{lane} = load {volatile}i32, ptr %entry{lane}')
        position = 6 if duplicate_lane and lane == 7 else lane
        lines.append(f'  %vector{lane} = insertelement <8 x i32> {previous}, i32 %count{lane}, i32 {position}')
        previous = f'%vector{lane}'
    body = '\n'.join(lines)
    return module_text(f'''@table = private unnamed_addr {linkage} {table}
declare i32 @llvm.vector.reduce.add.v8i32(<8 x i32>)
define i32 @f({integer} %x) {{
entry:
{body}
  %result = call i32 @llvm.vector.reduce.add.v8i32(<8 x i32> {previous})
  ret i32 %result
}}
''')


def odd_trailing_zero_select(predicate='eq', shift=None, exact='', count_uses=1, operand='%x', integer='i64', triple=MAC):
    even = '%even' if shift is not None else '%count'
    select = f'select i1 %low, {integer} 0, {integer} {even}' if predicate == 'ne' else f'select i1 %low, {integer} {even}, {integer} 0'
    shifted = f'  %even = lshr {exact}{integer} %count, {shift}\n' if shift is not None else ''
    extra_use = f'  call void @use({integer} %count)\n' if count_uses == 2 else ''
    return module_text(f'''declare void @use({integer})
declare {integer} @llvm.cttz.{integer}({integer}, i1)
define {integer} @f({integer} %x, {integer} %y) {{
entry:
  %bit = and {integer} %x, 1
  %low = icmp {predicate} {integer} %bit, 0
  %count = call range({integer} 1, 65) {integer} @llvm.cttz.{integer}({integer} {operand}, i1 true)
{extra_use}{shifted}  %result = {select}
  ret {integer} %result
}}
''', triple)


CASES = {
    'carry': (carry_addition(), IDIOMS, 1),
    'carry-ne': (carry_addition(predicate='ne'), IDIOMS, 1),
    'carry-i32': (carry_addition(integer='i32'), IDIOMS, 1),
    'carry-i1': (carry_addition(integer='i1'), IDIOMS, 0),
    'carry-swapped-phis': (carry_addition(swap_phis=True), IDIOMS, 1),
    'carry-swapped-and': (carry_addition(swap_and=True), IDIOMS, 1),
    'carry-swapped-xor': (carry_addition(swap_xor=True), IDIOMS, 1),
    'carry-extra-use': (carry_addition(extra_use=True), IDIOMS, 0),
    'carry-big-function': (carry_addition(padding=15), IDIOMS, 0),
    'carry-medium-function': (carry_addition(padding=11), IDIOMS, 1),
    'carry-optsize': (carry_addition(attributes='optsize'), IDIOMS, 0),
    'carry-minsize': (carry_addition(attributes='minsize'), IDIOMS, 0),
    'carry-asan': (carry_addition(attributes='sanitize_address'), IDIOMS, 0),
    'carry-x86': (carry_addition().replace(MAC, X86), IDIOMS, 0),
    'zeros-pre': (trailing_zero_loop(), IDIOMS, 1),
    'zeros-post': (trailing_zero_loop(test_before_shift=True), IDIOMS, 1),
    'zeros-no-counter': (trailing_zero_loop(counter=False), IDIOMS, 1),
    'zeros-post-no-counter': (trailing_zero_loop(test_before_shift=True, counter=False), IDIOMS, 1),
    'zeros-i32': (trailing_zero_loop(integer='i32'), IDIOMS, 1),
    'zeros-i16': (trailing_zero_loop(integer='i16'), IDIOMS, 0),
    'zeros-unguarded': (trailing_zero_loop(guard='none'), IDIOMS, 0),
    'zeros-odd': (trailing_zero_loop(guard='odd'), IDIOMS, 1),
    'zeros-assume': (trailing_zero_loop(guard='assume'), IDIOMS, 1),
    'zeros-exact-mismatch': (trailing_zero_loop(exact=True), IDIOMS, 0),
    'zeros-post-inexact': (trailing_zero_loop(test_before_shift=True, exact=False), IDIOMS, 0),
    'zeros-count-result': (trailing_zero_loop(result='%c'), IDIOMS, 1),
    'zeros-extra': (trailing_zero_loop(extra='  %unrelated = add i64 %w, 3\n'), IDIOMS, 0),
    'search': (threshold_search(), IDIOMS, 1),
    'search-uge': (threshold_search(split='uge'), IDIOMS, 1),
    'search-ugt-test': (threshold_search(test='icmp ugt i64 %next.high, %next.low'), IDIOMS, 1),
    'search-inverted': (threshold_search(test='icmp uge i64 %next.low, %next.high', order='label %exit, label %loop'), IDIOMS, 1),
    'search-target-low': (threshold_search(target='%first'), IDIOMS, 1),
    'search-target-high': (threshold_search(target='%last'), IDIOMS, 1),
    'search-target-in-loop': (threshold_search(target='%low'), IDIOMS, 0),
    'search-wrong-guard': (threshold_search(guard='icmp ult i64 %t, %last'), IDIOMS, 0),
    'search-signed-guard': (threshold_search(guard='icmp slt i64 %first, %last'), IDIOMS, 0),
    'search-signed-test': (threshold_search(test='icmp slt i64 %next.low, %next.high'), IDIOMS, 0),
    'search-big-function': (threshold_search(padding=15), IDIOMS, 0),
    'spread': (bit_spread(), IDIOMS, 1),
    'spread-i32': (bit_spread(integer='i32'), IDIOMS, 1),
    'spread-i16': (bit_spread(integer='i16', operand='and TYPE %x, 255'), IDIOMS, 0),
    'spread-from-16': (bit_spread(first_shift=16), IDIOMS, 1),
    'spread-from-16-wide': (bit_spread(first_shift=16, operand='and TYPE %x, 4294967295'), IDIOMS, 1),
    'spread-full': (bit_spread(operand='add TYPE %x, 0'), IDIOMS, 0),
    'spread-63-bits': (bit_spread(operand='lshr TYPE %x, 1'), IDIOMS, 1),
    'spread-swapped': (bit_spread(swap=True), IDIOMS, 1),
    'spread-add-two': (bit_spread(addend=2), IDIOMS, 0),
    'spread-unused': (bit_spread(used=False), IDIOMS, 0),
    'spread-missing-stage': (bit_spread(missing_shift=4), IDIOMS, 0),
    'nibbles': (nibble_population(), IDIOMS, 1),
    'nibbles-i64': (nibble_population(integer='i64'), IDIOMS, 1),
    'nibbles-two-indices': (nibble_population(two_indices=True), IDIOMS, 1),
    'nibbles-wrong-table': (nibble_population(table=POPULATION_TABLE.replace('i32 4]', 'i32 5]')), IDIOMS, 0),
    'nibbles-mutable-table': (nibble_population(linkage='global'), IDIOMS, 0),
    'nibbles-duplicate-nibble': (nibble_population(duplicate_nibble=True), IDIOMS, 0),
    'nibbles-duplicate-lane': (nibble_population(duplicate_lane=True), IDIOMS, 0),
    'nibbles-volatile': (nibble_population(volatile='volatile '), IDIOMS, 0),
    'odd': (odd_trailing_zero_select(), SELECTS, 1),
    'odd-ne': (odd_trailing_zero_select(predicate='ne'), SELECTS, 1),
    'odd-shift': (odd_trailing_zero_select(shift=1), SELECTS, 1),
    'odd-exact-shift': (odd_trailing_zero_select(shift=1, exact='exact '), SELECTS, 0),
    'odd-wide-shift': (odd_trailing_zero_select(shift=64), SELECTS, 0),
    'odd-two-uses': (odd_trailing_zero_select(count_uses=2), SELECTS, 0),
    'odd-other-operand': (odd_trailing_zero_select(operand='%y'), SELECTS, 0),
    'odd-i32': (odd_trailing_zero_select(integer='i32'), SELECTS, 1),
    'odd-x86': (odd_trailing_zero_select(triple=X86), SELECTS, 0),
}
