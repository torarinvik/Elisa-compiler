"""IR shapes for the bounded-trip check folding, shared by its test.

`bounded-trip-checks` iterates interval ranges over an innermost loop once per trip when
scalar evolution bounds its back edges by fewer than 64 (as a constant, or as a sum of
constants and values whose ranges on entry the guards bound). A checked operation whose
operand ranges cannot overflow on any trip gets a false overflow bit, and a compare the
ranges decide becomes a constant. The fixture is the second-order recurrence
`next = 2 * current - previous + a` over 30 trips; each case varies one part, and its
numbers are what the C++ pass did with the same shape (see EXPECTED).
"""
TRIPLE = 'arm64-apple-darwin'
DECLARATIONS = '''
declare { i64, i1 } @llvm.sadd.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.ssub.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.smul.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.uadd.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.usub.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.umul.with.overflow.i64(i64, i64)
declare void @llvm.trap()
'''


def module(body):
    """BODY as a module for the test triple, with the checked intrinsics declared."""
    return f'target triple = "{TRIPLE}"\n' + DECLARATIONS + body


def varied(text, *replacements):
    """TEXT with each (old, new) replacement made everywhere."""
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    return text


RECURRENCE = module('''define i64 @recurrence(i64 noundef %a) {
entry:
  %small = icmp ult i64 %a, 1000
  br i1 %small, label %loop, label %invalid
loop:
  %index = phi i64 [0, %entry], [%index.next, %latch]
  %previous = phi i64 [0, %entry], [%current, %latch]
  %current = phi i64 [1, %entry], [%next, %latch]
  %double = shl nsw i64 %current, 1
  %difference = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 %double, i64 %previous)
  %step = extractvalue { i64, i1 } %difference, 0
  %step.overflow = extractvalue { i64, i1 } %difference, 1
  br i1 %step.overflow, label %trap, label %add
add:
  %sum = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %step, i64 %a)
  %next = extractvalue { i64, i1 } %sum, 0
  %sum.overflow = extractvalue { i64, i1 } %sum, 1
  br i1 %sum.overflow, label %trap, label %latch
latch:
  %index.next = add nuw nsw i64 %index, 1
  %done = icmp eq i64 %index.next, 30
  br i1 %done, label %exit, label %loop
exit:
  ret i64 %next
trap:
  call void @llvm.trap()
  unreachable
invalid:
  ret i64 -1
}
''')

# The trip count a guarded argument gives: 1 <= count < 20.
SYMBOLIC = varied(RECURRENCE, ('define i64 @recurrence(i64 noundef %a) {\nentry:\n  %small = icmp ult i64 %a, 1000\n  br i1 %small, label %loop, label %invalid',
                               'define i64 @recurrence(i64 noundef %a, i64 noundef %count) {\nentry:\n  %small = icmp ult i64 %a, 1000\n  br i1 %small, label %nonempty, label %invalid\nnonempty:\n  %empty = icmp eq i64 %count, 0\n  br i1 %empty, label %invalid, label %bounded\nbounded:\n  %few = icmp ult i64 %count, 20\n  br i1 %few, label %loop, label %invalid'),
                  ('[0, %entry]', '[0, %bounded]'), ('[1, %entry]', '[1, %bounded]'), ('icmp eq i64 %index.next, 30', 'icmp eq i64 %index.next, %count'))

SHORT = varied(RECURRENCE, ('icmp eq i64 %index.next, 30', 'icmp eq i64 %index.next, 5'))

LOWERED = varied(RECURRENCE, ('  br i1 %done, label %exit, label %loop', '  %shifted = add i64 %next, 4611686018427387904\n  %negative = icmp slt i64 %shifted, 0\n  %wide = icmp ugt i64 %next, 1000000000\n  %either = or i1 %negative, %wide\n  br i1 %either, label %trap, label %again\nagain:\n  br i1 %done, label %exit, label %loop'), ('[%index.next, %latch]', '[%index.next, %again]'), ('[%current, %latch]', '[%current, %again]'), ('[%next, %latch]', '[%next, %again]'))

NESTED = module('''define i64 @nested(i64 noundef %a) {
entry:
  %small = icmp ult i64 %a, 1000
  br i1 %small, label %outer, label %invalid
outer:
  %round = phi i64 [0, %entry], [%round.next, %outer.latch]
  %total = phi i64 [0, %entry], [%total.next, %outer.latch]
  br label %inner
inner:
  %index = phi i64 [0, %outer], [%index.next, %inner.latch]
  %value = phi i64 [1, %outer], [%value.next, %inner.latch]
  %grown = call { i64, i1 } @llvm.smul.with.overflow.i64(i64 %value, i64 3)
  %value.next = extractvalue { i64, i1 } %grown, 0
  %grown.overflow = extractvalue { i64, i1 } %grown, 1
  br i1 %grown.overflow, label %trap, label %inner.latch
inner.latch:
  %index.next = add nuw nsw i64 %index, 1
  %inner.done = icmp eq i64 %index.next, 20
  br i1 %inner.done, label %outer.latch, label %inner
outer.latch:
  %total.next = add i64 %total, %value.next
  %round.next = add nuw nsw i64 %round, 1
  %outer.done = icmp eq i64 %round.next, %a
  br i1 %outer.done, label %exit, label %outer
exit:
  ret i64 %total.next
trap:
  call void @llvm.trap()
  unreachable
invalid:
  ret i64 -1
}
''')


def padded(count):
    """The fixture with COUNT more instructions in its loop."""
    lines = ''.join(f'  %pad{n} = add i64 %index, {n}\n' for n in range(count))
    return varied(RECURRENCE, ('  %double = shl nsw i64 %current, 1\n', lines + '  %double = shl nsw i64 %current, 1\n'))


CASES = {
    'recurrence': RECURRENCE,
    'recurrence-63-trips': varied(RECURRENCE, ('icmp eq i64 %index.next, 30', 'icmp eq i64 %index.next, 63')),
    'recurrence-64-trips': varied(RECURRENCE, ('icmp eq i64 %index.next, 30', 'icmp eq i64 %index.next, 64')),
    'recurrence-100-trips': varied(RECURRENCE, ('icmp eq i64 %index.next, 30', 'icmp eq i64 %index.next, 100')),
    'recurrence-wide-input': varied(RECURRENCE, ('icmp ult i64 %a, 1000', 'icmp ult i64 %a, 4611686018427387904')),
    'recurrence-unguarded': varied(RECURRENCE, ('br i1 %small, label %loop, label %invalid', 'br label %loop')),
    'symbolic': SYMBOLIC,
    'symbolic-unbounded': varied(SYMBOLIC, ('icmp ult i64 %count, 20', 'icmp ult i64 %count, 2000')),
    'symbolic-maybe-empty': varied(SYMBOLIC, ('icmp eq i64 %count, 0', 'icmp eq i64 %count, 7')),
    'symbolic-frozen': varied(SYMBOLIC, ('i64 noundef %count) {\nentry:\n', 'i64 %raw) {\nentry:\n  %count = freeze i64 %raw\n')),
    'lowered-checks': LOWERED,
    'compare-decided-true': varied(LOWERED, ('icmp slt i64 %shifted, 0', 'icmp sge i64 %shifted, 0')),
    'no-shift-flags': varied(RECURRENCE, ('shl nsw i64 %current, 1', 'shl i64 %current, 1')),
    'wide-shift': varied(RECURRENCE, ('shl nsw i64 %current, 1', 'shl nsw i64 %current, 62')),
    'unsigned-checks': varied(RECURRENCE, ('@llvm.ssub.with.overflow.i64(i64 %double, i64 %previous)', '@llvm.usub.with.overflow.i64(i64 %double, i64 %previous)'), ('@llvm.sadd.with.overflow.i64(i64 %step, i64 %a)', '@llvm.uadd.with.overflow.i64(i64 %step, i64 %a)')),
    'unsigned-product': varied(RECURRENCE, ('@llvm.sadd.with.overflow.i64(i64 %step, i64 %a)', '@llvm.umul.with.overflow.i64(i64 %step, i64 %a)')),
    'signed-product': varied(RECURRENCE, ('@llvm.sadd.with.overflow.i64(i64 %step, i64 %a)', '@llvm.smul.with.overflow.i64(i64 %step, i64 %a)')),
    'signed-product-short': varied(SHORT, ('@llvm.sadd.with.overflow.i64(i64 %step, i64 %a)', '@llvm.smul.with.overflow.i64(i64 %step, i64 %a)')),
    'unsigned-add': varied(RECURRENCE, ('@llvm.sadd.with.overflow.i64(i64 %step, i64 %a)', '@llvm.uadd.with.overflow.i64(i64 %step, i64 %a)')),
    'unsigned-product-short': varied(SHORT, ('@llvm.sadd.with.overflow.i64(i64 %step, i64 %a)', '@llvm.umul.with.overflow.i64(i64 %step, i64 %a)')),
    'signed-square': varied(RECURRENCE, ('@llvm.sadd.with.overflow.i64(i64 %step, i64 %a)', '@llvm.smul.with.overflow.i64(i64 %step, i64 %step)')),
    'selected-step': varied(RECURRENCE, ('  %sum = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %step, i64 %a)', '  %odd = trunc i64 %index to i1\n  %chosen = select i1 %odd, i64 %step, i64 %a\n  %sum = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %chosen, i64 %a)')),
    'narrowed-step': varied(RECURRENCE, ('  %sum = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %step, i64 %a)', '  %low = trunc i64 %step to i32\n  %back = sext i32 %low to i64\n  %sum = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %back, i64 %a)')),
    'loaded-step': varied(RECURRENCE, ('define i64 @recurrence(i64 noundef %a) {', 'define i64 @recurrence(i64 noundef %a, ptr %table) {'), ('  %sum = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %step, i64 %a)', '  %entry.address = getelementptr i64, ptr %table, i64 %index\n  %loaded = load i64, ptr %entry.address, !range !0\n  %stable = freeze i64 %loaded\n  %plain = load i64, ptr %entry.address\n  %both = add i64 %stable, %plain\n  %sum = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %stable, i64 %a)')) + '!0 = !{i64 -50, i64 50}\n',
    'nested': NESTED,
    'nested-long-inner': varied(NESTED, ('icmp eq i64 %index.next, 20', 'icmp eq i64 %index.next, 50')),
    'two-hundred-instructions': padded(200),
    'three-hundred-instructions': padded(300),
    'optnone': varied(RECURRENCE, ('define i64 @recurrence(i64 noundef %a) {', 'define i64 @recurrence(i64 noundef %a) noinline optnone {')),
    'no-loop': module('''define i64 @plain(i64 %a) {
  %sum = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %a, i64 1)
  %value = extractvalue { i64, i1 } %sum, 0
  ret i64 %value
}
'''),
    'two-loops': RECURRENCE + varied(RECURRENCE[RECURRENCE.index('define'):], ('@recurrence(', '@recurrence2('), ('icmp eq i64 %index.next, 30', 'icmp eq i64 %index.next, 10')),
}

# (changes, i1 false constants, i1 true constants, a second run's changes) per case.
EXPECTED = {
    'recurrence': (2, 2, 0, 2),
    'recurrence-63-trips': (0, 0, 0, 0),
    'recurrence-64-trips': (0, 0, 0, 0),
    'recurrence-100-trips': (0, 0, 0, 0),
    'recurrence-wide-input': (0, 0, 0, 0),
    'recurrence-unguarded': (0, 0, 0, 0),
    'symbolic': (2, 2, 0, 2),
    'symbolic-unbounded': (0, 0, 0, 0),
    'symbolic-maybe-empty': (0, 0, 0, 0),
    'symbolic-frozen': (2, 2, 0, 2),
    'lowered-checks': (3, 3, 0, 3),
    'compare-decided-true': (3, 2, 1, 5),
    'no-shift-flags': (0, 0, 0, 0),
    'wide-shift': (0, 0, 0, 0),
    'unsigned-checks': (0, 0, 0, 0),
    'unsigned-product': (0, 0, 0, 0),
    'signed-product': (0, 0, 0, 0),
    'signed-product-short': (2, 2, 0, 2),
    'unsigned-add': (1, 1, 0, 1),
    'unsigned-product-short': (1, 1, 0, 1),
    'signed-square': (0, 0, 0, 0),
    'selected-step': (2, 2, 0, 2),
    'narrowed-step': (2, 2, 0, 2),
    'loaded-step': (2, 2, 0, 2),
    'nested': (1, 1, 0, 1),
    'nested-long-inner': (1, 1, 0, 1),
    'two-hundred-instructions': (2, 2, 0, 2),
    'three-hundred-instructions': (0, 0, 0, 0),
    'optnone': (0, 0, 0, 0),
    'no-loop': (0, 0, 0, 0),
    'two-loops': (4, 4, 0, 4),
}
