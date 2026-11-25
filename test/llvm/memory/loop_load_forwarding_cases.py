"""IR shapes for the loop load forwarding, shared by its test.

`loop-load-forwarding` replaces a load of `buffer[i]` in a loop body with the value the
latch stored to `buffer[i + 1]` on the previous iteration, through a header phi whose
entry value is one load before the loop. It needs the latch's last memory write to be
that store into an uncaptured private array, no other write in the loop, and the load to
run on every iteration; a loop without a preheader gets one first. The fixture keeps a
running sum in `buffer`; each case varies one part, and its numbers are what the C++ pass
did with the same shape (see EXPECTED).
"""
TRIPLE = 'arm64-apple-darwin'
DECLARATIONS = '''
declare void @use(ptr)
declare void @tick()
'''


def module(body, triple=TRIPLE):
    """BODY as a module for TRIPLE, with the helper functions declared."""
    return f'target triple = "{triple}"\n' + DECLARATIONS + body


def varied(text, *replacements):
    """TEXT with each (old, new) replacement made everywhere."""
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    return text


SUM_BODY = '''define i64 @sum(i64 %n, i1 %flag) {
entry:
  %buffer = alloca [8 x i64]
  store i64 5, ptr %buffer
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%i.next, %latch]
  %total = phi i64 [0, %entry], [%total.next, %latch]
  %address = getelementptr i64, ptr %buffer, i64 %i
  %value = load i64, ptr %address
  %total.next = add i64 %total, %value
  br label %latch
latch:
  %i.next = add i64 %i, 1
  %next = getelementptr i64, ptr %buffer, i64 %i.next
  store i64 %total.next, ptr %next
  %more = icmp ult i64 %i.next, %n
  br i1 %more, label %loop, label %exit
exit:
  ret i64 %total.next
}
'''
SUM = module(SUM_BODY)
NO_PREHEADER = ('  br label %loop\nloop', '  br i1 %flag, label %loop, label %skip\nskip:\n  ret i64 0\nloop')

CASES = {
    'running-sum': SUM,
    'no-preheader': varied(SUM, NO_PREHEADER),
    'conditional-load': varied(SUM, ('  %address = getelementptr i64, ptr %buffer, i64 %i\n  %value = load i64, ptr %address\n  %total.next = add i64 %total, %value\n  br label %latch\n',
                                     '  br i1 %flag, label %reload, label %latch\nreload:\n  %address = getelementptr i64, ptr %buffer, i64 %i\n  %value = load i64, ptr %address\n  br label %latch\n'),
                               ('latch:\n', 'latch:\n  %total.next = phi i64 [%total, %loop], [%value, %reload]\n')),
    'conditional-load-no-preheader': None,
    'body-writes': varied(SUM, ('  br label %latch\nlatch', '  store i64 1, ptr %buffer\n  br label %latch\nlatch')),
    'body-calls': varied(SUM, ('  br label %latch\nlatch', '  call void @tick()\n  br label %latch\nlatch')),
    'escaped': varied(SUM, ('  br label %loop\nloop', '  call void @use(ptr %buffer)\n  br label %loop\nloop')),
    'call-after-store': varied(SUM, ('  %more =', '  call void @tick()\n  %more =')),
    'same-slot': varied(SUM, ('ptr %buffer, i64 %i.next', 'ptr %buffer, i64 %i')),
    'load-in-latch': varied(SUM, ('  %value = load i64, ptr %address\n  %total.next = add i64 %total, %value\n  br label %latch\nlatch:\n',
                                  '  br label %latch\nlatch:\n  %value = load i64, ptr %address\n  %total.next = add i64 %total, %value\n')),
    'narrower-load': varied(SUM, ('%value = load i64, ptr %address', '%narrow = load i32, ptr %address\n  %value = zext i32 %narrow to i64')),
    'volatile-store': varied(SUM, ('store i64 %total.next', 'store volatile i64 %total.next')),
    'linux-target': module(SUM_BODY, 'aarch64-unknown-linux-gnu'),
    'x86-target': module(SUM_BODY, 'x86_64-apple-darwin'),
}
CASES['conditional-load-no-preheader'] = varied(CASES['conditional-load'], NO_PREHEADER)

# Per case: the count of loops changed, the forwarded loads the module is left with, and a
# second run's count.
EXPECTED = {
    'running-sum': (1, 1, 0),
    'no-preheader': (1, 1, 0),
    'conditional-load': (0, 0, 0),
    'conditional-load-no-preheader': (1, 0, 0),
    'body-writes': (0, 0, 0),
    'body-calls': (0, 0, 0),
    'escaped': (0, 0, 0),
    'call-after-store': (0, 0, 0),
    'same-slot': (0, 0, 0),
    'load-in-latch': (0, 0, 0),
    'narrower-load': (0, 0, 0),
    'volatile-store': (0, 0, 0),
    'linux-target': (1, 1, 0),
    'x86-target': (0, 0, 0),
}
