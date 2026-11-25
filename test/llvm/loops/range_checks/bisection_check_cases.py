"""IR shapes for the bisection-check versioning, shared by its test.

`bisection-check-versioning` rewrites the bounds check `middle <u limit` of a binary search
`while begin < end: middle = begin + (end - begin) / 2` whose `end` only moves down to
`middle`: the trap is then taken only when `freeze(end_on_entry) >u limit` too, a loop
invariant condition that unswitching can take out of the loop. The fixture searches
`data[0, n)` with the check against `limit`; each case varies one part, and its numbers
are what the C++ pass did with the same shape (see EXPECTED).
"""
TRIPLE = 'arm64-apple-darwin'
DECLARATIONS = '''
declare void @llvm.trap()
'''


def module(body):
    """BODY as a module for the test triple, with `llvm.trap` declared."""
    return f'target triple = "{TRIPLE}"\n' + DECLARATIONS + body


def varied(text, *replacements):
    """TEXT with each (old, new) replacement made everywhere."""
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    return text


SEARCH = module('''define i64 @search(ptr %data, i64 %n, i64 %limit, i64 %key) {
entry:
  br label %header
header:
  %begin = phi i64 [0, %entry], [%begin.next, %latch]
  %end = phi i64 [%n, %entry], [%end.next, %latch]
  %more = icmp ult i64 %begin, %end
  br i1 %more, label %body, label %exit
body:
  %width = sub i64 %end, %begin
  %half = lshr i64 %width, 1
  %middle = add i64 %begin, %half
  %inside = icmp ult i64 %middle, %limit
  br i1 %inside, label %probe, label %trap
probe:
  %address = getelementptr i64, ptr %data, i64 %middle
  %value = load i64, ptr %address
  %less = icmp slt i64 %value, %key
  %middle.next = add i64 %middle, 1
  %begin.next = select i1 %less, i64 %middle.next, i64 %begin
  %end.next = select i1 %less, i64 %end, i64 %middle
  br label %latch
latch:
  br label %header
exit:
  ret i64 %begin
trap:
  call void @llvm.trap()
  unreachable
}
''')

# The two halves as blocks joined by a phi in the latch.
BRANCHED = varied(SEARCH, ('''  %begin.next = select i1 %less, i64 %middle.next, i64 %begin
  %end.next = select i1 %less, i64 %end, i64 %middle
  br label %latch
latch:
''', '''  br i1 %less, label %right, label %left
right:
  br label %latch
left:
  br label %latch
latch:
  %begin.next = phi i64 [%middle.next, %right], [%begin, %left]
  %end.next = phi i64 [%end, %right], [%middle, %left]
'''))

# A view whose length the loop reads from memory: LIMIT is a load in the body.
LOADED = varied(SEARCH, ('define i64 @search(ptr %data, i64 %n, i64 %limit, i64 %key) {', 'define i64 @search(ptr %data, i64 %n, ptr align 8 dereferenceable(8) %length, i64 %key) {'),
                ('  %inside = icmp ult i64 %middle, %limit', '  %limit = load i64, ptr %length, align 8\n  %inside = icmp ult i64 %middle, %limit'))

NESTED = module('''define i64 @searches(ptr %data, i64 %n, i64 %limit, i64 %rounds) {
entry:
  br label %outer
outer:
  %round = phi i64 [0, %entry], [%round.next, %outer.latch]
  %total = phi i64 [0, %entry], [%total.next, %outer.latch]
  br label %header
header:
  %begin = phi i64 [0, %outer], [%begin.next, %header.latch]
  %end = phi i64 [%n, %outer], [%end.next, %header.latch]
  %more = icmp ult i64 %begin, %end
  br i1 %more, label %body, label %outer.latch
body:
  %width = sub i64 %end, %begin
  %half = lshr i64 %width, 1
  %middle = add i64 %begin, %half
  %inside = icmp ult i64 %middle, %limit
  br i1 %inside, label %probe, label %trap
probe:
  %address = getelementptr i64, ptr %data, i64 %middle
  %value = load i64, ptr %address
  %less = icmp slt i64 %value, %round
  %middle.next = add i64 %middle, 1
  %begin.next = select i1 %less, i64 %middle.next, i64 %begin
  %end.next = select i1 %less, i64 %end, i64 %middle
  br label %header.latch
header.latch:
  br label %header
outer.latch:
  %total.next = add i64 %total, %begin
  %round.next = add i64 %round, 1
  %done = icmp eq i64 %round.next, %rounds
  br i1 %done, label %exit, label %outer
exit:
  ret i64 %total.next
trap:
  call void @llvm.trap()
  unreachable
}
''')

CASES = {
    'search': SEARCH,
    'divided-midpoint': varied(SEARCH, ('lshr i64 %width, 1', 'udiv i64 %width, 2')),
    'half-first': varied(SEARCH, ('add i64 %begin, %half', 'add i64 %half, %begin')),
    'quarter-midpoint': varied(SEARCH, ('lshr i64 %width, 1', 'lshr i64 %width, 2')),
    'divided-by-four': varied(SEARCH, ('lshr i64 %width, 1', 'udiv i64 %width, 4')),
    'trap-when-true': varied(SEARCH, ('  %inside = icmp ult i64 %middle, %limit\n  br i1 %inside, label %probe, label %trap', '  %outside = icmp uge i64 %middle, %limit\n  br i1 %outside, label %trap, label %probe')),
    'limit-first': varied(SEARCH, ('icmp ult i64 %middle, %limit', 'icmp ugt i64 %limit, %middle')),
    'signed-check': varied(SEARCH, ('icmp ult i64 %middle, %limit', 'icmp slt i64 %middle, %limit')),
    'inclusive-check': varied(SEARCH, ('icmp ult i64 %middle, %limit', 'icmp ule i64 %middle, %limit')),
    'end-first-guard': varied(SEARCH, ('icmp ult i64 %begin, %end', 'icmp ugt i64 %end, %begin')),
    'exit-when-true-guard': varied(SEARCH, ('  %more = icmp ult i64 %begin, %end\n  br i1 %more, label %body, label %exit', '  %done = icmp uge i64 %begin, %end\n  br i1 %done, label %exit, label %body')),
    'signed-guard': varied(SEARCH, ('icmp ult i64 %begin, %end', 'icmp slt i64 %begin, %end')),
    'unguarded': varied(SEARCH, ('  %more = icmp ult i64 %begin, %end\n  br i1 %more, label %body, label %exit', '  %more = icmp ult i64 %begin, %end\n  br label %body'), ('  br label %latch\nlatch:\n  br label %header', '  br label %latch\nlatch:\n  br i1 %more, label %header, label %exit')),
    'end-to-begin': varied(SEARCH, ('select i1 %less, i64 %end, i64 %middle', 'select i1 %less, i64 %end, i64 %begin')),
    'end-past-middle': varied(SEARCH, ('select i1 %less, i64 %end, i64 %middle', 'select i1 %less, i64 %end, i64 %middle.next')),
    'branched-halves': BRANCHED,
    'constant-bounds': varied(SEARCH, ('[%n, %entry]', '[100, %entry]'), ('icmp ult i64 %middle, %limit', 'icmp ult i64 %middle, 50')),
    'constant-end': varied(SEARCH, ('[%n, %entry]', '[100, %entry]')),
    'constant-limit': varied(SEARCH, ('icmp ult i64 %middle, %limit', 'icmp ult i64 %middle, 50')),
    'two-traps': varied(SEARCH, ('br i1 %inside, label %probe, label %trap', 'br i1 %inside, label %trap, label %trap')),
    'no-trap': varied(SEARCH, ('br i1 %inside, label %probe, label %trap', 'br i1 %inside, label %probe, label %exit')),
    'loaded-limit': LOADED,
    'loaded-limit-with-store': varied(LOADED, ('  %less = icmp slt i64 %value, %key', '  store i64 %middle, ptr %data\n  %less = icmp slt i64 %value, %key')),
    'loaded-limit-maybe-faulting': varied(LOADED, ('ptr align 8 dereferenceable(8) %length', 'ptr %length')),
    'volatile-limit': varied(LOADED, ('load i64, ptr %length, align 8', 'load volatile i64, ptr %length, align 8')),
    'computed-limit': varied(SEARCH, ('define i64 @search(ptr %data, i64 %n, i64 %limit, i64 %key) {', 'define i64 @search(ptr %data, i64 %n, i64 %count, i64 %key) {'),
                             ('  %inside = icmp ult i64 %middle, %limit', '  %limit = shl i64 %count, 3\n  %inside = icmp ult i64 %middle, %limit')),
    'varying-limit': varied(SEARCH, ('  %inside = icmp ult i64 %middle, %limit', '  %moving = add i64 %limit, %begin\n  %inside = icmp ult i64 %middle, %moving')),
    'nested': NESTED,
    'weighted': varied(SEARCH, ('br i1 %inside, label %probe, label %trap', 'br i1 %inside, label %probe, label %trap, !prof !0')) + '!0 = !{!"branch_weights", i32 2000, i32 1}\n',
    'optnone': varied(SEARCH, ('i64 %key) {', 'i64 %key) noinline optnone {')),
    'two-searches': SEARCH + varied(SEARCH[SEARCH.index('define'):], ('@search(', '@search2('), ('lshr i64 %width, 1', 'udiv i64 %width, 2')),
}

# (changes, bisect.* values defined, freezes, branch weights, a second run's changes) per case.
EXPECTED = {
    'search': (1, 4, 1, '', 0),
    'divided-midpoint': (1, 4, 1, '', 0),
    'half-first': (1, 4, 1, '', 0),
    'quarter-midpoint': (0, 0, 0, '', 0),
    'divided-by-four': (0, 0, 0, '', 0),
    'trap-when-true': (1, 4, 1, '', 0),
    'limit-first': (1, 4, 1, '', 0),
    'signed-check': (0, 0, 0, '', 0),
    'inclusive-check': (0, 0, 0, '', 0),
    'end-first-guard': (1, 4, 1, '', 0),
    'exit-when-true-guard': (1, 4, 1, '', 0),
    'signed-guard': (0, 0, 0, '', 0),
    'unguarded': (0, 0, 0, '', 0),
    'end-to-begin': (0, 0, 0, '', 0),
    'end-past-middle': (0, 0, 0, '', 0),
    'branched-halves': (1, 4, 1, '', 0),
    'constant-bounds': (0, 0, 0, '', 0),
    'constant-end': (1, 4, 1, '', 0),
    'constant-limit': (1, 4, 1, '', 0),
    'two-traps': (0, 0, 0, '', 0),
    'no-trap': (0, 0, 0, '', 0),
    'loaded-limit': (1, 4, 1, '', 0),
    'loaded-limit-with-store': (0, 0, 0, '', 0),
    'loaded-limit-maybe-faulting': (0, 0, 0, '', 0),
    'volatile-limit': (0, 0, 0, '', 0),
    'computed-limit': (1, 4, 1, '', 0),
    'varying-limit': (0, 0, 0, '', 0),
    'nested': (1, 4, 1, '', 0),
    'weighted': (1, 4, 1, '1, i32 2000', 0),
    'optnone': (0, 0, 0, '', 0),
    'two-searches': (2, 8, 2, '', 0),
}
