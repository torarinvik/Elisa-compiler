"""IR shapes for the bounded-factorial proofs, shared by their test.

`bounded-factorials` settles the checked arithmetic of innermost loops with a small
bounded trip count exactly: running products of a unit-step counter (20! fits, 21! does
not), sums of a value divided down to zero, Horner recurrences, down-counter products,
and every other checked call a bounded interval simulation of the loop keeps in range.
Each fixture is one of those shapes; each case varies one, and its count and what it
leaves are what the C++ pass did with the same shapes (see EXPECTED).
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAC = 'arm64-apple-darwin27.2.0'
LINUX = 'aarch64-unknown-linux-gnu'


def fixture(name):
    return (HERE / f'bounded_{name}_fixture.ll').read_text().replace(LINUX, MAC)


FACTORIAL = fixture('factorial')
DIVISION_SUM = fixture('division_sum')
HORNER = fixture('horner')
INTERVAL = fixture('interval')
DOWN = fixture('down')
DECLARATIONS = {
    'sadd': 'declare {i64,i1} @llvm.sadd.with.overflow.i64(i64,i64)',
    'ssub': 'declare {i64,i1} @llvm.ssub.with.overflow.i64(i64,i64)',
    'smul': 'declare {i64,i1} @llvm.smul.with.overflow.i64(i64,i64)',
}


def varied(text, *replacements, tail=''):
    """TEXT with each (old, new) replacement made once, and any checked-arithmetic
    declaration it now uses but lacks."""
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new, 1)
    text += tail
    for kind, declaration in DECLARATIONS.items():
        if f'@llvm.{kind}.with.overflow.i64(' in text and declaration not in text:
            text += declaration + '\n'
    return text


def interval_step(definition):
    """The interval fixture with DEFINITION (of %u, from %t) between the checked add and
    the checked multiply, which now multiplies %u."""
    return varied(INTERVAL, (' %q = call {i64,i1} @llvm.smul.with.overflow.i64(i64 %t, i64 3)', definition + '\n %q = call {i64,i1} @llvm.smul.with.overflow.i64(i64 %u, i64 3)'))


def padded(text, block_end, count):
    """TEXT with COUNT unused adds before BLOCK_END, a line ending one of its blocks."""
    padding = ''.join(f' %pad{index} = add i64 %d, {index}\n' for index in range(count))
    return varied(text, (block_end, padding + block_end))


def two_functions():
    """The factorial fixture with the down-counter function beside it."""
    return FACTORIAL + DOWN[DOWN.index('define'):DOWN.index('declare')]


FACTORIAL_CASES = {
    'factorial': FACTORIAL,
    'factorial-linux': FACTORIAL.replace(MAC, LINUX),
    'bound-21': varied(FACTORIAL, ('ugt i64 %n, 20', 'ugt i64 %n, 21')),
    'unbounded': varied(FACTORIAL, ('%bad = icmp ugt i64 %n, 20', '%bad = icmp eq i64 %n, -5')),
    'large-start': varied(FACTORIAL, ('[1,%pre], [%low,%ok]', '[4,%pre], [%low,%ok]')),
    'negative-limit-start': varied(FACTORIAL, ('[2,%pre], [%next', '[-30,%pre], [%next')),
    'step-two': varied(FACTORIAL, ('add i64 %c, 1', 'add i64 %c, 2'), ('ugt i64 %n, 20', 'ugt i64 %n, 2000')),
    'non-unit-step': varied(FACTORIAL, ('add i64 %c, 1', 'mul i64 %c, 3')),
    'wrong-direction': varied(FACTORIAL, ('icmp sgt i64 %next, %n', 'icmp slt i64 %next, %n')),
    'other-operands': varied(FACTORIAL, ('i64 %p, i64 %c), !elisa', 'i64 %p, i64 %n), !elisa')),
    'sanitizer': varied(FACTORIAL, ('@fact(i64 %n) {', '@fact(i64 %n) sanitize_address {')),
    'check-operands-swapped': varied(FACTORIAL, ('i64 %p, i64 %c), !elisa', 'i64 %c, i64 %p), !elisa')),
    'check-through-freeze': varied(FACTORIAL, (' %m = call', ' %pf = freeze i64 %p\n %m = call'), ('i64 %p, i64 %c), !elisa', 'i64 %pf, i64 %c), !elisa')),
    'multiply-through-freeze': varied(FACTORIAL, (' %low = mul i64 %p, %c', ' %cf = freeze i64 %c\n %low = mul i64 %cf, %p')),
    'unsigned-multiply': varied(FACTORIAL, ('%low = mul i64', '%low = mul nuw i64')),
    'limit-swapped': varied(FACTORIAL, ('icmp sgt i64 %next, %n', 'icmp slt i64 %n, %next')),
    'stays-on-true': varied(FACTORIAL, ('icmp sgt i64 %next, %n\n br i1 %done, label %exit, label %body', 'icmp sle i64 %next, %n\n br i1 %done, label %body, label %exit')),
    'strict-stay': varied(FACTORIAL, ('icmp sgt i64 %next, %n\n br i1 %done, label %exit, label %body', 'icmp slt i64 %next, %n\n br i1 %done, label %body, label %exit')),
    'checked-step': varied(FACTORIAL, (' %next = add i64 %c, 1', ' %nc = call {i64,i1} @llvm.sadd.with.overflow.i64(i64 %c, i64 1)\n %next = extractvalue {i64,i1} %nc, 0')),
    'counter-from-zero': varied(FACTORIAL, ('[2,%pre], [%next', '[0,%pre], [%next')),
    'second-check': varied(FACTORIAL, (' %next = add i64 %c, 1', ' %again = call {i64,i1} @llvm.smul.with.overflow.i64(i64 %p, i64 %c)\n %next = add i64 %c, 1')),
    'check-before-multiply': varied(FACTORIAL, (' %low = mul i64 %p, %c\n', ''), (' %next = add i64 %c, 1', ' %low = mul i64 %p, %c\n %next = add i64 %c, 1')),
    'opaque-metadata': varied(FACTORIAL, ('!elisa.checkedmul.slow !0', '!opaque !0')),
    'two-functions': two_functions(),
}

DIVISION_SUM_CASES = {
    'sum-quotient': DIVISION_SUM.replace('ADDEND', 'q'),
    'sum-remainder': DIVISION_SUM.replace('ADDEND', 'm'),
    'sum-huge-start': varied(DIVISION_SUM.replace('ADDEND', 'q'), ('[0,%pre], [%sn', '[9223372036854775000,%pre], [%sn')),
    'sum-no-input-bound': varied(DIVISION_SUM.replace('ADDEND', 'q'), ('%bad = icmp ugt i64 %n, 1000000000', '%bad = icmp eq i64 %n, -1')),
    'sum-input-high-bit': varied(DIVISION_SUM.replace('ADDEND', 'q'), ('%bad = icmp ugt i64 %n, 1000000000', '%bad = icmp eq i64 %n, 0')),
    'sum-other-addend': varied(DIVISION_SUM.replace('ADDEND', 'q'), ('i64 %s, i64 %q)', 'i64 %s, i64 %n)')),
    'sum-divide-by-one': varied(DIVISION_SUM.replace('ADDEND', 'q'), ('udiv i64 %r, 5', 'udiv i64 %r, 1')),
    'sum-divide-by-two': varied(DIVISION_SUM.replace('ADDEND', 'm'), ('udiv i64 %r, 5', 'udiv i64 %r, 2'), ('urem i64 %r, 5', 'urem i64 %r, 2')),
    'sum-exact-division': varied(DIVISION_SUM.replace('ADDEND', 'q'), ('udiv i64 %r, 5', 'udiv exact i64 %r, 5')),
    'sum-other-remainder': varied(DIVISION_SUM.replace('ADDEND', 'm'), ('urem i64 %r, 5', 'urem i64 %r, 7')),
    'sum-addend-first': varied(DIVISION_SUM.replace('ADDEND', 'm'), ('i64 %s, i64 %m)', 'i64 %m, i64 %s)')),
    'sum-frozen-addend': varied(DIVISION_SUM.replace('ADDEND', 'qf'), (' %c = call', ' %qf = freeze i64 %q\n %c = call')),
    'sum-negative-seed': varied(DIVISION_SUM.replace('ADDEND', 'q'), ('[0,%pre], [%sn', '[-9223372036854775000,%pre], [%sn')),
}

HORNER_CASES = {
    'horner': HORNER,
    'horner-count-too-big': varied(HORNER, ('ugt i64 %n, 12', 'ugt i64 %n, 64')),
    'horner-count-unbounded': varied(HORNER, ('%bad = icmp ugt i64 %n, 12', '%bad = icmp eq i64 %n, -7')),
    'horner-count-may-be-zero': varied(HORNER, ('icmp ult i64 %n, 1', 'icmp ult i64 %n, 0')),
    'horner-big-factor': varied(HORNER, ('i64 %x, i64 26', 'i64 %x, i64 100000000')),
    'horner-addend-unbounded': varied(HORNER, ('%d_bad = icmp ugt i64 %d, 26', '%d_bad = icmp eq i64 %d, -1')),
    'horner-huge-start': varied(HORNER, ('[0,%pre], [%xn', '[1000000000000000000,%pre], [%xn')),
    'horner-factor-first': varied(HORNER, ('i64 %x, i64 26', 'i64 26, i64 %x')),
    'horner-addend-first': varied(HORNER, ('i64 %mv, i64 %d)', 'i64 %d, i64 %mv)')),
    'horner-negative-factor': varied(HORNER, ('i64 %x, i64 26', 'i64 %x, i64 -26')),
    'horner-count-eleven': varied(HORNER, ('ugt i64 %n, 12', 'ugt i64 %n, 11')),
    'horner-count-thirteen': varied(HORNER, ('ugt i64 %n, 12', 'ugt i64 %n, 13')),
}

INTERVAL_CASES = {
    'interval': INTERVAL,
    'interval-too-many-iterations': varied(INTERVAL, ('ugt i64 %n, 15', 'ugt i64 %n, 200')),
    'interval-no-iteration-bound': varied(INTERVAL, ('%bad = icmp ugt i64 %n, 15', '%bad = icmp eq i64 %n, -7')),
    'interval-big-sample': varied(INTERVAL, ('ugt i64 %d, 8', 'ugt i64 %d, 4611686018427387904')),
    'interval-unchecked-sample': varied(INTERVAL, ('%d_bad = icmp ugt i64 %d, 8', '%d_bad = icmp eq i64 %d, -1')),
    'interval-squared-growth': varied(INTERVAL, ('i64 %t, i64 3)', 'i64 %t, i64 %t)'), ('[%t,%cmp]', '[%qv,%cmp]'), ('[0,%reset]', '[%qv,%reset]'), ('%s = phi i64 [0,%pre]', '%s = phi i64 [2,%pre]')),
    'interval-subtract': varied(INTERVAL, ('@llvm.sadd.with.overflow.i64(i64 %s, i64 %d)', '@llvm.ssub.with.overflow.i64(i64 %s, i64 %d)')),
    'interval-shift-left': interval_step(' %u = shl i64 %t, 1'),
    'interval-shift-too-far': interval_step(' %u = shl i64 %t, 62'),
    'interval-shift-right': interval_step(' %u = lshr i64 %t, 1'),
    'interval-arithmetic-shift': interval_step(' %u = ashr i64 %t, 2'),
    'interval-divide': interval_step(' %u = udiv i64 %t, 3'),
    'interval-signed-divide': interval_step(' %u = sdiv i64 %t, 3'),
    'interval-divide-by-sample': interval_step(' %u = udiv i64 %t, %d'),
    'interval-remainder': interval_step(' %u = urem i64 %t, 7'),
    'interval-mask': interval_step(' %u = and i64 %t, 15'),
    'interval-negative-mask': interval_step(' %u = and i64 %t, -16'),
    'interval-or': interval_step(' %u = or i64 %t, 1'),
    'interval-subtract-sample': interval_step(' %u = sub i64 %t, %d'),
    'interval-multiply-sample': interval_step(' %u = mul i64 %t, %d'),
    'interval-select': interval_step(' %small = icmp ult i64 %d, 4\n %u = select i1 %small, i64 %t, i64 9'),
    'interval-sign-extend': interval_step(' %narrow = trunc i64 %t to i32\n %u = sext i32 %narrow to i64'),
    'interval-zero-extend': interval_step(' %narrow = trunc i64 %t to i32\n %u = zext i32 %narrow to i64'),
    'interval-negative-zero-extend': interval_step(' %neg = sub i64 0, %t\n %narrow = trunc i64 %neg to i8\n %u = zext i8 %narrow to i64'),
    'interval-freeze': interval_step(' %u = freeze i64 %t'),
    'interval-signed-latch': varied(INTERVAL, ('%done = icmp eq i64 %next, %n', '%done = icmp sge i64 %next, 15')),
    'interval-offset-latch': varied(INTERVAL, ('%done = icmp eq i64 %next, %n', '%done = icmp sge i64 %i, 14')),
    'interval-lower-latch': varied(INTERVAL, ('%i = phi i64 [0,%pre]', '%i = phi i64 [15,%pre]'), ('%next = add i64 %i, 1', '%next = add i64 %i, -1'), ('%done = icmp eq i64 %next, %n', '%done = icmp slt i64 %next, 1')),
    'interval-padded-fits': padded(INTERVAL, ' %q = call', 400),
    'interval-padded-too-large': padded(INTERVAL, ' %q = call', 500),
    'interval-convergent': varied(INTERVAL, ('i64 %t, i64 3)', 'i64 %t, i64 3) #0'), tail='attributes #0 = { convergent }\n'),
    'interval-opaque-metadata': varied(INTERVAL, ('i64 %t, i64 3)', 'i64 %t, i64 3), !opaque !0'), tail='!0 = !{}\n'),
    'interval-slow-marker': varied(INTERVAL, ('i64 %t, i64 3)', 'i64 %t, i64 3), !elisa.checkedmul.slow !0'), tail='!0 = !{}\n'),
}

DOWN_CASES = {
    'down': DOWN,
    'down-bound-34': varied(DOWN, ('ugt i64 %n, 33', 'ugt i64 %n, 34')),
    'down-no-bound': varied(DOWN, ('%bad = icmp ugt i64 %n, 33', '%bad = icmp eq i64 %n, -9')),
    'down-upward': varied(DOWN, ('add i64 %f, -2', 'add i64 %f, 2')),
    'down-slower-step': varied(DOWN, ('add i64 %f, -2', 'add i64 %f, -1')),
    'down-checked-step': varied(DOWN, (' %next = add i64 %f, -2', ' %nc = call {i64,i1} @llvm.ssub.with.overflow.i64(i64 %f, i64 2)\n %next = extractvalue {i64,i1} %nc, 0')),
    'down-stays-on-false': varied(DOWN, ('%more = icmp sgt i64 %f, 3\n br i1 %more, label %body, label %exit', '%more = icmp sle i64 %f, 3\n br i1 %more, label %exit, label %body')),
    'down-to-one': varied(DOWN, ('icmp sgt i64 %f, 3', 'icmp sgt i64 %f, 1')),
}

CASES = {**FACTORIAL_CASES, **DIVISION_SUM_CASES, **HORNER_CASES, **INTERVAL_CASES, **DOWN_CASES}

# Each case's (count, checked calls left, `nsw` instructions, count of a second run), from
# the C++ pass.
EXPECTED = {
    'factorial': (1, 0, 2, 0),
    'factorial-linux': (1, 0, 2, 0),
    'bound-21': (0, 1, 0, 0),
    'unbounded': (0, 1, 0, 0),
    'large-start': (0, 1, 0, 0),
    'negative-limit-start': (0, 1, 0, 0),
    'step-two': (0, 1, 0, 0),
    'non-unit-step': (0, 1, 0, 0),
    'wrong-direction': (0, 1, 0, 0),
    'other-operands': (0, 1, 0, 0),
    'sanitizer': (0, 1, 0, 0),
    'check-operands-swapped': (1, 0, 2, 0),
    'check-through-freeze': (1, 0, 2, 0),
    'multiply-through-freeze': (1, 0, 2, 0),
    'unsigned-multiply': (1, 0, 2, 0),
    'limit-swapped': (1, 0, 2, 0),
    'stays-on-true': (1, 0, 2, 0),
    'strict-stay': (1, 0, 2, 0),
    'checked-step': (2, 0, 2, 0),
    'counter-from-zero': (1, 0, 2, 0),
    'second-check': (2, 0, 2, 0),
    'check-before-multiply': (1, 0, 2, 0),
    'opaque-metadata': (1, 0, 1, 0),
    'two-functions': (1, 0, 2, 0),
    'sum-quotient': (1, 0, 1, 0),
    'sum-remainder': (1, 0, 1, 0),
    'sum-huge-start': (0, 1, 0, 0),
    'sum-no-input-bound': (0, 1, 0, 0),
    'sum-input-high-bit': (0, 1, 0, 0),
    'sum-other-addend': (0, 1, 0, 0),
    'sum-divide-by-one': (0, 1, 0, 0),
    'sum-divide-by-two': (1, 0, 1, 0),
    'sum-exact-division': (0, 1, 0, 0),
    'sum-other-remainder': (0, 1, 0, 0),
    'sum-addend-first': (1, 0, 1, 0),
    'sum-frozen-addend': (1, 0, 1, 0),
    'sum-negative-seed': (1, 0, 1, 0),
    'horner': (2, 0, 3, 0),
    'horner-count-too-big': (0, 2, 0, 0),
    'horner-count-unbounded': (0, 2, 0, 0),
    'horner-count-may-be-zero': (0, 2, 0, 0),
    'horner-big-factor': (1, 1, 2, 0),
    'horner-addend-unbounded': (0, 2, 0, 0),
    'horner-huge-start': (0, 2, 0, 0),
    'horner-factor-first': (2, 0, 3, 0),
    'horner-addend-first': (2, 0, 3, 0),
    'horner-negative-factor': (2, 0, 3, 0),
    'horner-count-eleven': (2, 0, 3, 0),
    'horner-count-thirteen': (0, 2, 0, 0),
    'interval': (3, 0, 4, 0),
    'interval-too-many-iterations': (0, 3, 0, 0),
    'interval-no-iteration-bound': (0, 3, 0, 0),
    'interval-big-sample': (1, 2, 2, 0),
    'interval-unchecked-sample': (0, 3, 0, 0),
    'interval-squared-growth': (1, 2, 2, 0),
    'interval-subtract': (3, 0, 4, 0),
    'interval-shift-left': (3, 0, 4, 0),
    'interval-shift-too-far': (2, 1, 3, 0),
    'interval-shift-right': (3, 0, 4, 0),
    'interval-arithmetic-shift': (3, 0, 4, 0),
    'interval-divide': (3, 0, 4, 0),
    'interval-signed-divide': (3, 0, 4, 0),
    'interval-divide-by-sample': (2, 1, 3, 0),
    'interval-remainder': (3, 0, 4, 0),
    'interval-mask': (3, 0, 4, 0),
    'interval-negative-mask': (3, 0, 4, 0),
    'interval-or': (2, 1, 3, 0),
    'interval-subtract-sample': (3, 0, 4, 0),
    'interval-multiply-sample': (3, 0, 4, 0),
    'interval-select': (3, 0, 4, 0),
    'interval-sign-extend': (3, 0, 4, 0),
    'interval-zero-extend': (3, 0, 4, 0),
    'interval-negative-zero-extend': (3, 0, 4, 0),
    'interval-freeze': (3, 0, 4, 0),
    'interval-signed-latch': (3, 0, 4, 0),
    'interval-offset-latch': (0, 3, 0, 0),
    'interval-lower-latch': (3, 0, 3, 0),
    'interval-padded-fits': (3, 0, 4, 0),
    'interval-padded-too-large': (0, 3, 0, 0),
    'interval-convergent': (2, 1, 3, 0),
    'interval-opaque-metadata': (2, 1, 3, 0),
    'interval-slow-marker': (3, 0, 4, 0),
    'down': (1, 0, 1, 0),
    'down-bound-34': (0, 1, 0, 0),
    'down-no-bound': (0, 1, 0, 0),
    'down-upward': (0, 1, 0, 0),
    'down-slower-step': (0, 1, 0, 0),
    'down-checked-step': (1, 1, 1, 0),
    'down-stays-on-false': (1, 0, 1, 0),
    'down-to-one': (1, 0, 1, 0),
}
