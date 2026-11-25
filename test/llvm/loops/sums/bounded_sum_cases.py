"""IR shapes for the bounded-sum proofs, shared by their tests.

`bounded-sums` proves a zero- or nonnegative-seeded recurrence `sum += step` from the
step's nonnegative range and the loop's maximum trip count, then drops the overflow
check of its checked add (or marks its plain add `nuw nsw`), and reuses the proven
range for nearby checked adds, checked subtractions and plain subtractions. Each
case's count and what it leaves are what the C++ pass did with the same shapes (see
EXPECTED). The functions of bounded_sum_fixture.ll are cases too.
"""
from pathlib import Path

FIXTURE = (Path(__file__).resolve().parent / 'bounded_sum_fixture.ll').read_text()
HEADER = '''declare { i8, i1 } @llvm.sadd.with.overflow.i8(i8, i8)
declare { i8, i1 } @llvm.ssub.with.overflow.i8(i8, i8)
declare { i32, i1 } @llvm.sadd.with.overflow.i32(i32, i32)
declare { i128, i1 } @llvm.sadd.with.overflow.i128(i128, i128)
declare { i129, i1 } @llvm.sadd.with.overflow.i129(i129, i129)
declare void @llvm.trap()
declare i8 @llvm.smin.i8(i8, i8)
declare i1 @choose()
'''


def fixture_function(name):
    """One function of the fixture, with the fixture's declarations."""
    body = '\ndefine ' + FIXTURE.split('\ndefine ', 1)[1]
    for chunk in body.split('\ndefine ')[1:]:
        if chunk.split('(', 1)[0].endswith('@' + name):
            return HEADER + 'define ' + chunk.split('\n}\n', 1)[0] + '\n}\n'
    raise KeyError(name)


def update_block(update, width):
    if update == 'checked':
        return f'''check:
  %pair = call {{ {width}, i1 }} @llvm.sadd.with.overflow.{width}({width} %sum, {width} %step)
  %sum.next = extractvalue {{ {width}, i1 }} %pair, 0
  %overflow = extractvalue {{ {width}, i1 }} %pair, 1
  br i1 %overflow, label %trap, label %latch
'''
    if update == 'checked-observable':
        return f'''check:
  %pair = call {{ {width}, i1 }} @llvm.sadd.with.overflow.{width}({width} %sum, {width} %step)
  %sum.next = extractvalue {{ {width}, i1 }} %pair, 0
  %overflow = extractvalue {{ {width}, i1 }} %pair, 1
  %flag = zext i1 %overflow to {width}
  br label %latch
'''
    if update == 'plain':
        return f'check:\n  %sum.next = add {width} %sum, %step\n  br label %latch\n'
    if update == 'select':
        return f'''check:
  %added = add {width} %sum, %step
  %skip = call i1 @choose()
  %sum.next = select i1 %skip, {width} %sum, {width} %added
  br label %latch
'''
    if update == 'phi':
        return f'''check:
  %skip = call i1 @choose()
  br i1 %skip, label %latch, label %add
add:
  %added = add {width} %sum, %step
  br label %latch
'''
    if update == 'twice':
        return f'''check:
  %first = add {width} %sum, %step
  %sum.next = add {width} %first, %step
  br label %latch
'''
    raise KeyError(update)


def accumulate(name='sum', width='i8', seed='0', step_bound='3', trips='8', update='checked', attributes='', exit_code='', step='load'):
    """`sum += step` over at most TRIPS iterations, each step at most STEP_BOUND."""
    latch_phi = f'  %sum.next = phi {width} [ %sum, %check ], [ %added, %add ]\n' if update == 'phi' else ''
    loaded = f'  %ptr = getelementptr {width}, ptr %data, {width} %i\n  %step = load {width}, ptr %ptr, align 1\n' if step == 'load' else f'  %step = add {width} {step}, 0\n'
    result = exit_code or f'  ret {width} %sum\n'
    return f'''define {width} @{name}({width} noundef %n, ptr noundef %data) {attributes} {{
entry:
  %low = icmp ult {width} %n, 1
  %high = icmp ugt {width} %n, {trips}
  %bad = or i1 %low, %high
  br i1 %bad, label %invalid, label %loop
invalid:
  ret {width} -1
loop:
  %i = phi {width} [ 0, %entry ], [ %next, %latch ]
  %sum = phi {width} [ {seed}, %entry ], [ %sum.next, %latch ]
  %done = icmp eq {width} %i, %n
  br i1 %done, label %exit, label %body
body:
{loaded}  %step.bad = icmp ugt {width} %step, {step_bound}
  br i1 %step.bad, label %invalid, label %check
{update_block(update, width)}latch:
{latch_phi}  %next = add {width} %i, 1
  br label %loop
trap:
  call void @llvm.trap()
  unreachable
exit:
{result}}}
'''


def module(*functions, tail=''):
    return HEADER + ''.join(functions) + tail


def nested():
    """An outer loop around an inner sum: only the innermost loop is proved."""
    return module('''define i8 @nested(i8 noundef %n, ptr noundef %data) {
entry:
  %bad = icmp ugt i8 %n, 4
  br i1 %bad, label %exit, label %outer
outer:
  %o = phi i8 [ 0, %entry ], [ %o.next, %outer.latch ]
  %total = phi i8 [ 0, %entry ], [ %total.next, %outer.latch ]
  br label %inner
inner:
  %i = phi i8 [ 0, %outer ], [ %i.next, %inner ]
  %sum = phi i8 [ 0, %outer ], [ %sum.next, %inner ]
  %ptr = getelementptr i8, ptr %data, i8 %i
  %raw = load i8, ptr %ptr
  %step = and i8 %raw, 3
  %sum.next = add i8 %sum, %step
  %i.next = add i8 %i, 1
  %inner.done = icmp eq i8 %i.next, %n
  br i1 %inner.done, label %outer.latch, label %inner
outer.latch:
  %total.next = add i8 %total, %sum.next
  %o.next = add i8 %o, 1
  %outer.done = icmp eq i8 %o.next, %n
  br i1 %outer.done, label %exit, label %outer
exit:
  %result = phi i8 [ 0, %entry ], [ %total.next, %outer.latch ]
  ret i8 %result
}
''')


def irreducible():
    """A sum next to an irreducible cycle: the function is skipped."""
    return module(accumulate(update='plain').replace('''invalid:
  ret i8 -1''', '''invalid:
  %which = call i1 @choose()
  br i1 %which, label %left, label %right
left:
  %go.right = call i1 @choose()
  br i1 %go.right, label %right, label %out
right:
  %go.left = call i1 @choose()
  br i1 %go.left, label %left, label %out
out:
  ret i8 -1'''))


def many_functions(count):
    return module(*[accumulate(name=f'sum{index}', update='plain') for index in range(count)])


def many_loops(count):
    """COUNT sum loops in a row in one function."""
    blocks = []
    for index in range(count):
        following = f'loop{index + 1}' if index + 1 < count else 'exit'
        previous = f'loop{index - 1}' if index else 'entry'
        start = f'%s{index - 1}.next' if index else '0'
        blocks.append(f'''loop{index}:
  %i{index} = phi i8 [ 0, %{previous} ], [ %i{index}.next, %loop{index} ]
  %s{index} = phi i8 [ 0, %{previous} ], [ %s{index}.next, %loop{index} ]
  %raw{index} = load i8, ptr %data
  %step{index} = and i8 %raw{index}, 1
  %s{index}.next = add i8 %s{index}, %step{index}
  %i{index}.next = add nuw i8 %i{index}, 1
  %done{index} = icmp eq i8 %i{index}.next, 4
  br i1 %done{index}, label %{following}, label %loop{index}
''')
    return module(f'''define i8 @loops(ptr noundef %data) {{
entry:
  br label %loop0
{''.join(blocks)}exit:
  ret i8 %s{count - 1}.next
}}
''')


SUB_EXIT = '  %less = sub i8 %sum, 4\n  ret i8 %less\n'
SUB_WIDE_EXIT = '  %less = sub i8 %sum, %n\n  ret i8 %less\n'
SADD_EXIT = '''  %more.pair = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %sum, i8 10)
  %more = extractvalue { i8, i1 } %more.pair, 0
  ret i8 %more
'''
SADD_UNSAFE_EXIT = SADD_EXIT.replace('i8 10)', 'i8 120)')
SSUB_EXIT = '''  %less.pair = call { i8, i1 } @llvm.ssub.with.overflow.i8(i8 %sum, i8 %n)
  %less = extractvalue { i8, i1 } %less.pair, 0
  %less.overflow = extractvalue { i8, i1 } %less.pair, 1
  br i1 %less.overflow, label %trap, label %done.sub
done.sub:
  ret i8 %less
'''
SSUB_OBSERVED_EXIT = SSUB_EXIT.replace('  ret i8 %less\n', '  %seen = zext i1 %less.overflow to i8\n  %both = add i8 %less, %seen\n  ret i8 %both\n')
DEBUG_TAIL = '''!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!2}
!0 = distinct !DICompileUnit(language: DW_LANG_C, file: !1, emissionKind: FullDebug)
!1 = !DIFile(filename: "sum.elisa", directory: "/")
!2 = !{i32 2, !"Debug Info Version", i32 3}
'''

CASES = {
    'fixture': FIXTURE,
    'fixture-negative-cap': FIXTURE.replace('@llvm.smin.i8(i8 %value, i8 %cap)', '@llvm.smin.i8(i8 %value, i8 -1)'),
    'fixture-zero-step': FIXTURE.replace('i8 %sum, i8 %step)', 'i8 %sum, i8 0)'),
    'fixture-undef-step': FIXTURE.replace('i8 %sum, i8 %step)', 'i8 %sum, i8 undef)'),
    'fixture-sanitize': FIXTURE.replace('ptr noundef %data) {', 'ptr noundef %data) sanitize_address {'),
    'fixture-optnone': FIXTURE.replace('ptr noundef %data) {', 'ptr noundef %data) optnone noinline {'),
    'fixture-optsize': FIXTURE.replace('ptr noundef %data) {', 'ptr noundef %data) optsize {'),
    'safe-checked': fixture_function('safe_checked'),
    'safe-plain': fixture_function('safe_plain'),
    'unsafe-m33': fixture_function('unsafe_m33'),
    'nonzero-seed127': fixture_function('nonzero_seed127'),
    'header-update-before-exit': fixture_function('header_update_before_exit'),
    'header-update-observable-flag': fixture_function('header_update_observable_flag'),
    'safe-clamped': fixture_function('safe_clamped'),
    'checked': module(accumulate()),
    'checked-observable-flag': module(accumulate(update='checked-observable')),
    'plain': module(accumulate(update='plain')),
    'plain-already-nsw-nuw': module(accumulate(update='plain').replace('add i8 %sum, %step', 'add nuw nsw i8 %sum, %step')),
    'select-update': module(accumulate(update='select')),
    'phi-update': module(accumulate(update='phi')),
    'two-updates': module(accumulate(update='twice')),
    'seed-positive': module(accumulate(seed='5')),
    'seed-negative': module(accumulate(seed='-1')),
    'seed-at-limit': module(accumulate(seed='100')),
    'seed-too-large': module(accumulate(seed='101')),
    'steps-too-large': module(accumulate(step_bound='16')),
    'steps-at-limit': module(accumulate(step_bound='15', trips='8')),
    'trips-too-many': module(accumulate(trips='200', step_bound='1')),
    'constant-step': module(accumulate(step='3')),
    'width-32': module(accumulate(width='i32', step_bound='1000', trips='100000')),
    'width-128': module(accumulate(width='i128', step_bound='1000', trips='100000')),
    'width-129': module(accumulate(width='i129', step_bound='1000', trips='100000')),
    'plain-sub': module(accumulate(exit_code=SUB_EXIT)),
    'plain-sub-unbounded': module(accumulate(exit_code=SUB_WIDE_EXIT)),
    'checked-add-reuse': module(accumulate(exit_code=SADD_EXIT)),
    'checked-add-reuse-unsafe': module(accumulate(exit_code=SADD_UNSAFE_EXIT)),
    'checked-sub-reuse': module(accumulate(exit_code=SSUB_EXIT)),
    'checked-sub-observed': module(accumulate(exit_code=SSUB_OBSERVED_EXIT)),
    'checked-sub-constant': module(accumulate(exit_code=SSUB_EXIT.replace('i8 %sum, i8 %n)', 'i8 %sum, i8 4)'))),
    'checked-sub-constant-unsafe': module(accumulate(exit_code=SSUB_EXIT.replace('i8 %sum, i8 %n)', 'i8 %sum, i8 -110)'))),
    'checked-sub-observed-constant': module(accumulate(exit_code=SSUB_OBSERVED_EXIT.replace('i8 %sum, i8 %n)', 'i8 %sum, i8 4)'))),
    'plain-sub-unsafe': module(accumulate(exit_code=SUB_EXIT.replace('sub i8 %sum, 4', 'sub i8 %sum, -110'))),
    'strictfp': module(accumulate(attributes='strictfp')),
    'minsize': module(accumulate(attributes='minsize')),
    'sanitize-memory': module(accumulate(attributes='sanitize_memory')),
    'sanitize-thread': module(accumulate(attributes='sanitize_thread')),
    'sanitize-hwaddress': module(accumulate(attributes='sanitize_hwaddress')),
    'debug-module': module(accumulate(), tail=DEBUG_TAIL),
    'nested': nested(),
    'irreducible': irreducible(),
    'functions-32': many_functions(32),
    'functions-33': many_functions(33),
    'loops-64': many_loops(64),
    'loops-65': many_loops(65),
}

# What the C++ pass did with each case: (count, checked adds, checked subtractions,
# `add nuw nsw`, `sub nsw`, traps) -- see test_bounded_sums.shape.
EXPECTED = {
    'checked-add-reuse-unsafe': (2, 1, 0, 2, 0, 1),
    'checked-add-reuse': (3, 0, 0, 2, 0, 1),
    'checked-observable-flag': (1, 1, 0, 1, 0, 1),
    'checked-sub-constant-unsafe': (2, 0, 1, 2, 0, 1),
    'checked-sub-constant': (3, 0, 0, 2, 1, 1),
    'checked-sub-observed-constant': (2, 0, 1, 2, 0, 1),
    'checked-sub-observed': (2, 0, 1, 2, 0, 1),
    'checked-sub-reuse': (2, 0, 1, 2, 0, 1),
    'checked': (2, 0, 0, 2, 0, 1),
    'constant-step': (2, 0, 0, 2, 0, 1),
    'debug-module': (0, 1, 0, 0, 0, 1),
    'fixture-negative-cap': (9, 5, 0, 10, 0, 5),
    'fixture-optnone': (2, 6, 0, 3, 0, 5),
    'fixture-optsize': (2, 6, 0, 3, 0, 5),
    'fixture-sanitize': (2, 6, 0, 3, 0, 5),
    'fixture-undef-step': (8, 6, 0, 9, 0, 5),
    'fixture-zero-step': (12, 2, 0, 13, 0, 5),
    'fixture': (10, 4, 0, 11, 0, 5),
    'functions-32': (64, 0, 0, 64, 0, 32),
    'functions-33': (64, 0, 0, 64, 0, 33),
    'header-update-before-exit': (1, 1, 0, 1, 0, 1),
    'header-update-observable-flag': (1, 1, 0, 1, 0, 0),
    'irreducible': (0, 0, 0, 0, 0, 1),
    'loops-64': (128, 0, 0, 128, 0, 0),
    'loops-65': (128, 0, 0, 128, 0, 0),
    'minsize': (0, 1, 0, 0, 0, 1),
    'nested': (0, 0, 0, 0, 0, 0),
    'nonzero-seed127': (1, 1, 0, 1, 0, 1),
    'phi-update': (2, 0, 0, 2, 0, 1),
    'plain-already-nsw-nuw': (1, 0, 0, 2, 0, 1),
    'plain-sub-unbounded': (2, 0, 0, 2, 0, 1),
    'plain-sub-unsafe': (2, 0, 0, 2, 0, 1),
    'plain-sub': (3, 0, 0, 2, 1, 1),
    'plain': (2, 0, 0, 2, 0, 1),
    'safe-checked': (2, 0, 0, 2, 0, 1),
    'safe-clamped': (2, 0, 0, 3, 0, 1),
    'safe-plain': (2, 0, 0, 2, 0, 0),
    'sanitize-hwaddress': (0, 1, 0, 0, 0, 1),
    'sanitize-memory': (0, 1, 0, 0, 0, 1),
    'sanitize-thread': (0, 1, 0, 0, 0, 1),
    'seed-at-limit': (2, 0, 0, 2, 0, 1),
    'seed-negative': (1, 1, 0, 1, 0, 1),
    'seed-positive': (2, 0, 0, 2, 0, 1),
    'seed-too-large': (1, 1, 0, 1, 0, 1),
    'select-update': (2, 0, 0, 2, 0, 1),
    'steps-at-limit': (1, 1, 0, 1, 0, 1),
    'steps-too-large': (1, 1, 0, 1, 0, 1),
    'strictfp': (0, 1, 0, 0, 0, 1),
    'trips-too-many': (0, 1, 0, 0, 0, 1),
    'two-updates': (1, 0, 0, 1, 0, 1),
    'unsafe-m33': (1, 1, 0, 1, 0, 1),
    'width-128': (2, 0, 0, 2, 0, 1),
    'width-129': (0, 1, 0, 0, 0, 1),
    'width-32': (2, 0, 0, 2, 0, 1),
}
