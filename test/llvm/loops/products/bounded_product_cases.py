"""IR shapes for the bounded-product proofs, shared by their test.

`bounded-products` first bounds a header phi an inexact `udiv` by a constant shrinks to
zero (assuming its entry maximum) and the checked counters its loop advances (assuming
their reachable range, and turning the checked add into `add nsw`). With those facts it
proves that an inner loop counted to a limit of at most 16 multiplies a phi by a defined
invariant base without leaving the width: the multiply gains `nsw` and the matching
`smul.with.overflow` calls it dominates fold to it. bounded_product_fixture.ll is the
scan-power loop the proofs were written for; each case varies it, or is the header-counter
fixture. Each case's count and what it leaves are what the C++ pass did with the same
shapes (see EXPECTED), except where two of its flaws are fixed: a proved base's freeze is
removed (the C++ pass kept every one), and base-quotient is proved from the assumptions
the first phase adds (the C++ pass's stale assumption cache missed them).
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAC = 'arm64-apple-darwin27.2.0'
LINUX = 'aarch64-unknown-linux-gnu'
FIXTURE = (HERE / 'bounded_product_fixture.ll').read_text().replace(LINUX, MAC)
HEADER_COUNTER = (HERE / 'bounded_product_header_counter.ll').read_text().replace(LINUX, MAC)
FREEZE = ' %frozen_base = freeze i64 %base\n'


def varied(*replacements, tail=''):
    """The fixture with each (old, new) replacement made once."""
    text = FIXTURE
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new, 1)
    return text + tail


def derived_base(definition):
    """The fixture with the frozen base computed in `pre`, where the inner loop sees it
    as an invariant, by DEFINITION (which defines %derived)."""
    return varied((FREEZE, ''), (' %positive = icmp', definition + ' %frozen_base = freeze i64 %derived\n %positive = icmp'))


def renamed(text, name):
    return text.replace('@scan_power(', f'@{name}(')


def many_functions(count):
    body = '\ndefine ' + FIXTURE.split('\ndefine ', 1)[1]
    head = FIXTURE.split('\ndefine ', 1)[0]
    return head + ''.join(renamed(body, f'scan_power_{index}') for index in range(count))


def padded(count):
    """The fixture with COUNT unused adds in the entry block."""
    padding = ''.join(f' %pad{index} = add i64 %n, {index}\n' for index in range(count))
    return varied((' %shift = add', padding + ' %shift = add'))


def extra_counters(count):
    """COUNT more checked counters advanced beside %position."""
    phis = ''.join(f' %c{index} = phi i64 [0,%entry], [%c{index}.next,%next]\n' for index in range(count))
    updates = ''.join(f' %c{index}.pair = call {{i64,i1}} @llvm.sadd.with.overflow.i64(i64 %c{index}, i64 1)\n'
                      f' %c{index}.next = extractvalue {{i64,i1}} %c{index}.pair, 0\n' for index in range(count))
    return varied((' %done = icmp eq i64 %remaining, 0\n', phis + ' %done = icmp eq i64 %remaining, 0\n'),
                  (' %pair = call', updates + ' %pair = call'))


SLOW_CALL = 'i64 %value, i64 %frozen_base)'
CASES = {
    'safe': FIXTURE,
    'linux': FIXTURE.replace(MAC, LINUX),
    'large-base': varied(('srem i64 %base_arg, 10', 'srem i64 %base_arg, 2147483647')),
    'unknown-base-definedness': varied(('i64 noundef %base_arg', 'i64 %base_arg')),
    'unknown-counter-definedness': varied(('i64 noundef %pos', 'i64 %pos')),
    'unknown-seed-definedness': varied(('i64 noundef %n', 'i64 %n')),
    'unsigned-poison-flag': varied(('%low = mul i64', '%low = mul nuw i64')),
    'non-unit-exponent': varied(('%exponent, 1', '%exponent, 2')),
    'sanitizer': varied(('%base_arg) {', '%base_arg) sanitize_address {')),
    'optnone': varied(('%base_arg) {', '%base_arg) noinline optnone {')),
    'minsize': varied(('%base_arg) {', '%base_arg) minsize {')),
    'unknown-metadata': varied((SLOW_CALL, SLOW_CALL + ', !opaque !0'), tail='\n!0 = !{}\n'),
    'slow-marker': varied((SLOW_CALL, SLOW_CALL + ', !elisa.checkedmul.slow !0'), tail='\n!0 = !{}\n'),
    'slow-marker-and-opaque': varied((SLOW_CALL, SLOW_CALL + ', !elisa.checkedmul.slow !0, !opaque !0'), tail='\n!0 = !{}\n'),
    'unbounded-counter': varied(('%pos_shift, 7', '%pos_shift, 100')),
    'counter-to-sixteen': varied(('%pos_shift, 7', '%pos_shift, 15')),
    'counter-to-seventeen': varied(('%pos_shift, 7', '%pos_shift, 16')),
    'earlier-freeze-use': varied(('%low = mul', '%early_use = add i64 %frozen_base, 1\n %low = mul')),
    'no-freeze': varied((FREEZE, ''), ('%value, %frozen_base', '%value, %base'), (SLOW_CALL, 'i64 %value, i64 %base)'),
                        ('icmp ult i64 %frozen_base', 'icmp ult i64 %base')),
    'multiply-swapped': varied(('mul i64 %value, %frozen_base', 'mul i64 %frozen_base, %value')),
    'call-swapped': varied((SLOW_CALL, 'i64 %frozen_base, i64 %value)')),
    'call-before-multiply': varied((' %low = mul i64 %value, %frozen_base\n', ''),
                                   (' %product = call', ' %product = call'),
                                   (' %overflow = extractvalue', ' %low = mul i64 %value, %frozen_base\n %overflow = extractvalue'),
                                   ('[1,%pre], [%low,%latch]\n %frozen', '[1,%pre], [%next_value,%latch]\n %frozen'),
                                   (' %cheap = icmp', ' %cheap_value = mul i64 %value, %frozen_base\n %cheap = icmp'),
                                   ('%increment = add nuw', '%next_value = phi i64 [%cheap_value,%power], [%low,%slow]\n %increment = add nuw'),
                                   ('[1,%pre], [%low,%latch]\n %sum_next', '[1,%pre], [%next_value,%latch]\n %sum_next')),
    'variant-base': varied((' %low = mul i64 %value, %frozen_base', ' %moved = add i64 %exponent, 2\n %low = mul i64 %value, %moved'),
                           (SLOW_CALL, 'i64 %value, i64 %moved)')),
    'second-power': varied(('%value = phi i64 [1,%pre], [%low,%latch]\n', '%value = phi i64 [1,%pre], [%low,%latch]\n %other = phi i64 [3,%pre], [%other_low,%latch]\n'),
                           (' %cheap = icmp', ' %other_low = mul i64 %other, %frozen_base\n %cheap = icmp'),
                           (' %overflow = extractvalue', ' %other_product = call {i64,i1} @llvm.smul.with.overflow.i64(i64 %other, i64 %frozen_base)\n %overflow = extractvalue'),
                           ('%sum_next = add i64 %sum, %power_result', '%other_result = phi i64 [3,%pre], [%other_low,%latch]\n %mixed = add i64 %power_result, %other_result\n %sum_next = add i64 %sum, %mixed')),
    'outer-not-equal': varied(('%done = icmp eq i64 %remaining, 0\n br i1 %done, label %exit, label %pre', '%done = icmp ne i64 %remaining, 0\n br i1 %done, label %pre, label %exit')),
    'latch-not-equal': varied(('%power_done = icmp eq i64 %increment, %position\n br i1 %power_done, label %after_power, label %power',
                               '%power_done = icmp ne i64 %increment, %position\n br i1 %power_done, label %power, label %after_power')),
    'latch-limit-first': varied(('icmp eq i64 %increment, %position', 'icmp eq i64 %position, %increment')),
    'divide-by-one': varied(('udiv i64 %remaining, 10', 'udiv i64 %remaining, 1')),
    'divide-by-two': varied(('udiv i64 %remaining, 10', 'udiv i64 %remaining, 2')),
    'divide-by-hundred': varied(('udiv i64 %remaining, 10', 'udiv i64 %remaining, 100')),
    'divide-wide-constant': varied(('udiv i64 %remaining, 10', 'udiv i64 %remaining, 8589934592')),
    'exact-division': varied(('udiv i64 %remaining, 10', 'udiv exact i64 %remaining, 10')),
    'seventeen-digit-seed': varied(('add i64 %n, -100000000', 'add i64 %n, -100000000000000000'), ('-99999999\n', '-99999999999999999\n')),
    'sixteen-digit-seed': varied(('add i64 %n, -100000000', 'add i64 %n, -10000000000000000'), ('-99999999\n', '-9999999999999999\n')),
    'counter-ascending': varied(('i64 %position, i64 -1)', 'i64 %position, i64 1)')),
    'counter-step-first': varied(('i64 %position, i64 -1)', 'i64 -1, i64 %position)')),
    'counter-step-variable': varied(('i64 %position, i64 -1)', 'i64 %position, i64 %pos_shift)')),
    'counter-unsigned-add': varied(('@llvm.sadd.with.overflow.i64(i64 %position', '@llvm.uadd.with.overflow.i64(i64 %position'),
                                   ('declare {i64,i1} @llvm.smul', 'declare {i64,i1} @llvm.uadd.with.overflow.i64(i64,i64)\ndeclare {i64,i1} @llvm.smul')),
    'counter-metadata': varied(('i64 %position, i64 -1)', 'i64 %position, i64 -1), !opaque !0'), tail='\n!0 = !{}\n'),
    'counter-overflow-reachable': varied(('%pos_shift = add i64 %pos, -1\n %bad_pos = icmp ugt i64 %pos_shift, 7',
                                          '%pos_shift = add i64 %pos, 9223372036854775800\n %bad_pos = icmp ugt i64 %pos_shift, 7')),
    'two-counters': extra_counters(1),
    'five-counters': extra_counters(4),
    'base-counter-add': derived_base(' %derived = add nsw i64 %position, 1\n'),
    'base-counter-add-unsigned': derived_base(' %derived = add nuw i64 %position, 1\n'),
    'base-counter-sub': derived_base(' %derived = sub nsw i64 %position, 1\n'),
    'base-counter-multiply': derived_base(' %derived = mul nsw i64 %position, %position\n'),
    'base-counter-multiply-unsigned': derived_base(' %derived = mul nuw i64 %position, 3\n'),
    'base-counter-and': derived_base(' %derived = and i64 %position, 7\n'),
    'base-counter-select': derived_base(' %small = icmp samesign ult i64 %position, 4\n %derived = select i1 %small, i64 %position, i64 3\n'),
    'base-counter-compare': derived_base(' %small = icmp samesign ult i64 %position, 4\n %derived = zext i1 %small to i64\n'),
    'base-counter-signed-compare': derived_base(' %small = icmp ult i64 %position, 4\n %derived = zext i1 %small to i64\n'),
    'base-counter-truncate': derived_base(' %narrow = trunc i64 %position to i32\n %derived = sext i32 %narrow to i64\n'),
    'base-counter-truncate-flagged': derived_base(' %narrow = trunc nsw i64 %position to i32\n %derived = sext i32 %narrow to i64\n'),
    'base-quotient': derived_base(' %derived = udiv i64 %remaining, 10000000\n'),
    'base-quotient-exact': derived_base(' %derived = udiv exact i64 %remaining, 10000000\n'),
    'base-remaining-phi': derived_base(' %derived = urem i64 %remaining, 7\n'),
    'base-plus-one': derived_base(' %derived = add nsw i64 %base, 1\n'),
    'base-plus-one-unsigned': derived_base(' %derived = add nuw i64 %base, 1\n'),
    'base-minus-one-unsigned': derived_base(' %derived = sub nuw i64 %base, 1\n'),
    'base-doubled': derived_base(' %derived = mul nsw i64 %base, 2\n'),
    'base-argument-plus-one': derived_base(' %derived = add nsw i64 %base_arg, 1\n'),
    'base-select': derived_base(' %plus = add nsw i64 %base, 1\n %derived = select i1 %bad_pos, i64 %plus, i64 2\n'),
    'base-samesign-compare': derived_base(' %plus = add nsw i64 %base, 1\n %small = icmp samesign ult i64 %plus, 4\n %derived = select i1 %small, i64 %plus, i64 3\n'),
    'base-compare': derived_base(' %plus = add nsw i64 %base, 1\n %small = icmp ult i64 %plus, 4\n %derived = select i1 %small, i64 %plus, i64 3\n'),
    'base-cast-chain': derived_base(' %narrow = trunc i64 %base to i32\n %plus = add nsw i32 %narrow, 1\n %derived = sext i32 %plus to i64\n'),
    'base-flagged-cast': derived_base(' %plus = add nsw i64 %base, 1\n %narrow = trunc nsw i64 %plus to i32\n %derived = sext i32 %narrow to i64\n'),
    'base-quotient-of-base': derived_base(' %plus = add nsw i64 %base, 9\n %derived = udiv i64 %plus, 2\n'),
    'base-deep-chain': derived_base(''.join(f' %step{index} = add nsw i64 %{"base" if index == 0 else f"step{index - 1}"}, 0\n' for index in range(8)) + ' %derived = add nsw i64 %step7, 0\n'),
    'padded-800': padded(762),
    'padded-801': padded(763),
    'header-counter': HEADER_COUNTER,
    'functions-33': many_functions(33),
}

# What the C++ pass did with each case: (count, smul calls, sadd calls, assumes, `mul nsw`,
# freezes) -- see test_bounded_products.shape.
EXPECTED = {
    'safe': (3, 0, 0, 2, 1, 0, 0),
    'linux': (3, 0, 0, 2, 1, 0, 0),
    'large-base': (2, 1, 0, 2, 0, 1, 0),
    'unknown-base-definedness': (2, 1, 0, 2, 0, 1, 0),
    'unknown-counter-definedness': (1, 1, 1, 1, 0, 1, 1),
    'unknown-seed-definedness': (0, 1, 1, 0, 0, 1, 0),
    'unsigned-poison-flag': (2, 1, 0, 2, 0, 1, 0),
    'non-unit-exponent': (2, 1, 0, 2, 0, 1, 0),
    'sanitizer': (0, 1, 1, 0, 0, 1, 0),
    'optnone': (0, 1, 1, 0, 0, 1, 0),
    'minsize': (0, 1, 1, 0, 0, 1, 0),
    'unknown-metadata': (2, 1, 0, 2, 0, 1, 0),
    'slow-marker': (3, 0, 0, 2, 1, 0, 0),
    'slow-marker-and-opaque': (2, 1, 0, 2, 0, 1, 0),
    'unbounded-counter': (2, 1, 0, 2, 0, 1, 0),
    'counter-to-sixteen': (2, 1, 0, 2, 0, 1, 0),
    'counter-to-seventeen': (2, 1, 0, 2, 0, 1, 0),
    'earlier-freeze-use': (3, 0, 0, 2, 1, 1, 0),
    'no-freeze': (3, 0, 0, 2, 1, 0, 0),
    'multiply-swapped': (3, 0, 0, 2, 1, 0, 0),
    'call-swapped': (3, 0, 0, 2, 1, 0, 0),
    'call-before-multiply': (2, 1, 0, 2, 0, 1, 0),
    'variant-base': (2, 1, 0, 2, 0, 1, 0),
    'second-power': (4, 0, 0, 2, 2, 0, 0),
    'outer-not-equal': (3, 0, 0, 2, 1, 0, 0),
    'latch-not-equal': (3, 0, 0, 2, 1, 0, 0),
    'latch-limit-first': (3, 0, 0, 2, 1, 0, 0),
    'divide-by-one': (0, 1, 1, 0, 0, 1, 0),
    'divide-by-two': (0, 1, 1, 0, 0, 1, 0),
    'divide-by-hundred': (3, 0, 0, 2, 1, 0, 0),
    'divide-wide-constant': (0, 1, 1, 0, 0, 1, 0),
    'exact-division': (0, 1, 1, 0, 0, 1, 0),
    'seventeen-digit-seed': (0, 1, 1, 0, 0, 1, 0),
    'sixteen-digit-seed': (3, 0, 0, 2, 1, 0, 0),
    'counter-ascending': (2, 1, 0, 2, 0, 1, 0),
    'counter-step-first': (3, 0, 0, 2, 1, 0, 0),
    'counter-step-variable': (1, 1, 1, 1, 0, 1, 1),
    'counter-unsigned-add': (1, 1, 1, 1, 0, 1, 1),
    'counter-metadata': (1, 1, 1, 1, 0, 1, 1),
    'counter-overflow-reachable': (2, 1, 0, 2, 0, 1, 0),
    'two-counters': (4, 0, 0, 3, 1, 0, 0),
    'five-counters': (6, 0, 1, 5, 1, 0, 2),
    'base-counter-add': (2, 1, 0, 2, 0, 1, 0),
    'base-counter-add-unsigned': (2, 1, 0, 2, 0, 1, 0),
    'base-counter-sub': (2, 1, 0, 2, 0, 1, 0),
    'base-counter-multiply': (2, 1, 0, 2, 1, 1, 0),
    'base-counter-multiply-unsigned': (2, 1, 0, 2, 0, 1, 0),
    'base-counter-and': (2, 1, 0, 2, 0, 1, 0),
    'base-counter-select': (2, 1, 0, 2, 0, 1, 0),
    'base-counter-compare': (2, 1, 0, 2, 0, 1, 0),
    'base-counter-signed-compare': (2, 1, 0, 2, 0, 1, 0),
    'base-counter-truncate': (2, 1, 0, 2, 0, 1, 0),
    'base-counter-truncate-flagged': (2, 1, 0, 2, 0, 1, 0),
    'base-quotient': (3, 0, 0, 2, 1, 0, 0),
    'base-quotient-exact': (2, 1, 0, 2, 0, 1, 0),
    'base-remaining-phi': (2, 1, 0, 2, 0, 1, 0),
    'base-plus-one': (3, 0, 0, 2, 1, 0, 0),
    'base-plus-one-unsigned': (2, 1, 0, 2, 0, 1, 0),
    'base-minus-one-unsigned': (2, 1, 0, 2, 0, 1, 0),
    'base-doubled': (2, 1, 0, 2, 1, 1, 0),
    'base-argument-plus-one': (2, 1, 0, 2, 0, 1, 0),
    'base-select': (3, 0, 0, 2, 1, 0, 0),
    'base-samesign-compare': (2, 1, 0, 2, 0, 1, 0),
    'base-compare': (2, 1, 0, 2, 0, 1, 0),
    'base-cast-chain': (2, 1, 0, 2, 0, 1, 0),
    'base-flagged-cast': (2, 1, 0, 2, 0, 1, 0),
    'base-quotient-of-base': (2, 1, 0, 2, 0, 1, 0),
    'base-deep-chain': (2, 1, 0, 2, 0, 1, 0),
    'padded-800': (3, 0, 0, 2, 1, 0, 0),
    'padded-801': (0, 1, 1, 0, 0, 1, 0),
    'header-counter': (1, 0, 1, 1, 0, 0, 1),
    'functions-33': (96, 1, 1, 64, 32, 1, 3),
}
