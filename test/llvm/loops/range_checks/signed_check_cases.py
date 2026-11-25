"""IR shapes for the signed-check prover and the recursive argument bounds, shared by
their test.

`proven-signed-checks` folds a checked signed i64 add, subtract or multiply into plain
arithmetic when the ranges of its operands show it cannot overflow: ranges from the
guards dominating it (through `and`/`or`, boolean selects, an added constant and `abs`),
from casts, loads with `!range`, bisection webs, loop counters, stepped and shrinking loop
values, sums over counted loops, compared guards, a split on low bits, and the fields
every caller of a private helper passes. `refold-proven-signed-checks` first freezes the
guarded loads that give narrow ranges. `recursive-argument-bounds` removes a recursive
helper's index check that every outside call and every recursive edge keeps in bounds.
Each case's numbers are what the C++ passes did with the same shape (see EXPECTED).
"""
TRIPLE = 'arm64-apple-darwin'
HEADER = f'target triple = "{TRIPLE}"\n'
DECLARATIONS = '''
declare { i64, i1 } @llvm.sadd.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.ssub.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.smul.with.overflow.i64(i64, i64)
declare i64 @llvm.abs.i64(i64, i1)
declare void @llvm.trap()
'''


def module(body):
    """BODY as a module for the test triple, with the checked intrinsics declared."""
    return HEADER + DECLARATIONS + body


def checked(operation, left, right, name='checked'):
    """A trapping checked OPERATION of LEFT and RIGHT, continuing at `NAME.ok` with
    `%NAME.value`."""
    return f'''  %{name} = call {{ i64, i1 }} @llvm.{operation}.with.overflow.i64(i64 {left}, i64 {right})
  %{name}.overflow = extractvalue {{ i64, i1 }} %{name}, 1
  br i1 %{name}.overflow, label %trap, label %{name}.ok
{name}.ok:
  %{name}.value = extractvalue {{ i64, i1 }} %{name}, 0
'''


TRAP = '''trap:
  call void @llvm.trap()
  unreachable
'''


def guarded(parameters, guard, operation, left, right):
    """`@f(PARAMETERS)`: GUARD (instructions ending in `%guard`) taken to the checked
    operation, else -1."""
    return module(f'''define i64 @f({parameters}) {{
entry:
{guard}  br i1 %guard, label %body, label %invalid
body:
{checked(operation, left, right)}  ret i64 %checked.value
invalid:
  ret i64 -1
{TRAP}}}
''')


def varied(text, *replacements):
    """TEXT with each (old, new) replacement made everywhere."""
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    return text


SUM = module('''define i64 @sum(ptr %values, i64 %count) {
entry:
  %large = icmp ugt i64 %count, 1000
  br i1 %large, label %invalid, label %check
check:
  %empty = icmp eq i64 %count, 0
  br i1 %empty, label %invalid, label %loop
loop:
  %index = phi i64 [0, %check], [%next, %latch]
  %total = phi i64 [0, %check], [%added, %latch]
  %address = getelementptr i64, ptr %values, i64 %index
  %value = load i64, ptr %address, !range !0
  %pair = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %total, i64 %value)
  %overflow = extractvalue { i64, i1 } %pair, 1
  br i1 %overflow, label %trap, label %latch
trap:
  call void @llvm.trap()
  unreachable
latch:
  %added = extractvalue { i64, i1 } %pair, 0
  %next = add i64 %index, 1
  %done = icmp eq i64 %next, %count
  br i1 %done, label %exit, label %loop
exit:
  ret i64 %added
invalid:
  ret i64 -1
}
!0 = !{i64 -1000000, i64 1000001}
''')

STACK = module('''define i64 @stack(ptr %codes, i64 %count) {
entry:
  %large = icmp ugt i64 %count, 512
  br i1 %large, label %invalid, label %check
check:
  %empty = icmp eq i64 %count, 0
  br i1 %empty, label %invalid, label %loop
loop:
  %index = phi i64 [0, %check], [%next, %latch]
  %top = phi i64 [0, %check], [%moved, %latch]
  %address = getelementptr i64, ptr %codes, i64 %index
  %code = load i64, ptr %address
  %push = icmp eq i64 %code, 0
  br i1 %push, label %pushing, label %popping
pushing:
  %full = icmp eq i64 %top, 256
  br i1 %full, label %invalid, label %pushed
pushed:
  %up = add i64 %top, 1
  br label %latch
popping:
  %bottom = icmp eq i64 %top, 0
  br i1 %bottom, label %invalid, label %popped
popped:
  %down = add i64 %top, -1
  br label %latch
latch:
  %moved = phi i64 [%up, %pushed], [%down, %popped]
  %next = add i64 %index, 1
  %done = icmp eq i64 %next, %count
  br i1 %done, label %exit, label %loop
exit:
  %last = phi i64 [%moved, %latch]
  %pair = call { i64, i1 } @llvm.smul.with.overflow.i64(i64 %last, i64 20000000000000000)
  %overflow = extractvalue { i64, i1 } %pair, 1
  br i1 %overflow, label %trap, label %done.exit
trap:
  call void @llvm.trap()
  unreachable
done.exit:
  %scaled = extractvalue { i64, i1 } %pair, 0
  ret i64 %scaled
invalid:
  ret i64 -1
}
''')

TOTIENT = module('''define i64 @totient(i64 %argument, i64 %other) {
entry:
  %n = freeze i64 %argument
  %low = icmp slt i64 %n, 1
  br i1 %low, label %invalid, label %check
check:
  %high = icmp sgt i64 %n, 1000000
  br i1 %high, label %invalid, label %head
head:
  %result = phi i64 [ %n, %check ], [ %result.next, %stepped ]
  %remaining = phi i64 [ %n, %check ], [ %remaining.next, %stepped ]
  %factor = phi i64 [ 2, %check ], [ %factor.next, %stepped ]
  %quotient = sdiv i64 %remaining, %factor
  %past = icmp sgt i64 %factor, %quotient
  br i1 %past, label %exit, label %body
body:
  %product = mul i64 %quotient, %factor
  %divides = icmp eq i64 %remaining, %product
  br i1 %divides, label %inner, label %latch
inner:
  %left = phi i64 [ %remaining, %body ], [ %divided, %inner ]
  %divided = sdiv i64 %left, %factor
  %back = mul i64 %divided, %factor
  %again = icmp eq i64 %left, %back
  br i1 %again, label %inner, label %reduce
reduce:
  %share = sdiv i64 %result, %factor
  %pair = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 %result, i64 %share)
  %overflow = extractvalue { i64, i1 } %pair, 1
  br i1 %overflow, label %trap, label %reduced
reduced:
  %smaller = extractvalue { i64, i1 } %pair, 0
  br label %latch
latch:
  %result.next = phi i64 [ %result, %body ], [ %smaller, %reduced ]
  %remaining.next = phi i64 [ %remaining, %body ], [ %left, %reduced ]
  %step = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %factor, i64 1)
  %step.overflow = extractvalue { i64, i1 } %step, 1
  br i1 %step.overflow, label %trap, label %stepped
stepped:
  %factor.next = extractvalue { i64, i1 } %step, 0
  br label %head
exit:
  %rest = icmp sgt i64 %remaining, 1
  br i1 %rest, label %last, label %done
last:
  %last.share = sdiv i64 %result, %remaining
  %last.pair = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 %result, i64 %last.share)
  %last.overflow = extractvalue { i64, i1 } %last.pair, 1
  br i1 %last.overflow, label %trap, label %last.done
last.done:
  %final = extractvalue { i64, i1 } %last.pair, 0
  ret i64 %final
done:
  ret i64 %result
trap:
  call void @llvm.trap()
  unreachable
invalid:
  ret i64 -1
}
''')

BISECTION = module('''define i64 @search(ptr %values, i64 noundef %count, i64 %wanted) {
entry:
  %small = icmp slt i64 %count, 1000
  br i1 %small, label %head, label %invalid
head:
  %low = phi i64 [0, %entry], [%low.next, %latch]
  %high = phi i64 [%count, %entry], [%high.next, %latch]
  %more = icmp slt i64 %low, %high
  br i1 %more, label %body, label %exit
body:
  %sum = add nsw i64 %low, %high
  %middle = sdiv i64 %sum, 2
''' + checked('sadd', '%middle', '9223372036854774000') + '''  %address = getelementptr i64, ptr %values, i64 %middle
  %value = load i64, ptr %address
  %less = icmp slt i64 %value, %wanted
  br label %latch
latch:
  %low.next = select i1 %less, i64 %middle, i64 %low
  %high.next = select i1 %less, i64 %high, i64 %middle
  %stuck = icmp eq i64 %low.next, %low
  br i1 %stuck, label %exit, label %head
exit:
  ret i64 %low
invalid:
  ret i64 -1
''' + TRAP + '}\n')

FIELDS = module('''define internal i64 @helper({ i64, i64 } %pair) {
entry:
  %first = extractvalue { i64, i64 } %pair, 0
''' + checked('smul', '%first', '%first') + '''  ret i64 %checked.value
''' + TRAP + '''}
define i64 @constant_caller() {
  %partial = insertvalue { i64, i64 } poison, i64 1000, 0
  %pair = insertvalue { i64, i64 } %partial, i64 5, 1
  %result = call i64 @helper({ i64, i64 } %pair)
  ret i64 %result
}
define i64 @narrow_caller(i32 %narrow) {
  %wide = sext i32 %narrow to i64
  %partial = insertvalue { i64, i64 } poison, i64 %wide, 0
  %pair = insertvalue { i64, i64 } %partial, i64 7, 1
  %result = call i64 @helper({ i64, i64 } %pair)
  ret i64 %result
}
''')

SPLIT = module('''define i64 @f(i64 noundef %x, i64 noundef %y) {
entry:
  %bit = and i64 %x, 1
  %other = xor i64 %bit, 1
  %first = mul i64 %bit, 9000000000000000000
  %second = mul i64 %other, 9000000000000000000
  %guard = icmp slt i64 %y, 5
  br i1 %guard, label %body, label %invalid
body:
''' + checked('sadd', '%first', '%second') + '''  ret i64 %checked.value
invalid:
  ret i64 -1
''' + TRAP + '}\n')


def summed_helper(checks):
    """A private helper over two aggregates and a guarded index with CHECKS checked adds."""
    lines = ''
    previous = '%index'
    for number in range(checks):
        lines += f'''  %step{number} = call {{ i64, i1 }} @llvm.sadd.with.overflow.i64(i64 %index, i64 {number + 1})
  %value{number} = extractvalue {{ i64, i1 }} %step{number}, 0
  %total{number} = add i64 {previous}, %value{number}
'''
        previous = f'%total{number}'
    return f'''define internal i64 @helper([4 x i64] %first, [4 x i64] %second, i64 noundef %index) {{
entry:
  %guard = icmp ult i64 %index, 100
  br i1 %guard, label %body, label %invalid
body:
{lines}  ret i64 {previous}
invalid:
  ret i64 -1
}}
'''


RELATED = module(summed_helper(8) + '''define i64 @caller([4 x i64] %first, [4 x i64] %second) {
  %one = call i64 @helper([4 x i64] %first, [4 x i64] %second, i64 1)
  %two = call i64 @helper([4 x i64] %first, [4 x i64] %second, i64 2)
  %both = add i64 %one, %two
  ret i64 %both
}
''')

UNSTABLE = module('''define i64 @f(ptr %input) {
entry:
  %raw = load i32, ptr %input
  %small = icmp ult i32 %raw, 20
  br i1 %small, label %body, label %invalid
body:
  %wide = sext i32 %raw to i64
''' + checked('smul', '%wide', '461168601842738790') + '''  ret i64 %checked.value
invalid:
  ret i64 -1
''' + TRAP + '}\n')

WALK = module('''define internal void @walk({ ptr, i64 } %view, i64 %first, i64 %second) {
entry:
  %length = extractvalue { ptr, i64 } %view, 1
  %first.in = icmp ult i64 %first, %length
  br i1 %first.in, label %check, label %trap
check:
  %length.again = extractvalue { ptr, i64 } %view, 1
  %second.in = icmp ult i64 %second, %length.again
  br i1 %second.in, label %body, label %second.trap
body:
  %data = extractvalue { ptr, i64 } %view, 0
  %address = getelementptr i64, ptr %data, i64 %first
  %value = load i64, ptr %address
  %stop = icmp eq i64 %value, 0
  br i1 %stop, label %done, label %recurse
recurse:
  store i64 0, ptr %address
  call void @walk({ ptr, i64 } %view, i64 %second, i64 %first)
  br label %done
done:
  ret void
trap:
  call void @llvm.trap()
  unreachable
second.trap:
  call void @llvm.trap()
  unreachable
}
define void @start(ptr %data) {
  %partial = insertvalue { ptr, i64 } poison, ptr %data, 0
  %view = insertvalue { ptr, i64 } %partial, i64 10, 1
  call void @walk({ ptr, i64 } %view, i64 0, i64 3)
  ret void
}
''')
GUARDED_WALK = varied(WALK, ('define void @start(ptr %data) {\n', 'define void @start(ptr %data, i64 noundef %count) {\n  %enough = icmp ugt i64 %count, 5\n  br i1 %enough, label %call, label %skip\ncall:\n'), ('i64 10, 1', 'i64 %count, 1'), ('i64 0, i64 3)\n  ret void\n}', 'i64 0, i64 3)\n  ret void\nskip:\n  ret void\n}'))

LINUX = 'x86_64-unknown-linux-gnu'

# (pass, IR) per case; every case runs with a generic CPU's target machine.
CASES = {
    'sum': ('proven-signed-checks', SUM),
    'sum-unbounded-count': ('proven-signed-checks', varied(SUM, ('icmp ugt i64 %count, 1000', 'icmp eq i64 %count, 7'))),
    'sum-empty-count': ('proven-signed-checks', varied(SUM, ('icmp eq i64 %count, 0', 'icmp eq i64 %count, 5'))),
    'sum-large-terms': ('proven-signed-checks', varied(SUM, ('!{i64 -1000000, i64 1000001}', '!{i64 -4611686018427387904, i64 4611686018427387904}'))),
    'sum-step-two': ('proven-signed-checks', varied(SUM, ('add i64 %index, 1', 'add i64 %index, 2'))),
    'sum-twice': ('proven-signed-checks', varied(SUM, ('%added = extractvalue { i64, i1 } %pair, 0', '%once = extractvalue { i64, i1 } %pair, 0\n  %added = add i64 %once, %value'))),
    'stack': ('proven-signed-checks', STACK),
    'stack-unguarded-push': ('proven-signed-checks', varied(STACK, ('br i1 %full, label %invalid, label %pushed', 'br label %pushed'))),
    'stack-push-two': ('proven-signed-checks', varied(STACK, ('add i64 %top, 1', 'add i64 %top, 2'))),
    'stack-wide-capacity': ('proven-signed-checks', varied(STACK, ('icmp eq i64 %top, 256', 'icmp eq i64 %top, 100000'))),
    'totient': ('proven-signed-checks', TOTIENT),
    'totient-negative-start': ('proven-signed-checks', varied(TOTIENT, ('br i1 %low, label %invalid, label %check', 'br label %check'))),
    'totient-growing-result': ('proven-signed-checks', varied(TOTIENT, ('ssub.with.overflow.i64(i64 %result, i64 %share)', 'sadd.with.overflow.i64(i64 %result, i64 %share)'))),
    'totient-negative-divisor': ('proven-signed-checks', varied(TOTIENT, ('[ 2, %check ]', '[ -1, %check ]'))),
    'totient-unbounded-guard': ('proven-signed-checks', varied(TOTIENT, ('icmp sgt i64 %factor, %quotient', 'icmp sgt i64 %factor, %other'))),
    'guarded-parameter': ('proven-signed-checks', guarded('i64 %x', '  %guard = icmp ult i64 %x, 1000\n', 'smul', '%x', '%x')),
    'guarded-noundef': ('proven-signed-checks', guarded('i64 noundef %x', '  %guard = icmp ult i64 %x, 1000\n', 'smul', '%x', '%x')),
    'guarded-too-wide': ('proven-signed-checks', guarded('i64 noundef %x', '  %guard = icmp ult i64 %x, 4000000000\n', 'smul', '%x', '%x')),
    'absolute-guard': ('proven-signed-checks', guarded('i64 noundef %x', '  %size = call i64 @llvm.abs.i64(i64 %x, i1 false)\n  %guard = icmp ule i64 %size, 3000000000\n', 'smul', '%x', '%x')),
    'offset-guard': ('proven-signed-checks', guarded('i64 noundef %x', '  %shifted = add i64 %x, 5\n  %guard = icmp ult i64 %shifted, 100\n', 'sadd', '%x', '9223372036854775700')),
    'both-guards': ('proven-signed-checks', guarded('i64 noundef %x', '  %above = icmp sgt i64 %x, -10\n  %below = icmp slt i64 %x, 10\n  %guard = and i1 %above, %below\n', 'smul', '%x', '922337203685477580')),
    'select-guards': ('proven-signed-checks', guarded('i64 noundef %x', '  %above = icmp sgt i64 %x, -10\n  %below = icmp slt i64 %x, 10\n  %guard = select i1 %above, i1 %below, i1 false\n', 'smul', '%x', '922337203685477580')),
    'either-guard-rejects': ('proven-signed-checks', guarded('i64 noundef %x', '  %under = icmp slt i64 %x, -10\n  %over = icmp sgt i64 %x, 10\n  %outside = or i1 %under, %over\n  %guard = xor i1 %outside, true\n', 'smul', '%x', '922337203685477580')),
    'narrowed-cast': ('proven-signed-checks', guarded('i64 noundef %x', '  %narrow = trunc i64 %x to i32\n  %wide = sext i32 %narrow to i64\n  %guard = icmp ne i64 %x, 0\n', 'smul', '%wide', '2147483648')),
    'zero-extended-cast': ('proven-signed-checks', guarded('i64 noundef %x', '  %narrow = trunc i64 %x to i32\n  %wide = zext i32 %narrow to i64\n  %guard = icmp ne i64 %x, 0\n', 'smul', '%wide', '2147483648')),
    'exact-quotient': ('proven-signed-checks', guarded('i64 noundef %x', '  %above = icmp sgt i64 %x, 15\n  %below = icmp slt i64 %x, 1000\n  %guard = and i1 %above, %below\n  %third = udiv exact i64 %x, 3\n', 'smul', '%third', '27670116110564327')),
    'ranged-load': ('proven-signed-checks', module('''define i64 @f(ptr %input) {
entry:
  %raw = load i64, ptr %input, !range !0
  %value = freeze i64 %raw
''' + checked('sadd', '%value', '9223372036854775000') + '''  ret i64 %checked.value
''' + TRAP + '''}
!0 = !{i64 0, i64 800}
''')),
    'bisection': ('proven-signed-checks', BISECTION),
    'bisection-unbounded': ('proven-signed-checks', varied(BISECTION, ('icmp slt i64 %count, 1000', 'icmp slt i64 %count, 1000000000000'))),
    'caller-fields': ('proven-signed-checks', FIELDS),
    'caller-fields-wide': ('proven-signed-checks', varied(FIELDS, ('i64 1000, 0', 'i64 5000000000, 0'))),
    'split-bits': ('proven-signed-checks', SPLIT),
    'split-bits-unguarded': ('proven-signed-checks', varied(SPLIT, ('icmp slt i64 %y, 5', 'icmp slt i64 %x, %y'))),
    'related-calls': ('proven-signed-checks', RELATED),
    'related-calls-seven': ('proven-signed-checks', module(summed_helper(7) + RELATED[RELATED.index('define i64 @caller'):])),
    'optnone': ('proven-signed-checks', varied(guarded('i64 noundef %x', '  %guard = icmp ult i64 %x, 1000\n', 'smul', '%x', '%x'), ('define i64 @f(i64 noundef %x) {', 'define i64 @f(i64 noundef %x) noinline optnone {'))),
    'not-aarch64': ('proven-signed-checks', varied(SUM, (TRIPLE, LINUX))),
    'unstable-load': ('refold-proven-signed-checks', UNSTABLE),
    'unstable-load-wide': ('refold-proven-signed-checks', varied(UNSTABLE, ('icmp ult i32 %raw, 20', 'icmp ult i32 %raw, 40'))),
    'refold-sum': ('refold-proven-signed-checks', SUM),
    'walk': ('recursive-argument-bounds', WALK),
    'walk-noundef': ('recursive-argument-bounds', varied(WALK, ('i64 %first, i64 %second) {', 'i64 noundef %first, i64 noundef %second) {'))),
    'walk-first-out-of-range': ('recursive-argument-bounds', varied(WALK, ('i64 0, i64 3)', 'i64 12, i64 3)'))),
    'walk-entry-guard-rejects': ('recursive-argument-bounds', varied(WALK, ('i64 0, i64 3)', 'i64 12, i64 15)'))),
    'walk-guarded-length': ('recursive-argument-bounds', GUARDED_WALK),
    'walk-other-view': ('recursive-argument-bounds', varied(WALK, ('call void @walk({ ptr, i64 } %view, i64 %second', '%other = insertvalue { ptr, i64 } %view, i64 4, 1\n  call void @walk({ ptr, i64 } %other, i64 %second'))),
    'walk-not-aarch64': ('recursive-argument-bounds', varied(WALK, (TRIPLE, LINUX))),
}

# What the C++ passes did with each shape: the count (checks folded, related helper calls
# inlined, or index checks removed), the checked operations, freezes and conditional
# branches left, and the count of a second run.
EXPECTED = {
    'sum': (1, 0, 1, 4, 0),
    'sum-unbounded-count': (0, 1, 0, 4, 0),
    'sum-empty-count': (0, 1, 0, 4, 0),
    'sum-large-terms': (0, 1, 0, 4, 0),
    'sum-step-two': (0, 1, 0, 4, 0),
    'sum-twice': (0, 1, 0, 4, 0),
    'stack': (1, 0, 0, 7, 0),
    'stack-unguarded-push': (0, 1, 0, 6, 0),
    'stack-push-two': (0, 1, 0, 7, 0),
    'stack-wide-capacity': (0, 1, 0, 7, 0),
    'totient': (3, 0, 1, 9, 0),
    'totient-negative-start': (1, 2, 1, 8, 0),
    'totient-growing-result': (1, 2, 1, 9, 0),
    'totient-negative-divisor': (0, 3, 1, 9, 0),
    'totient-unbounded-guard': (2, 1, 1, 9, 0),
    'guarded-parameter': (1, 0, 1, 2, 0),
    'guarded-noundef': (1, 0, 0, 2, 0),
    'guarded-too-wide': (0, 1, 0, 2, 0),
    'absolute-guard': (1, 0, 0, 2, 0),
    'offset-guard': (1, 0, 0, 2, 0),
    'both-guards': (1, 0, 0, 2, 0),
    'select-guards': (1, 0, 0, 2, 0),
    'either-guard-rejects': (0, 1, 0, 2, 0),
    'narrowed-cast': (1, 0, 0, 2, 0),
    'zero-extended-cast': (1, 0, 0, 2, 0),
    'exact-quotient': (1, 0, 0, 2, 0),
    'ranged-load': (1, 0, 1, 1, 0),
    'bisection': (1, 0, 0, 4, 0),
    'bisection-unbounded': (0, 1, 0, 4, 0),
    'caller-fields': (1, 0, 0, 1, 0),
    'caller-fields-wide': (0, 1, 0, 1, 0),
    'split-bits': (1, 0, 0, 2, 0),
    'split-bits-unguarded': (0, 1, 0, 2, 0),
    'related-calls': (10, 0, 0, 1, 0),
    'related-calls-seven': (7, 0, 0, 1, 0),
    'optnone': (0, 1, 0, 2, 0),
    'not-aarch64': (0, 1, 0, 4, 0),
    'unstable-load': (1, 0, 1, 2, 0),
    'unstable-load-wide': (0, 1, 0, 2, 0),
    'refold-sum': (1, 0, 1, 4, 0),
    'walk': (1, 0, 1, 2, 0),
    'walk-noundef': (1, 0, 0, 2, 0),
    'walk-first-out-of-range': (1, 0, 1, 2, 0),
    'walk-entry-guard-rejects': (1, 0, 1, 2, 0),
    'walk-guarded-length': (1, 0, 1, 3, 0),
    'walk-other-view': (0, 0, 0, 3, 0),
    'walk-not-aarch64': (0, 0, 0, 3, 0),
}
