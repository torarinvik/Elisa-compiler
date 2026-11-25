"""IR shapes for the full-array-initializer removal, shared by its test.

`full-array-initializers` removes the zero fill of a private i64 array of 16 to 4096
elements when a counted loop stores every element from 0 up before any read: the loop's
latch stores `buffer[i]`, steps `i` by one from zero and leaves at the element count, and
that exit edge dominates every load. The fixture fills 16 elements with `3 * i` and reads
one back; each case varies one part, and its numbers are what the C++ pass did with the
same shape (see EXPECTED).
"""
TRIPLE = 'arm64-apple-darwin'
DECLARATIONS = '''
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)
declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1)
declare void @llvm.lifetime.start.p0(ptr)
declare void @llvm.lifetime.end.p0(ptr)
declare void @use(ptr)
'''


def module(body, triple=TRIPLE):
    """BODY as a module for TRIPLE, with the memory intrinsics declared."""
    return f'target triple = "{triple}"\n' + DECLARATIONS + body


def varied(text, *replacements):
    """TEXT with each (old, new) replacement made everywhere."""
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    return text


FILL_BODY = '''define i64 @fill(i64 %k, ptr %source) {
entry:
  %buffer = alloca [16 x i64]
  call void @llvm.memset.p0.i64(ptr %buffer, i8 0, i64 128, i1 false)
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%i.next, %loop]
  %address = getelementptr i64, ptr %buffer, i64 %i
  %value = mul i64 %i, 3
  store i64 %value, ptr %address
  %i.next = add i64 %i, 1
  %filled = icmp eq i64 %i.next, 16
  br i1 %filled, label %read, label %loop
read:
  %slot = getelementptr i64, ptr %buffer, i64 %k
  %result = load i64, ptr %slot
  ret i64 %result
}
'''
FILL = module(FILL_BODY)

CASES = {
    'counted-fill': FILL,
    'not-equal-exit': varied(FILL, ('icmp eq i64 %i.next, 16', 'icmp ne i64 %i.next, 16'),
                             ('label %read, label %loop', 'label %loop, label %read')),
    'short-count': varied(FILL, ('icmp eq i64 %i.next, 16', 'icmp eq i64 %i.next, 15')),
    'starts-at-one': varied(FILL, ('[0, %entry]', '[1, %entry]')),
    'steps-by-two': varied(FILL, ('add i64 %i, 1', 'add i64 %i, 2')),
    'same-sign-compare': varied(FILL, ('icmp eq i64', 'icmp samesign eq i64')),
    'read-before-fill': varied(FILL, ('  br label %loop\nloop', '  %early = load i64, ptr %buffer\n  br label %loop\nloop')),
    'no-reads': varied(FILL, ('  %slot = getelementptr i64, ptr %buffer, i64 %k\n  %result = load i64, ptr %slot\n  ret i64 %result',
                              '  ret i64 0')),
    'small-array': varied(FILL, ('[16 x i64]', '[8 x i64]'), ('i64 128, i1', 'i64 64, i1'), ('%i.next, 16', '%i.next, 8')),
    'partial-fill-length': varied(FILL, ('i64 128, i1', 'i64 64, i1')),
    'i32-elements': varied(FILL, ('[16 x i64]', '[16 x i32]'), ('i64 128, i1', 'i64 64, i1'),
                           ('getelementptr i64', 'getelementptr i32'), ('store i64 %value', '%narrow = trunc i64 %value to i32\n  store i32 %narrow'),
                           ('load i64, ptr %slot', 'load i32, ptr %slot\n  %wide = zext i32 %result to i64'), ('ret i64 %result', 'ret i64 %wide')),
    'escaped': varied(FILL, ('read:\n', 'read:\n  call void @use(ptr %buffer)\n')),
    'lifetimes': varied(FILL, ('  call void @llvm.memset', '  call void @llvm.lifetime.start.p0(ptr %buffer)\n  call void @llvm.memset'),
                        ('  ret i64 %result', '  call void @llvm.lifetime.end.p0(ptr %buffer)\n  ret i64 %result')),
    'copied-in': varied(FILL, ('read:\n', 'read:\n  call void @llvm.memcpy.p0.p0.i64(ptr %buffer, ptr %source, i64 8, i1 false)\n')),
    'early-exit-to-read': varied(FILL, ('  %address = getelementptr i64, ptr %buffer, i64 %i\n',
                                        '  %stop = icmp eq i64 %k, %i\n  br i1 %stop, label %read, label %body\nbody:\n  %address = getelementptr i64, ptr %buffer, i64 %i\n'),
                                 ('[%i.next, %loop]', '[%i.next, %body]')),
    'linux-target': module(FILL_BODY, 'aarch64-unknown-linux-gnu'),
    'x86-target': module(FILL_BODY, 'x86_64-apple-darwin'),
}

# Per case: the count of fills removed, the zero fills the module is left with, and a
# second run's count.
EXPECTED = {
    'counted-fill': (1, 0, 0),
    'not-equal-exit': (1, 0, 0),
    'short-count': (0, 1, 0),
    'starts-at-one': (0, 1, 0),
    'steps-by-two': (0, 1, 0),
    'same-sign-compare': (0, 1, 0),
    'read-before-fill': (0, 1, 0),
    'no-reads': (0, 1, 0),
    'small-array': (0, 1, 0),
    'partial-fill-length': (0, 1, 0),
    'i32-elements': (0, 1, 0),
    'escaped': (0, 1, 0),
    'lifetimes': (1, 0, 0),
    'copied-in': (1, 0, 0),
    'early-exit-to-read': (0, 1, 0),
    'linux-target': (1, 0, 0),
    'x86-target': (0, 1, 0),
}
