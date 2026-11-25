"""IR shapes for the proven-check removal, shared by its test.

`proven-checks` folds a branch to a trap to its other side when the index prover shows
the comparison deciding it always holds there: `index <u length`, `index <=u length` or
`index != length`. Each case is one function whose `trap` block only traps; its numbers
are what the C++ pass did with the same shape (see EXPECTED).
"""
TRIPLE = 'arm64-apple-darwin'
DECLARATIONS = '''
declare void @llvm.trap()
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)
declare i64 @llvm.umin.i64(i64, i64)
'''
TRAP = '''trap:
  call void @llvm.trap()
  unreachable
'''


def module(body):
    """BODY as a module for the test triple, with the intrinsics declared."""
    return f'target triple = "{TRIPLE}"\n' + DECLARATIONS + body


def varied(text, *replacements):
    """TEXT with each (old, new) replacement made everywhere."""
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    return text


SCAN = module('''define i64 @scan(ptr %data, i64 %n, i64 %len) {
entry:
  %fits = icmp ule i64 %n, %len
  br i1 %fits, label %loop, label %done
loop:
  %i = phi i64 [0, %entry], [%next, %body]
  %total = phi i64 [0, %entry], [%sum, %body]
  %more = icmp ult i64 %i, %n
  br i1 %more, label %check, label %done
check:
  %inside = icmp ult i64 %i, %len
  br i1 %inside, label %body, label %trap
body:
  %slot = getelementptr i64, ptr %data, i64 %i
  %value = load i64, ptr %slot
  %sum = add i64 %total, %value
  %next = add nuw i64 %i, 1
  br label %loop
''' + TRAP + '''done:
  %result = phi i64 [0, %entry], [%total, %loop]
  ret i64 %result
}
''')
CHECK = ('  %inside = icmp ult i64 %i, %len\n  br i1 %inside, label %body, label %trap\n')


def checked(condition, safe_first=True):
    """SCAN with the check CONDITION (instructions defining %inside)."""
    branch = 'br i1 %inside, label %body, label %trap' if safe_first else 'br i1 %inside, label %trap, label %body'
    return varied(SCAN, (CHECK, f'  {condition}\n  {branch}\n'))


def single(body, arguments='i64 %x, i64 %len'):
    """A function reading `data[index]` after the check BODY defines %inside for."""
    return module(f'''define i64 @read(ptr %data, {arguments}) {{
{body}
  br i1 %inside, label %read, label %trap
read:
  %slot = getelementptr i64, ptr %data, i64 %index
  %value = load i64, ptr %slot
  ret i64 %value
''' + TRAP + '''done:
  ret i64 0
}
''')


ELEMENT = module('''define i64 @stored(ptr %input, i64 %n, i64 %k) {
entry:
  %table = alloca [8 x i64]
  call void @llvm.memset.p0.i64(ptr %table, i8 0, i64 64, i1 false)
  %value = load i64, ptr %input
  %slot = getelementptr i64, ptr %table, i64 1
  store i64 %value, ptr %slot
  %big = icmp ugt i64 %value, %n
  br i1 %big, label %reject, label %accept
reject:
  ret i64 -1
accept:
  %masked = and i64 %k, 7
  %at = getelementptr i64, ptr %table, i64 %masked
  %read = load i64, ptr %at
  %inside = icmp ule i64 %read, %n
  br i1 %inside, label %ok, label %trap
ok:
  ret i64 %read
''' + TRAP + '''}
''')

TWO_POINTERS = module('''define i64 @reverse(ptr %data, i64 %n, i64 %len) {
entry:
  %several = icmp ugt i64 %n, 1
  %fits = icmp ule i64 %n, %len
  %usable = and i1 %several, %fits
  %last = add i64 %n, -1
  br i1 %usable, label %loop, label %done
loop:
  %left = phi i64 [0, %entry], [%left.next, %latch]
  %right = phi i64 [%last, %entry], [%right.next, %latch]
  %left.inside = icmp ult i64 %left, %len
  br i1 %left.inside, label %right.check, label %trap
right.check:
  %right.inside = icmp ult i64 %right, %len
  br i1 %right.inside, label %latch, label %trap
latch:
  %left.slot = getelementptr i64, ptr %data, i64 %left
  %right.slot = getelementptr i64, ptr %data, i64 %right
  %a = load i64, ptr %left.slot
  %b = load i64, ptr %right.slot
  store i64 %b, ptr %left.slot
  store i64 %a, ptr %right.slot
  %left.next = add nuw i64 %left, 1
  %right.next = add i64 %right, -1
  %again = icmp ult i64 %left.next, %right.next
  br i1 %again, label %loop, label %done
''' + TRAP + '''done:
  ret i64 0
}
''')

COUNTDOWN = module('''define i64 @countdown(ptr %data, i64 %n, i64 %len) {
entry:
  %nonzero = icmp ne i64 %n, 0
  %fits = icmp ule i64 %n, %len
  %usable = and i1 %nonzero, %fits
  br i1 %usable, label %loop, label %done
loop:
  %i = phi i64 [%n, %entry], [%previous, %body]
  %previous = add i64 %i, -1
  %inside = icmp ult i64 %previous, %len
  br i1 %inside, label %body, label %trap
body:
  %slot = getelementptr i64, ptr %data, i64 %previous
  store i64 0, ptr %slot
  %more = icmp ne i64 %previous, 0
  br i1 %more, label %loop, label %done
''' + TRAP + '''done:
  ret i64 0
}
''')

EXIT_BOUND = module('''define i64 @span(ptr %data, i64 %left, i64 %right, i64 %len) {
entry:
  %ordered = icmp ult i64 %left, %right
  %fits = icmp ule i64 %right, %len
  %usable = and i1 %ordered, %fits
  br i1 %usable, label %loop, label %done
loop:
  %i = phi i64 [%left, %entry], [%next, %body]
  %inside = icmp ult i64 %i, %len
  br i1 %inside, label %body, label %trap
body:
  %slot = getelementptr i64, ptr %data, i64 %i
  store i64 1, ptr %slot
  %next = add i64 %i, 1
  %end = icmp eq i64 %next, %right
  br i1 %end, label %done, label %loop
''' + TRAP + '''done:
  ret i64 0
}
''')

ROUNDED = module('''define i64 @rounded(ptr %data, i64 %n) {
entry:
  %vector = and i64 %n, -4
  %empty = icmp eq i64 %vector, 0
  br i1 %empty, label %done, label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %body]
  %inside = icmp ult i64 %i, %n
  br i1 %inside, label %body, label %trap
body:
  %slot = getelementptr i64, ptr %data, i64 %i
  store i64 0, ptr %slot
  %next = add nuw i64 %i, 4
  %end = icmp eq i64 %next, %vector
  br i1 %end, label %done, label %loop
''' + TRAP + '''done:
  ret i64 0
}
''')

SENTINEL = module('''define i64 @root(ptr %parents, i64 %node, i64 %count) {
entry:
  store i64 -1, ptr %parents
  %fits = icmp ult i64 %node, %count
  br i1 %fits, label %loop, label %done
loop:
  %current = phi i64 [%node, %entry], [%up, %body]
  %inside = icmp ult i64 %current, %count
  br i1 %inside, label %body, label %trap
body:
  %slot = getelementptr i64, ptr %parents, i64 %current
  %up = load i64, ptr %slot
  %root = icmp eq i64 %up, -1
  br i1 %root, label %done, label %loop
''' + TRAP + '''done:
  ret i64 0
}
''')

CASES = {
    'guarded-loop': SCAN,
    'unguarded-loop': varied(SCAN, ('  %fits = icmp ule i64 %n, %len\n  br i1 %fits, label %loop, label %done\n', '  br label %loop\n'),
                             ('[0, %entry], [%total, %loop]', '[%total, %loop]')),
    'reversed-compare': checked('%inside = icmp ugt i64 %len, %i'),
    'at-most-check': checked('%inside = icmp ule i64 %i, %len'),
    'not-equal-check': checked('%inside = icmp ne i64 %i, %len'),
    'trap-on-true': checked('%inside = icmp uge i64 %i, %len', safe_first=False),
    'wider-than-length': varied(SCAN, ('%fits = icmp ule i64 %n, %len', '%fits = icmp ule i64 %n, 100'), ('%inside = icmp ult i64 %i, %len', '%inside = icmp ult i64 %i, 50')),
    'signed-loop': varied(SCAN, ('%more = icmp ult i64 %i, %n', '%more = icmp slt i64 %i, %n')),
    'previous-element': single('''entry:
  %positive = icmp ugt i64 %x, 0
  br i1 %positive, label %bounded, label %done
bounded:
  %fits = icmp ule i64 %x, %len
  br i1 %fits, label %check, label %done
check:
  %index = add i64 %x, -1
  %inside = icmp ult i64 %index, %len'''),
    'midpoint': single('''entry:
  %ordered = icmp ult i64 %low, %high
  br i1 %ordered, label %sized, label %done
sized:
  %fits = icmp ule i64 %high, %len
  br i1 %fits, label %check, label %done
check:
  %width = sub i64 %high, %low
  %half = lshr i64 %width, 1
  %index = add i64 %low, %half
  %inside = icmp ult i64 %index, %len''', 'i64 %low, i64 %high, i64 %len'),
    'masked-index': single('''entry:
  br label %check
check:
  %index = and i64 %x, 7
  %inside = icmp ult i64 %index, 8'''),
    'select-of-bounded': single('''entry:
  %a.inside = icmp ult i64 %a, %len
  %b.inside = icmp ult i64 %b, %len
  %both = and i1 %a.inside, %b.inside
  br i1 %both, label %check, label %done
check:
  %index = select i1 %flag, i64 %a, i64 %b
  %inside = icmp ult i64 %index, %len''', 'i64 %a, i64 %b, i1 %flag, i64 %len'),
    'minimum-length': single('''entry:
  %below.len = icmp ult i64 %x, %len
  %below.cap = icmp ult i64 %x, %cap
  %both = and i1 %below.len, %below.cap
  br i1 %both, label %check, label %done
check:
  %index = add i64 %x, 0
  %limit = call i64 @llvm.umin.i64(i64 %len, i64 %cap)
  %inside = icmp ult i64 %index, %limit''', 'i64 %x, i64 %len, i64 %cap'),
    'join-of-bounded': single('''entry:
  br i1 %flag, label %left, label %right
left:
  %a.inside = icmp ult i64 %a, %len
  br i1 %a.inside, label %check, label %done
right:
  %b.inside = icmp ult i64 %b, %len
  br i1 %b.inside, label %check, label %done
check:
  %index = phi i64 [%a, %left], [%b, %right]
  %inside = icmp ult i64 %index, %len''', 'i64 %a, i64 %b, i1 %flag, i64 %len'),
    'unsigned-half': single('''entry:
  %nonzero = icmp ne i64 %x, 0
  br i1 %nonzero, label %check, label %done
check:
  %index = lshr i64 %x, 1
  %inside = icmp ult i64 %index, %x'''),
    'scaled-index': single('''entry:
  %quarter = lshr i64 %a, 2
  %small = icmp ult i64 %x, %quarter
  br i1 %small, label %sized, label %done
sized:
  %fits = icmp ule i64 %a, %len
  br i1 %fits, label %check, label %done
check:
  %scaled = shl nuw i64 %x, 2
  %index = add nuw i64 %scaled, 1
  %inside = icmp ult i64 %index, %len''', 'i64 %x, i64 %a, i64 %len'),
    'difference-index': single('''entry:
  %nonzero = icmp ne i64 %k, 0
  br i1 %nonzero, label %covered, label %done
covered:
  %within = icmp ule i64 %k, %x
  br i1 %within, label %sized, label %done
sized:
  %fits = icmp ule i64 %x, %len
  br i1 %fits, label %check, label %done
check:
  %index = sub i64 %x, %k
  %inside = icmp ult i64 %index, %len''', 'i64 %x, i64 %k, i64 %len'),
    'unbounded-difference': single('''entry:
  %fits = icmp ule i64 %x, %len
  br i1 %fits, label %check, label %done
check:
  %index = sub i64 %x, %k
  %inside = icmp ult i64 %index, %len''', 'i64 %x, i64 %k, i64 %len'),
    'two-pointers': TWO_POINTERS,
    'countdown': COUNTDOWN,
    'exit-bound': EXIT_BOUND,
    'rounded-vector': ROUNDED,
    'sentinel': SENTINEL,
    'element-checked': ELEMENT,
    'element-unchecked': varied(ELEMENT, ('  %big = icmp ugt i64 %value, %n\n  br i1 %big, label %reject, label %accept\n', '  br label %accept\n'),
                                ('reject:\n  ret i64 -1\n', '')),
    'element-signed': varied(ELEMENT, ('  %big = icmp ugt i64 %value, %n\n  br i1 %big, label %reject, label %accept\n',
                                       '  %negative = icmp slt i64 %value, 0\n  br i1 %negative, label %reject, label %upper\nupper:\n  %big = icmp sgt i64 %value, %n\n  br i1 %big, label %reject, label %accept\n')),
    'optnone': varied(SCAN, ('define i64 @scan(ptr %data, i64 %n, i64 %len) {', 'define i64 @scan(ptr %data, i64 %n, i64 %len) noinline optnone {')),
}

# Two shapes the C++ pass folded unsoundly, kept here with the sound answer. A join of
# `add nuw %x, %y` (y unknown) is not bounded by x's range: C++'s partial
# `m_NUWAdd(m_Value(Base), m_APInt)` match left Base = x. And a recurrence 3i + 4 for i
# below m where 3m wraps to -2: C++ let `uadd_ov` clear the `umul_ov` flag, took the
# wrapped largest value, and dropped a trap that the first iteration reaches when the
# length is 0.
UNSOUND_CASES = {
    'nuw-join-unknown-step': module('''define i64 @join(i64 %x, i64 %y, i1 %which) {
entry:
  %small = icmp ult i64 %x, 10
  br i1 %small, label %pick, label %out
pick:
  br i1 %which, label %left, label %right
left:
  %sum = add nuw i64 %x, %y
  br label %merge
right:
  br label %merge
merge:
  %v = phi i64 [ %sum, %left ], [ %x, %right ]
  %ok = icmp ult i64 %v, 10
  br i1 %ok, label %out, label %trap
out:
  ret i64 0
''' + TRAP + '}\n'),
    'wrapping-recurrence-bound': module('''define i64 @wraps(ptr %p, i64 %len) {
entry:
  %m = load i64, ptr %p, align 8
  %times = mul i64 %m, 3
  %wrapped = icmp ne i64 %times, -2
  %empty = icmp eq i64 %m, 0
  %skip = or i1 %wrapped, %empty
  br i1 %skip, label %out, label %loop
loop:
  %i = phi i64 [ %next, %latch ], [ 0, %entry ]
  %scaled = mul nuw nsw i64 %i, 3
  %index = add nsw i64 %scaled, 4
  %ok = icmp ult i64 %index, %len
  br i1 %ok, label %latch, label %trap
latch:
  %next = add nsw i64 %i, 1
  %done = icmp eq i64 %next, %m
  br i1 %done, label %out, label %loop
out:
  ret i64 0
''' + TRAP + '}\n'),
}
CASES.update(UNSOUND_CASES)

# Per case: the count of checks folded, the constant branches the module is left with,
# and a second run's count.

EXPECTED = {
    'guarded-loop': (1, 1, 0),
    'unguarded-loop': (0, 0, 0),
    'reversed-compare': (1, 1, 0),
    'at-most-check': (1, 1, 0),
    'not-equal-check': (1, 1, 0),
    'trap-on-true': (1, 1, 0),
    'wider-than-length': (0, 0, 0),
    'signed-loop': (0, 0, 0),
    'previous-element': (1, 1, 0),
    'midpoint': (1, 1, 0),
    'masked-index': (1, 1, 0),
    'select-of-bounded': (1, 1, 0),
    'minimum-length': (1, 1, 0),
    'join-of-bounded': (1, 1, 0),
    'unsigned-half': (1, 1, 0),
    'scaled-index': (1, 1, 0),
    'difference-index': (1, 1, 0),
    'unbounded-difference': (0, 0, 0),
    'two-pointers': (1, 1, 0),
    'countdown': (1, 1, 0),
    'exit-bound': (1, 1, 0),
    'rounded-vector': (1, 1, 0),
    'sentinel': (0, 0, 0),
    'element-checked': (1, 1, 0),
    'element-unchecked': (0, 0, 0),
    'element-signed': (1, 1, 0),
    'optnone': (0, 0, 0),
    'nuw-join-unknown-step': (0, 0, 0),
    'wrapping-recurrence-bound': (0, 0, 0),
}
