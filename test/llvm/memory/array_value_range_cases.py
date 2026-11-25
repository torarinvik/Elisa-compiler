"""IR shapes for the array value ranges, shared by their test.

`array-value-ranges` gives the loads of a zero-filled private integer array `!range`
metadata: the union of zero and the ranges of every value stored into it, when every use
is an element-aligned access, a fill, a copy or a lifetime marker. The fixture fills
`table[0, 8)` with `i & 7` and reads one element back; each case varies one part, and
its numbers are what the C++ pass did with the same shape (see EXPECTED).
"""
TRIPLE = 'arm64-apple-darwin'
DECLARATIONS = '''
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)
declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1)
declare void @use(ptr)
define i64 @count_view({ ptr, i64 } %view) {
  %length = extractvalue { ptr, i64 } %view, 1
  ret i64 %length
}
'''


def module(body):
    """BODY as a module for the test triple, with the memory intrinsics declared."""
    return f'target triple = "{TRIPLE}"\n' + DECLARATIONS + body


def varied(text, *replacements):
    """TEXT with each (old, new) replacement made everywhere."""
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    return text


TABLE = module('''define i64 @values(i64 %x, i64 noundef %d, i64 %k, i1 %flag, ptr %out) {
entry:
  %table = alloca [8 x i64]
  call void @llvm.memset.p0.i64(ptr %table, i8 0, i64 64, i1 false)
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%i.next, %loop]
  %slot = getelementptr i64, ptr %table, i64 %i
  %value = and i64 %i, 7
  store i64 %value, ptr %slot
  %i.next = add nuw i64 %i, 1
  %more = icmp ult i64 %i.next, 8
  br i1 %more, label %loop, label %read
read:
  %masked = and i64 %k, 7
  %at = getelementptr i64, ptr %table, i64 %masked
  %result = load i64, ptr %at
  ret i64 %result
}
''')
STORED = ('%value = and i64 %i, 7', 'STORED_VALUE')
READ = ('  %result = load i64, ptr %at\n', '  %result = load i64, ptr %at\n  EXTRA_READ\n')


def stored(value):
    """TABLE storing VALUE (instructions ending in a definition of %value)."""
    return varied(TABLE, (STORED[0], value))


SECOND = '''  %copy = alloca [8 x i64]
  call void @llvm.memset.p0.i64(ptr %copy, i8 0, i64 64, i1 false)
'''

CASES = {
    'masked-values': TABLE,
    'remainders': stored('%value = srem i64 %x, 7'),
    'guarded-divisor': varied(stored('%value = urem i64 %x, %d'),
                              ('  br label %loop\nloop', '  %small = icmp ult i64 %d, 10\n  br i1 %small, label %loop, label %none\nnone:\n  ret i64 0\nloop')),
    'unguarded-divisor': stored('%value = urem i64 %x, %d'),
    'unfilled': varied(TABLE, ('  call void @llvm.memset.p0.i64(ptr %table, i8 0, i64 64, i1 false)\n', '')),
    'escaped': varied(TABLE, ('read:\n', 'read:\n  call void @use(ptr %table)\n')),
    'unbounded-store': stored('%value = add i64 %x, 0'),
    'own-values': varied(stored('%old = load i64, ptr %table\n  %value = select i1 %flag, i64 %old, i64 3')),
    'phi-of-values': varied(TABLE, ('  %value = and i64 %i, 7\n', ''), ('  store i64 %value', '  br i1 %flag, label %two, label %five\ntwo:\n  br label %join\nfive:\n  br label %join\njoin:\n  %value = phi i64 [2, %two], [5, %five]\n  store i64 %value'),
                            ('[%i.next, %loop]', '[%i.next, %join]'), ('br i1 %more, label %loop, label %read', 'br i1 %more, label %loop, label %read')),
    'select-values': stored('%value = select i1 %flag, i64 1, i64 9'),
    'vector-store': varied(TABLE, ('read:\n', 'read:\n  store <2 x i64> <i64 1, i64 12>, ptr %table\n')),
    'vector-load': varied(TABLE, READ, ('EXTRA_READ', '%pair = load <2 x i64>, ptr %table\n  store <2 x i64> %pair, ptr %out')),
    'copied-array': varied(TABLE, ('  br label %loop\nloop', SECOND + '  br label %loop\nloop'), READ,
                           ('EXTRA_READ', 'call void @llvm.memcpy.p0.p0.i64(ptr %copy, ptr %table, i64 64, i1 false)\n  %copied = load i64, ptr %copy\n  store i64 %copied, ptr %out')),
    'copied-at-offset': varied(TABLE, ('  br label %loop\nloop', SECOND + '  br label %loop\nloop'), READ,
                               ('EXTRA_READ', '%middle = getelementptr i8, ptr %table, i64 4\n  call void @llvm.memcpy.p0.p0.i64(ptr %copy, ptr %middle, i64 16, i1 false)\n  %copied = load i64, ptr %copy\n  store i64 %copied, ptr %out')),
    'loaded-from-other-array': varied(TABLE, ('  br label %loop\nloop', SECOND + '  br label %loop\nloop'), READ,
                                      ('EXTRA_READ', 'store i64 %result, ptr %copy\n  %again = load i64, ptr %copy\n  store i64 %again, ptr %out')),
    'viewed': varied(TABLE, ('read:\n', 'read:\n  %data = insertvalue { ptr, i64 } undef, ptr %table, 0\n  %view = insertvalue { ptr, i64 } %data, i64 8, 1\n  %length = call i64 @count_view({ ptr, i64 } %view)\n')),
    'scaled-byte-index': varied(TABLE, ('%at = getelementptr i64, ptr %table, i64 %masked', '%bytes = shl i64 %masked, 3\n  %at = getelementptr i8, ptr %table, i64 %bytes')),
    'unscaled-byte-index': varied(TABLE, ('%at = getelementptr i64, ptr %table, i64 %masked', '%at = getelementptr i8, ptr %table, i64 %masked')),
    'whole-element-offset': varied(TABLE, ('%at = getelementptr i64, ptr %table, i64 %masked', '%at = getelementptr i8, ptr %table, i64 16')),
    'inside-element-offset': varied(TABLE, ('%at = getelementptr i64, ptr %table, i64 %masked', '%at = getelementptr i8, ptr %table, i64 4')),
    'pattern-fill': varied(TABLE, ('  br label %loop\nloop', '  call void @llvm.memset.p0.i64(ptr %table, i8 -1, i64 16, i1 false)\n  br label %loop\nloop')),
    'i32-elements': varied(TABLE, ('[8 x i64]', '[8 x i32]'), ('i64 64, i1', 'i64 32, i1'), ('getelementptr i64', 'getelementptr i32'),
                           ('store i64 %value', '%narrow = trunc i64 %value to i32\n  store i32 %narrow'),
                           ('%result = load i64, ptr %at', '%narrow.result = load i32, ptr %at\n  %result = zext i32 %narrow.result to i64')),
    'written-prefix': varied(TABLE, ('%table = alloca [8 x i64]', '%table = alloca [8 x i64], !elisa.written.prefix !0'),
                             ('  call void @llvm.memset.p0.i64(ptr %table, i8 0, i64 64, i1 false)\n', '')) + '!0 = !{}\n',
    'existing-range': varied(TABLE, READ, ('EXTRA_READ', '%bounded = load i64, ptr %table, !range !0\n  store i64 %bounded, ptr %out')) + '!0 = !{i64 0, i64 100}\n',
    'volatile-load': varied(TABLE, READ, ('EXTRA_READ', '%volatile = load volatile i64, ptr %table\n  store i64 %volatile, ptr %out')),
}

# Per case: the count of arrays annotated, the `!range` bounds the module's loads carry
# (sorted), and a second run's count.
EXPECTED = {
    'masked-values': (1, ('i64 0, i64 8',), 0),
    'remainders': (1, ('i64 -6, i64 7',), 0),
    'guarded-divisor': (1, ('i64 0, i64 9',), 0),
    'unguarded-divisor': (1, ('i64 0, i64 -1',), 0),
    'unfilled': (0, (), 0),
    'escaped': (0, (), 0),
    'unbounded-store': (0, (), 0),
    'own-values': (1, ('i64 0, i64 4', 'i64 0, i64 4'), 0),
    'phi-of-values': (1, ('i64 0, i64 6',), 0),
    'select-values': (1, ('i64 0, i64 10',), 0),
    'vector-store': (1, ('i64 0, i64 13',), 0),
    'vector-load': (1, ('i64 0, i64 8', 'i64 0, i64 8'), 0),
    'copied-array': (2, ('i64 0, i64 8', 'i64 0, i64 8'), 0),
    'copied-at-offset': (0, (), 0),
    'loaded-from-other-array': (2, ('i64 0, i64 8', 'i64 0, i64 8'), 0),
    'viewed': (0, (), 0),
    'scaled-byte-index': (1, ('i64 0, i64 8',), 0),
    'unscaled-byte-index': (0, (), 0),
    'whole-element-offset': (1, ('i64 0, i64 8',), 0),
    'inside-element-offset': (0, (), 0),
    'pattern-fill': (0, (), 0),
    'i32-elements': (1, ('i32 0, i32 8',), 0),
    'written-prefix': (1, ('i64 0, i64 8',), 0),
    'existing-range': (1, ('i64 0, i64 100', 'i64 0, i64 8'), 0),
    'volatile-load': (0, (), 0),
}
