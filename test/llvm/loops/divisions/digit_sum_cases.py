"""IR shapes for the bounded-division-sum elision, shared by its test.

`bounded-division-sums` proves the checked sum of the remainders of a divide-down loop:
`while n > 0: total += n srem B; n = n sdiv B` from a zero total. A positive W-bit `n`
reaches zero within W-1 divisions and each remainder is at most B-1, so the sum fits
whenever (W-1)*(B-1) does. The fixture is that loop; each case varies one part, and its
count is what the C++ pass did with the same shape (see EXPECTED). The exhaustive fixture
covers every divisor from 2 to 20 over i8.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRIPLE = 'arm64-apple-darwin27.2.0'
# Digit sums of every signed 8-bit input for divisors 2 to 20, and one with a nonzero
# start that must keep its check (digit_sum_exhaustive.c prints them all).
EXHAUSTIVE = (HERE / 'digit_sum_exhaustive.ll').read_text()
DIGITS = f'target triple = "{TRIPLE}"\n\n' + '''define i64 @digits(i64 %x) {
entry:
  br label %head
head:
  %n = phi i64 [%x, %entry], [%q, %next]
  %total = phi i64 [0, %entry], [%sum, %next]
  %more = icmp sgt i64 %n, 0
  br i1 %more, label %body, label %exit
body:
  %r = srem i64 %n, 10
  %call = call {i64, i1} @llvm.sadd.with.overflow.i64(i64 %total, i64 %r)
  %sum = extractvalue {i64, i1} %call, 0
  %overflow = extractvalue {i64, i1} %call, 1
  br i1 %overflow, label %trap, label %next
next:
  %q = sdiv i64 %n, 10
  br label %head
trap:
  call void @llvm.trap()
  unreachable
exit:
  ret i64 %total
}

declare {i64, i1} @llvm.sadd.with.overflow.i64(i64, i64)
declare void @llvm.trap()
'''


def varied(text, *replacements):
    """TEXT with each (old, new) replacement made everywhere."""
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    return text


def narrowed(width, base):
    """The fixture over iW with divisor BASE."""
    return varied(DIGITS, ('i64', f'i{width}'), ('srem i' + str(width) + ' %n, 10', f'srem i{width} %n, {base}'), ('sdiv i' + str(width) + ' %n, 10', f'sdiv i{width} %n, {base}'))


MEMORY = f'target triple = "{TRIPLE}"\n\n' + '''define i64 @digits(i64 %x) {
entry:
  %n.slot = alloca i64
  %total.slot = alloca i64
  store i64 %x, ptr %n.slot
  store i64 0, ptr %total.slot
  br label %head
head:
  %n = load i64, ptr %n.slot
  %more = icmp sgt i64 %n, 0
  br i1 %more, label %body, label %exit
body:
  %total = load i64, ptr %total.slot
  %r = srem i64 %n, 10
  %call = call {i64, i1} @llvm.sadd.with.overflow.i64(i64 %total, i64 %r)
  %sum = extractvalue {i64, i1} %call, 0
  %overflow = extractvalue {i64, i1} %call, 1
  br i1 %overflow, label %trap, label %next
next:
  store i64 %sum, ptr %total.slot
  %q = sdiv i64 %n, 10
  store i64 %q, ptr %n.slot
  br label %head
trap:
  call void @llvm.trap()
  unreachable
exit:
  %result = load i64, ptr %total.slot
  ret i64 %result
}

declare {i64, i1} @llvm.sadd.with.overflow.i64(i64, i64)
declare void @llvm.trap()
'''
TWO_ENTRIES = varied(DIGITS, ('entry:\n  br label %head', 'entry:\n  %odd = trunc i64 %x to i1\n  br i1 %odd, label %head, label %side\nside:\n  br label %head'), ('[%x, %entry], [%q, %next]', '[%x, %entry], [%x, %side], [%q, %next]'), ('[0, %entry], [%sum, %next]', '[0, %entry], [0, %side], [%sum, %next]'))
NESTED = varied(DIGITS, ('[%x, %entry]', '[%x, %outer]'), ('[0, %entry]', '[0, %outer]'), ('define i64 @digits(i64 %x) {\nentry:\n  br label %head', 'define i64 @digits(i64 %x) {\nentry:\n  br label %outer\nouter:\n  %round = phi i64 [0, %entry], [%round.next, %exit]\n  br label %head'), ('exit:\n  ret i64 %total', 'exit:\n  %round.next = add i64 %round, 1\n  %again = icmp ult i64 %round.next, 3\n  br i1 %again, label %outer, label %done\ndone:\n  ret i64 %total'))
SECOND = DIGITS[DIGITS.index('define'):DIGITS.index('declare')].replace('@digits(', '@digits2(')

CASES = {
    'digits': DIGITS,
    'memory': MEMORY,
    'two-entries': TWO_ENTRIES,
    'nested': NESTED,
    'two-functions': DIGITS + SECOND,
    'base-two': varied(DIGITS, ('%n, 10', '%n, 2')),
    'base-one': varied(DIGITS, ('%n, 10', '%n, 1')),
    'base-negative': varied(DIGITS, ('%n, 10', '%n, -10')),
    'base-huge': varied(DIGITS, ('%n, 10', '%n, 146402730743726602')),
    'base-largest': varied(DIGITS, ('%n, 10', '%n, 146402730743726601')),
    'i8-base-19': narrowed(8, 19),
    'i8-base-20': narrowed(8, 20),
    'i3-base-2': narrowed(3, 2),
    'i32-base-10': narrowed(32, 10),
    'sum-first': varied(DIGITS, ('(i64 %total, i64 %r)', '(i64 %r, i64 %total)')),
    'other-divisor-remainder': varied(DIGITS, ('srem i64 %n, 10', 'srem i64 %n, 7')),
    'remainder-of-input': varied(DIGITS, ('srem i64 %n, 10', 'srem i64 %x, 10')),
    'unsigned-division': varied(DIGITS, ('sdiv i64 %n, 10', 'udiv i64 %n, 10')),
    'unsigned-remainder': varied(DIGITS, ('srem i64 %n, 10', 'urem i64 %n, 10')),
    'guard-sge': varied(DIGITS, ('icmp sgt i64 %n, 0', 'icmp sge i64 %n, 0')),
    'guard-one': varied(DIGITS, ('icmp sgt i64 %n, 0', 'icmp sgt i64 %n, 1')),
    'guard-inverted': varied(DIGITS, ('br i1 %more, label %body, label %exit', 'br i1 %more, label %exit, label %body'), ('icmp sgt i64 %n, 0', 'icmp sle i64 %n, 0')),
    'nonzero-start': varied(DIGITS, ('[0, %entry]', '[5, %entry]')),
    'overflow-field': varied(DIGITS, ('%sum = extractvalue {i64, i1} %call, 0', '%sum.bit = extractvalue {i64, i1} %call, 1\n  %sum = zext i1 %sum.bit to i64')),
    'checked-subtract': varied(DIGITS, ('@llvm.sadd.with.overflow', '@llvm.ssub.with.overflow')),
    'unchecked-sum': varied(DIGITS, ('%call = call {i64, i1} @llvm.sadd.with.overflow.i64(i64 %total, i64 %r)\n  %sum = extractvalue {i64, i1} %call, 0\n  %overflow = extractvalue {i64, i1} %call, 1\n  br i1 %overflow, label %trap, label %next', '%sum = add i64 %total, %r\n  br label %next')),
    'optsize': varied(DIGITS, ('@digits(i64 %x) {', '@digits(i64 %x) optsize {')),
    'no-remainder': varied(DIGITS, ('srem i64 %n, 10', 'and i64 %n, 7')),
    'exhaustive': EXHAUSTIVE,
}

# What the C++ pass did with each shape: the count (functions put through mem2reg and
# loop-simplify), the checked adds and subtractions left, the `proved.digit.sum` adds made,
# and the count of a second run.
EXPECTED = {
    'digits': (1, 0, 1, 0),
    'memory': (1, 0, 1, 0),
    'two-entries': (1, 0, 1, 0),
    'nested': (1, 0, 1, 0),
    'two-functions': (2, 0, 2, 0),
    'base-two': (1, 0, 1, 0),
    'base-one': (1, 1, 0, 1),
    'base-negative': (1, 1, 0, 1),
    'base-huge': (1, 1, 0, 1),
    'base-largest': (1, 0, 1, 0),
    'i8-base-19': (1, 0, 1, 0),
    'i8-base-20': (1, 1, 0, 1),
    'i3-base-2': (1, 0, 1, 0),
    'i32-base-10': (1, 0, 1, 0),
    'sum-first': (1, 0, 1, 0),
    'other-divisor-remainder': (1, 1, 0, 1),
    'remainder-of-input': (1, 1, 0, 1),
    'unsigned-division': (0, 1, 0, 0),
    'unsigned-remainder': (0, 1, 0, 0),
    'guard-sge': (1, 1, 0, 1),
    'guard-one': (1, 1, 0, 1),
    'guard-inverted': (1, 1, 0, 1),
    'nonzero-start': (1, 1, 0, 1),
    'overflow-field': (1, 1, 0, 1),
    'checked-subtract': (0, 1, 0, 0),
    'unchecked-sum': (0, 0, 0, 0),
    'optsize': (0, 1, 0, 0),
    'no-remainder': (0, 1, 0, 0),
    'exhaustive': (22, 4, 18, 4),
}
