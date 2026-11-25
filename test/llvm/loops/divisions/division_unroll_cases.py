"""IR shapes for the bounded unsigned-division unroll, shared by its test.

`bounded-division-unroll` unrolls a two-block loop that divides a value by a constant
until it drops below the divisor (or reaches zero), when the value's range on the entry
edge bounds the trips. With a defined seed and an inexact division it also assumes the
value stays at most its entry maximum, and turns a checked constant counter whose every
update fits into an `add nsw`. Each case's count, and what it leaves, are what the C++
pass did with the same shapes (see EXPECTED).
"""
MAC = 'arm64-apple-darwin27.2.0'
X86 = 'x86_64-apple-macosx14.0.0'

HEADER = '''declare {i64, i1} @llvm.sadd.with.overflow.i64(i64, i64)
declare {i64, i1} @llvm.uadd.with.overflow.i64(i64, i64)
declare {i32, i1} @llvm.sadd.with.overflow.i32(i32, i32)
declare {i128, i1} @llvm.sadd.with.overflow.i128(i128, i128)
declare void @llvm.trap()
declare void @sink(i64)
'''


def count_digits(name='count_with_offset', width='i64', divisor='10', low='-100000000', span='-99999999',
                 exit_test='ult', step='1', seed=None, attributes='', loop_metadata='', extra_body='',
                 checked='sadd', division='udiv', defined=''):
    """Count the decimal digits of N above OFFSET with a checked counter. The loop
    leaves when the value drops below the divisor, or with EXIT_TEST 'ne' when it
    reaches zero."""
    test = f'icmp ult {width} %digits, {divisor}' if exit_test == 'ult' else f'icmp ne {width} %digits, 0'
    branch = 'label %exit, label %body' if exit_test == 'ult' else 'label %body, label %exit'
    initial = f'[{{{width} {seed}, i1 false}}, %entry]' if seed is not None else '[%initial, %entry]'
    return f'''define {width} @{name}({width} {defined}%n, {width} %offset) {attributes} {{
entry:
 %shift = add {width} %n, {low}
 %invalid = icmp ult {width} %shift, {span}
 %initial0 = insertvalue {{{width},i1}} poison, {width} %offset, 0
 %initial = insertvalue {{{width},i1}} %initial0, i1 false, 1
 br i1 %invalid, label %bad, label %head
head:
 %digits = phi {width} [%n, %entry], [%div, %body]
 %counter = phi {{{width},i1}} {initial}, [%checked, %body]
 %count = extractvalue {{{width},i1}} %counter, 0
 %done = {test}
 br i1 %done, {branch}
body:
 %div = {division} {width} %digits, {divisor}
{extra_body} %checked = call {{{width},i1}} @llvm.{checked}.with.overflow.{width}({width} %count, {width} {step})
 %overflow = extractvalue {{{width},i1}} %checked, 1
 br i1 %overflow, label %trap, label %head{loop_metadata}
trap:
 call void @llvm.trap()
 unreachable
exit:
 ret {width} %count
bad:
 ret {width} -1
}}
'''


def module(*functions, triple=MAC, tail=''):
    return f'target triple = "{triple}"\n' + HEADER + ''.join(functions) + tail


BASE = count_digits()
DISABLED = '\n!0 = distinct !{!0, !1}\n!1 = !{!"llvm.loop.unroll.disable"}\n'
CYCLE = '\n!0 = distinct !{!0, !1}\n!1 = distinct !{!1}\n'
MUSTPROGRESS = '\n!0 = distinct !{!0, !1}\n!1 = !{!"llvm.loop.mustprogress"}\n'
MAXIMUM, MINIMUM = 2**63 - 1, -(2**63)


def constant_counter(seed, step):
    return module(count_digits(seed=seed, step=step, defined='noundef '))


def unguarded():
    """The digit count of any N: no entry range bounds the trips."""
    return BASE.replace(' br i1 %invalid, label %bad, label %head', ' br label %head')


def many_functions(count):
    return module(*[count_digits(name=f'count{index}') for index in range(count)])


CASES = {
    'base': module(BASE),
    'disable': module(count_digits(loop_metadata=', !llvm.loop !0'), tail=DISABLED),
    'metadata-cycle': module(count_digits(loop_metadata=', !llvm.loop !0'), tail=CYCLE),
    'mustprogress': module(count_digits(loop_metadata=', !llvm.loop !0'), tail=MUSTPROGRESS),
    'signed': module(count_digits(division='sdiv')),
    'divisor-one': module(count_digits(divisor='1')),
    'divisor-two': module(count_digits(divisor='2')),
    'divisor-two-small': module(count_digits(divisor='2', low='-1000', span='-999')),
    'divisor-large': module(count_digits(divisor='4294967296')),
    'sanitize': module(count_digits(attributes='sanitize_address')),
    'optnone': module(count_digits(attributes='noinline optnone')),
    'optsize': module(count_digits(attributes='optsize')),
    'x86': module(BASE, triple=X86),
    'positive': constant_counter(0, 1),
    'negative': constant_counter(17, -3),
    'maximum-safe': constant_counter(MAXIMUM - 7, 1),
    'maximum-trap': constant_counter(MAXIMUM - 6, 1),
    'minimum-safe': constant_counter(MINIMUM + 7, -1),
    'minimum-trap': constant_counter(MINIMUM + 6, -1),
    'unknown-definedness': module(count_digits(seed=0)),
    'exact-division': module(count_digits(seed=0, defined='noundef ', division='udiv exact')),
    'zero-test': module(count_digits(exit_test='ne')),
    'zero-test-defined': module(count_digits(exit_test='ne', seed=0, defined='noundef ')),
    'unsigned-counter': module(count_digits(checked='uadd', seed=0, defined='noundef ')),
    'unbounded': module(unguarded()),
    'width-32': module(count_digits(width='i32', low='-100000', span='-99999')),
    'width-128': module(count_digits(width='i128', seed=0, defined='noundef ')),
    'store-in-loop': module(count_digits(extra_body=' call void @sink(i64 %div)\n')),
    'two-loops': module(count_digits(name='first'), count_digits(name='second')),
    'functions-33': many_functions(33),
    'trips-at-16': module(count_digits(low='-100000000000000000', span='-99999999999999999')),
    'trips-over-16': module(count_digits(low='-1000000000000000000', span='-999999999999999999')),
}

# What the C++ pass did with each case: (count, udiv instructions, assumes, checked
# adds, `add nsw` counters, traps) -- see test_division_unroll.shape.
EXPECTED = {
    'base': (2, 8, 0, 8, 0, 1),
    'disable': (0, 1, 0, 1, 0, 1),
    'divisor-large': (0, 1, 0, 1, 0, 1),
    'divisor-one': (0, 1, 0, 1, 0, 1),
    'divisor-two-small': (2, 10, 0, 10, 0, 1),
    'divisor-two': (0, 1, 0, 1, 0, 1),
    'exact-division': (2, 8, 0, 8, 0, 1),
    'functions-33': (24, 117, 0, 117, 0, 33),
    'maximum-safe': (4, 8, 8, 0, 8, 1),
    'maximum-trap': (3, 6, 7, 0, 0, 1),
    'metadata-cycle': (0, 1, 0, 1, 0, 1),
    'minimum-safe': (4, 8, 8, 0, 8, 1),
    'minimum-trap': (3, 6, 7, 0, 0, 1),
    'mustprogress': (2, 8, 0, 8, 0, 1),
    'negative': (4, 8, 8, 0, 8, 1),
    'optnone': (0, 1, 0, 1, 0, 1),
    'optsize': (0, 1, 0, 1, 0, 1),
    'positive': (4, 8, 8, 0, 8, 1),
    'sanitize': (0, 1, 0, 1, 0, 1),
    'signed': (0, 0, 0, 1, 0, 1),
    'store-in-loop': (0, 1, 0, 1, 0, 1),
    'trips-at-16': (2, 16, 0, 16, 0, 1),
    'trips-over-16': (0, 1, 0, 1, 0, 1),
    'two-loops': (4, 16, 0, 16, 0, 2),
    'unbounded': (0, 1, 0, 1, 0, 1),
    'unknown-definedness': (2, 8, 0, 8, 0, 1),
    'unsigned-counter': (3, 8, 8, 8, 0, 1),
    'width-128': (4, 8, 8, 0, 8, 1),
    'width-32': (2, 5, 0, 5, 0, 1),
    'x86': (2, 8, 0, 8, 0, 1),
    'zero-test-defined': (4, 9, 9, 0, 9, 1),
    'zero-test': (2, 9, 0, 9, 0, 1),
}
