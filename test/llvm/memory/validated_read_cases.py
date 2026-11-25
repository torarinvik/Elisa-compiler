"""IR shapes for the validated reads, shared by their test.

`validated-reads` gives a load `!range` metadata when it reads an element a counted loop
earlier checked against constants (returning on a bad one), its element index is
provably below the loop's bound, and no write that could reach the memory runs between
them. The fixture checks `input[0, n)` against [0, 1e9] and then reads `input[k]` under
`k < n`; each case varies one part, and its numbers are what the C++ pass did with the
same shape (see EXPECTED).
"""
TRIPLE = 'arm64-apple-darwin'
DECLARATIONS = '''
declare void @mystery()
define void @fill(ptr %slot) {
  store i64 1, ptr %slot
  ret void
}
'''


def module(body):
    """BODY as a module for the test triple, with the helpers declared."""
    return f'target triple = "{TRIPLE}"\n' + DECLARATIONS + body


def varied(text, *replacements):
    """TEXT with each (old, new) replacement made everywhere."""
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    return text


VALIDATED = module('''define i64 @read(ptr %input, i64 %n, i64 %k) {
entry:
  %empty = icmp eq i64 %n, 0
  br i1 %empty, label %checked, label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %valid]
  %slot = getelementptr i64, ptr %input, i64 %i
  %value = load i64, ptr %slot
  %low = icmp slt i64 %value, 0
  br i1 %low, label %bad, label %upper
upper:
  %high = icmp sgt i64 %value, 1000000000
  br i1 %high, label %bad, label %valid
valid:
  %next = add i64 %i, 1
  %done = icmp eq i64 %next, %n
  br i1 %done, label %checked, label %loop
checked:
  %inside = icmp ult i64 %k, %n
  br i1 %inside, label %read, label %bad
read:
  %at = getelementptr i64, ptr %input, i64 %k
  %again = load i64, ptr %at
  ret i64 %again
bad:
  ret i64 -1
}
''')
CHECKED = ('checked:\n', 'checked:\n  EXTRA\n')
TESTS = ('''  %low = icmp slt i64 %value, 0
  br i1 %low, label %bad, label %upper
upper:
  %high = icmp sgt i64 %value, 1000000000
  br i1 %high, label %bad, label %valid
''', 'TESTS')


def tested(tests):
    """VALIDATED with the element tests TESTS in place of the two signed checks."""
    return varied(VALIDATED, TESTS, ('TESTS', tests))


def extra(instructions):
    """VALIDATED with INSTRUCTIONS at the start of the block after the loop."""
    return varied(VALIDATED, CHECKED, ('EXTRA', instructions))


HEADER_TESTED = module('''define i64 @read(ptr %input, i64 %n, i64 %k) {
entry:
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %valid]
  %more = icmp ult i64 %i, %n
  br i1 %more, label %body, label %checked
body:
  %slot = getelementptr i64, ptr %input, i64 %i
  %value = load i64, ptr %slot
  %high = icmp ugt i64 %value, 255
  br i1 %high, label %bad, label %valid
valid:
  %next = add i64 %i, 1
  br label %loop
checked:
  %inside = icmp ult i64 %k, %n
  br i1 %inside, label %read, label %bad
read:
  %at = getelementptr i64, ptr %input, i64 %k
  %again = load i64, ptr %at
  ret i64 %again
bad:
  ret i64 -1
}
''')

CASES = {
    'validated': VALIDATED,
    'unguarded-read': varied(VALIDATED, ('  %inside = icmp ult i64 %k, %n\n  br i1 %inside, label %read, label %bad\n', '  br label %read\n')),
    'header-tested': HEADER_TESTED,
    'written-between': extra('store i64 7, ptr %input'),
    'stack-write-between': extra('%local = alloca i64\n  store i64 7, ptr %local'),
    'stack-helper-call': extra('%local = alloca i64\n  call void @fill(ptr %local)'),
    'argument-helper-call': extra('call void @fill(ptr %input)'),
    'unknown-call': extra('call void @mystery()'),
    'unsigned-only': tested('  %high = icmp ugt i64 %value, 100\n  br i1 %high, label %bad, label %valid\n'),
    'either-test': tested('  %low = icmp slt i64 %value, 0\n  %high = icmp sgt i64 %value, 9\n  %either = or i1 %low, %high\n  br i1 %either, label %bad, label %valid\n'),
    'select-test': tested('  %low = icmp slt i64 %value, 0\n  %high = icmp sgt i64 %value, 9\n  %either = select i1 %low, i1 true, i1 %high\n  br i1 %either, label %bad, label %valid\n'),
    'reloaded-test': tested('  %reloaded = load i64, ptr %slot\n  %high = icmp ugt i64 %reloaded, 50\n  br i1 %high, label %bad, label %valid\n'),
    'other-element-test': tested('  %neighbor = getelementptr i64, ptr %slot, i64 1\n  %reloaded = load i64, ptr %neighbor\n  %high = icmp ugt i64 %reloaded, 50\n  br i1 %high, label %bad, label %valid\n'),
    'no-test': tested('  br label %valid\n'),
    'uncovered-exit': varied(VALIDATED, ('  %empty = icmp eq i64 %n, 0\n  br i1 %empty, label %checked, label %loop\n', '  %empty = icmp ult i64 %n, 1\n  br i1 %empty, label %checked, label %loop\n')),
    'offset-start': varied(VALIDATED, ('%slot = getelementptr i64, ptr %input, i64 %i', '%shifted = add i64 %i, 2\n  %slot = getelementptr i64, ptr %input, i64 %shifted'),
                           ('%at = getelementptr i64, ptr %input, i64 %k', '%moved = add i64 %k, 2\n  %at = getelementptr i64, ptr %input, i64 %moved')),
    'misaligned-read': varied(VALIDATED, ('%at = getelementptr i64, ptr %input, i64 %k', '%at = getelementptr i8, ptr %input, i64 %k')),
    'i32-elements': varied(VALIDATED, ('getelementptr i64, ptr %input', 'getelementptr i32, ptr %input'), ('%value = load i64', '%value = load i32'),
                           ('icmp slt i64 %value', 'icmp slt i32 %value'), ('icmp sgt i64 %value', 'icmp sgt i32 %value'),
                           ('%again = load i64, ptr %at\n  ret i64 %again', '%again = load i32, ptr %at\n  %wide = sext i32 %again to i64\n  ret i64 %wide')),
    'sum-bound': varied(VALIDATED, ('define i64 @read(ptr %input, i64 %n, i64 %k)', 'define i64 @read(ptr %input, i64 %a, i64 %b, i64 %k)'),
                        ('entry:\n', 'entry:\n  %n = add nuw i64 %a, %b\n'), ('%inside = icmp ult i64 %k, %n', '%inside = icmp ult i64 %k, %a')),
    'existing-range': varied(VALIDATED, ('%again = load i64, ptr %at', '%again = load i64, ptr %at, !range !0')) + '!0 = !{i64 0, i64 5}\n',
    'volatile-read': varied(VALIDATED, ('%again = load i64, ptr %at', '%again = load volatile i64, ptr %at')),
    'stack-array': varied(VALIDATED, ('entry:\n', 'entry:\n  %input = alloca [64 x i64]\n'), ('define i64 @read(ptr %input,', 'define i64 @read(ptr %unused,')),
    'optnone': varied(VALIDATED, ('define i64 @read(ptr %input, i64 %n, i64 %k) {', 'define i64 @read(ptr %input, i64 %n, i64 %k) noinline optnone {')),
}

# Per case: the count of loads annotated, the `!range` bounds the module's loads carry
# (sorted), and a second run's count.
EXPECTED = {
    'validated': (1, [(0, 1000000001)], 0),
    'unguarded-read': (0, [], 0),
    'header-tested': (1, [(0, 256)], 0),
    'written-between': (0, [], 0),
    'stack-write-between': (1, [(0, 1000000001)], 0),
    'stack-helper-call': (1, [(0, 1000000001)], 0),
    'argument-helper-call': (0, [], 0),
    'unknown-call': (0, [], 0),
    'unsigned-only': (1, [(0, 101)], 0),
    'either-test': (1, [(0, 10)], 0),
    'select-test': (1, [(0, 10)], 0),
    'reloaded-test': (1, [(0, 51)], 0),
    'other-element-test': (0, [], 0),
    'no-test': (0, [], 0),
    'uncovered-exit': (0, [], 0),
    'offset-start': (1, [(0, 1000000001)], 0),
    'misaligned-read': (0, [], 0),
    'i32-elements': (1, [(0, 1000000001)], 0),
    'sum-bound': (1, [(0, 1000000001)], 0),
    'existing-range': (0, [(0, 5)], 0),
    'volatile-read': (0, [], 0),
    'stack-array': (0, [], 0),
    'optnone': (0, [], 0),
}
