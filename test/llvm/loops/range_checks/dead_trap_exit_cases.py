"""IR shapes for the dead-trap-exit removal, shared by its test.

`dead-trap-exits` makes a loop's trapping exit stay in the loop when the exit's smallest
possible count (backedges taken before it is first taken) is above the largest count of an
exit that never traps. The counts come from scalar evolution, their ranges from lazy value
info on the entry edge and from the guards on the dominating edges. The fixture sums
`data[0, n)` with the check `i < len`, guarded by `n < 100` and `len > 99`; each case varies
one part, and its numbers are what the C++ pass did with the same shape (see EXPECTED).
"""
TRIPLE = 'arm64-apple-darwin'
DECLARATIONS = '''
declare void @llvm.trap()
declare i64 @llvm.umin.i64(i64, i64)
declare i64 @llvm.umax.i64(i64, i64)
declare i64 @llvm.smin.i64(i64, i64)
declare i64 @llvm.smax.i64(i64, i64)
'''


def module(body):
    """BODY as a module for the test triple, with the trap and min/max intrinsics declared."""
    return f'target triple = "{TRIPLE}"\n' + DECLARATIONS + body


def varied(text, *replacements):
    """TEXT with each (old, new) replacement made everywhere."""
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    return text


SUM = module('''define i64 @sum(ptr %data, i64 %n, i64 %len) {
entry:
  %small = icmp ult i64 %n, 100
  br i1 %small, label %sized, label %done
sized:
  %big = icmp ugt i64 %len, 99
  br i1 %big, label %preheader, label %done
preheader:
  %empty = icmp eq i64 %n, 0
  br i1 %empty, label %done, label %loop
loop:
  %i = phi i64 [0, %preheader], [%i.next, %latch]
  %total = phi i64 [0, %preheader], [%total.next, %latch]
  %inside = icmp ult i64 %i, %len
  br i1 %inside, label %latch, label %trap
latch:
  %address = getelementptr i64, ptr %data, i64 %i
  %value = load i64, ptr %address
  %total.next = add i64 %total, %value
  %i.next = add nuw i64 %i, 1
  %more = icmp ult i64 %i.next, %n
  br i1 %more, label %loop, label %finish
finish:
  ret i64 %total.next
done:
  ret i64 0
trap:
  call void @llvm.trap()
  unreachable
}
''')

GUARDS = '''  %small = icmp ult i64 %n, 100
  br i1 %small, label %sized, label %done
sized:
  %big = icmp ugt i64 %len, 99
  br i1 %big, label %preheader, label %done'''


# The loop tested at the top, so its exit's count is the limit itself.
TOP_TESTED = varied(SUM, ('  %empty = icmp eq i64 %n, 0\n  br i1 %empty, label %done, label %loop\n', '  br label %loop\n'),
                    ('  %inside = icmp ult i64 %i, %len\n', '  %more = icmp ult i64 %i, %n\n  br i1 %more, label %check, label %finish\ncheck:\n  %inside = icmp ult i64 %i, %len\n'),
                    ('  %more = icmp ult i64 %i.next, %n\n  br i1 %more, label %loop, label %finish\nfinish:\n  ret i64 %total.next', '  br label %loop\nfinish:\n  ret i64 %total'))


def limited(limit):
    """The top-tested loop running to LIMIT, computed in the preheader from n and m."""
    return varied(TOP_TESTED, ('define i64 @sum(ptr %data, i64 %n, i64 %len) {', 'define i64 @sum(ptr %data, i64 %n, i64 %m, i64 %len) {'),
                  ('preheader:\n  br label %loop', f'preheader:\n  %limit = {limit}\n  br label %loop'),
                  ('icmp ult i64 %i, %n', 'icmp ult i64 %i, %limit'))


# The count n as the zero extension of a guarded i32.
WIDENED = varied(SUM, ('define i64 @sum(ptr %data, i64 %n, i64 %len) {\nentry:\n  %small = icmp ult i64 %n, 100',
                       'define i64 @sum(ptr %data, i32 %narrow, i64 %len) {\nentry:\n  %n = zext i32 %narrow to i64\n  %small = icmp ult i32 %narrow, 100'))

NESTED = module('''define i64 @rows(ptr %data, i64 %n, i64 %len, i64 %rows) {
entry:
  %small = icmp ult i64 %n, 100
  br i1 %small, label %sized, label %done
sized:
  %big = icmp ugt i64 %len, 99
  br i1 %big, label %outer, label %done
outer:
  %row = phi i64 [0, %sized], [%row.next, %outer.latch]
  %sum = phi i64 [0, %sized], [%sum.next, %outer.latch]
  %empty = icmp eq i64 %n, 0
  br i1 %empty, label %outer.latch, label %loop
loop:
  %i = phi i64 [0, %outer], [%i.next, %latch]
  %total = phi i64 [0, %outer], [%total.next, %latch]
  %inside = icmp ult i64 %i, %len
  br i1 %inside, label %latch, label %trap
latch:
  %address = getelementptr i64, ptr %data, i64 %i
  %value = load i64, ptr %address
  %total.next = add i64 %total, %value
  %i.next = add nuw i64 %i, 1
  %more = icmp ult i64 %i.next, %n
  br i1 %more, label %loop, label %outer.latch
outer.latch:
  %row.total = phi i64 [0, %outer], [%total.next, %latch]
  %sum.next = add i64 %sum, %row.total
  %row.next = add i64 %row, 1
  %again = icmp ult i64 %row.next, %rows
  br i1 %again, label %outer, label %finish
finish:
  ret i64 %sum.next
done:
  ret i64 0
trap:
  call void @llvm.trap()
  unreachable
}
''')

# A first loop between the guards and the checked loop.
AFTER_LOOP = varied(SUM, ('''preheader:
  %empty = icmp eq i64 %n, 0''', '''preheader:
  br label %warm
warm:
  %w = phi i64 [0, %preheader], [%w.next, %warm]
  %w.next = add i64 %w, 1
  %warm.more = icmp ult i64 %w.next, %len
  br i1 %warm.more, label %warm, label %warmed
warmed:
  %empty = icmp eq i64 %n, 0'''), ('[0, %preheader], [%i.next', '[0, %warmed], [%i.next'), ('[0, %preheader], [%total.next', '[0, %warmed], [%total.next'))

CASES = {
    'sum': SUM,
    'short-array': varied(SUM, ('icmp ugt i64 %len, 99', 'icmp ugt i64 %len, 50')),
    'exact-fit': varied(SUM, ('icmp ugt i64 %len, 99', 'icmp ugt i64 %len, 98')),
    'unguarded-length': varied(SUM, ('  %big = icmp ugt i64 %len, 99\n  br i1 %big, label %preheader, label %done', '  br label %preheader')),
    'unguarded-count': varied(SUM, ('  %small = icmp ult i64 %n, 100\n  br i1 %small, label %sized, label %done', '  br label %sized')),
    'inverted-guard': varied(SUM, ('  %big = icmp ugt i64 %len, 99\n  br i1 %big, label %preheader, label %done', '  %short = icmp ule i64 %len, 99\n  br i1 %short, label %done, label %preheader')),
    'offset-guard': varied(SUM, ('  %big = icmp ugt i64 %len, 99', '  %room = add i64 %len, -100\n  %big = icmp ult i64 %room, 1000')),
    'and-guard': varied(SUM, (GUARDS, '  %small = icmp ult i64 %n, 100\n  %big = icmp ugt i64 %len, 99\n  %both = and i1 %small, %big\n  br i1 %both, label %sized, label %done\nsized:\n  br label %preheader')),
    'select-and-guard': varied(SUM, (GUARDS, '  %small = icmp ult i64 %n, 100\n  %big = icmp ugt i64 %len, 99\n  %both = select i1 %small, i1 %big, i1 false\n  br i1 %both, label %sized, label %done\nsized:\n  br label %preheader')),
    'or-guard': varied(SUM, (GUARDS, '  %large = icmp uge i64 %n, 100\n  %tiny = icmp ule i64 %len, 99\n  %either = or i1 %large, %tiny\n  br i1 %either, label %done, label %sized\nsized:\n  br label %preheader')),
    'after-earlier-loop': AFTER_LOOP,
    'trap-in-latch': varied(SUM, ('  %inside = icmp ult i64 %i, %len\n  br i1 %inside, label %latch, label %trap\nlatch:\n', '  br label %latch\nlatch:\n'),
                            ('  br i1 %more, label %loop, label %finish', '  %inside = icmp ult i64 %i.next, %len\n  br i1 %inside, label %check, label %trap\ncheck:\n  br i1 %more, label %loop, label %finish'),
                            ('[%i.next, %latch]', '[%i.next, %check]'), ('[%total.next, %latch]', '[%total.next, %check]')),
    'top-tested': TOP_TESTED,
    'only-traps': varied(SUM, ('br i1 %more, label %loop, label %finish', 'br i1 %more, label %loop, label %trap')),
    'narrow-counter': module(varied(SUM[SUM.index('define'):], ('i64 %n, i64 %len', 'i32 %n, i32 %len'), ('icmp ult i64 %n, 100', 'icmp ult i32 %n, 100'), ('icmp ugt i64 %len, 99', 'icmp ugt i32 %len, 99'),
                                    ('icmp eq i64 %n, 0', 'icmp eq i32 %n, 0'), ('%i = phi i64', '%i = phi i32'), ('icmp ult i64 %i, %len', 'icmp ult i32 %i, %len'), ('ptr %data, i64 %i', 'ptr %data, i32 %i'),
                                    ('add nuw i64 %i, 1', 'add nuw i32 %i, 1'), ('icmp ult i64 %i.next, %n', 'icmp ult i32 %i.next, %n'))),
    'widened-count': WIDENED,
    'widened-top-tested': varied(TOP_TESTED, ('define i64 @sum(ptr %data, i64 %n, i64 %len) {\nentry:\n  %small = icmp ult i64 %n, 100',
                                              'define i64 @sum(ptr %data, i32 %narrow, i64 %len) {\nentry:\n  %n = zext i32 %narrow to i64\n  %small = icmp ult i32 %narrow, 100')),
    'sign-extended-top-tested': varied(TOP_TESTED, ('define i64 @sum(ptr %data, i64 %n, i64 %len) {\nentry:\n  %small = icmp ult i64 %n, 100',
                                                    'define i64 @sum(ptr %data, i32 %narrow, i64 %len) {\nentry:\n  %n = sext i32 %narrow to i64\n  %small = icmp ult i32 %narrow, 100')),
    'truncated-top-tested': varied(TOP_TESTED, ('define i64 @sum(ptr %data, i64 %n, i64 %len) {\nentry:\n  %small = icmp ult i64 %n, 100',
                                                'define i64 @sum(ptr %data, i128 %wide, i64 %len) {\nentry:\n  %n = trunc i128 %wide to i64\n  %small = icmp ult i128 %wide, 100')),
    'unsigned-minimum': limited('call i64 @llvm.umin.i64(i64 %n, i64 %m)'),
    'unsigned-minimum-wide': limited('call i64 @llvm.umin.i64(i64 %m, i64 1000)'),
    'unsigned-maximum-of-constant': limited('call i64 @llvm.umax.i64(i64 %n, i64 7)'),
    'signed-minimum-of-constant': limited('call i64 @llvm.smin.i64(i64 %n, i64 7)'),
    'signed-maximum-of-constant': limited('call i64 @llvm.smax.i64(i64 %n, i64 7)'),
    'halved-count': limited('lshr i64 %n, 1'),
    'masked-count': limited('and i64 %m, 63'),
    'unsigned-maximum': limited('call i64 @llvm.umax.i64(i64 %n, i64 %m)'),
    'signed-minimum': limited('call i64 @llvm.smin.i64(i64 %n, i64 %m)'),
    'signed-maximum': limited('call i64 @llvm.smax.i64(i64 %n, i64 %m)'),
    'doubled-count': limited('shl nuw i64 %n, 1'),
    'doubled-count-long-array': varied(limited('shl nuw i64 %n, 1'), ('icmp ugt i64 %len, 99', 'icmp ugt i64 %len, 299')),
    'scaled-count-long-array': varied(limited('mul nuw i64 %n, 3'), ('icmp ugt i64 %len, 99', 'icmp ugt i64 %len, 299')),
    'scaled-count': limited('mul nuw i64 %n, 3'),
    'quartered-count': limited('udiv i64 %n, 4'),
    'nested': NESTED,
    'no-loop': module('''define i64 @plain(i64 %a) {
  %b = add i64 %a, 1
  ret i64 %b
}
'''),
    'two-functions': SUM + varied(SUM[SUM.index('define'):], ('@sum(', '@sum2('), ('icmp ugt i64 %len, 99', 'icmp ugt i64 %len, 50')) + varied(SUM[SUM.index('define'):], ('@sum(', '@sum3(')),
}

# (functions changed, branches on a constant, a second run's count) per case.
EXPECTED = {
    'sum': (1, 1, 0),
    'short-array': (0, 0, 0),
    'exact-fit': (1, 1, 0),
    'unguarded-length': (0, 0, 0),
    'unguarded-count': (0, 0, 0),
    'inverted-guard': (1, 1, 0),
    'offset-guard': (1, 1, 0),
    'and-guard': (1, 1, 0),
    'select-and-guard': (1, 1, 0),
    'or-guard': (1, 1, 0),
    'after-earlier-loop': (1, 1, 0),
    'trap-in-latch': (1, 1, 0),
    'top-tested': (1, 1, 0),
    'only-traps': (0, 0, 0),
    'narrow-counter': (0, 0, 0),
    'widened-count': (0, 0, 0),
    'widened-top-tested': (1, 1, 0),
    'sign-extended-top-tested': (1, 1, 0),
    'truncated-top-tested': (1, 1, 0),
    'unsigned-minimum': (1, 1, 0),
    'unsigned-minimum-wide': (0, 0, 0),
    'unsigned-maximum-of-constant': (1, 1, 0),
    'signed-minimum-of-constant': (1, 1, 0),
    'signed-maximum-of-constant': (1, 1, 0),
    'halved-count': (0, 0, 0),
    'masked-count': (1, 1, 0),
    'unsigned-maximum': (0, 0, 0),
    'signed-minimum': (0, 0, 0),
    'signed-maximum': (0, 0, 0),
    'doubled-count': (0, 0, 0),
    'doubled-count-long-array': (1, 1, 0),
    'scaled-count-long-array': (1, 1, 0),
    'scaled-count': (0, 0, 0),
    'quartered-count': (0, 0, 0),
    'nested': (1, 1, 0),
    'no-loop': (0, 0, 0),
    'two-functions': (2, 2, 0),
}
