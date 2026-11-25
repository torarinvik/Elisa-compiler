"""IR shapes for the copied-scratch initializer removal, shared by its test.

`copied-scratch` removes the zero fill of a private byte buffer whose one reader copies a
prefix out of it, when for every value of an argument the guards allow (at most 64 of
them) the stores a counted loop and the path after it make cover every copied byte. The
fixture fills `buffer[0, n)` byte by byte for `n < 4` and copies `n` bytes out; each case
varies one part, and its numbers are what the C++ pass did with the same shape (see
EXPECTED), except where EXPECTED says otherwise.
"""
TRIPLE = 'aarch64-unknown-linux-gnu'
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


COPY_BODY = '''define void @copy(ptr %out, i64 noundef %n, i1 %flag) {
entry:
  %buffer = alloca [16 x i8]
  call void @llvm.memset.p0.i64(ptr %buffer, i8 0, i64 16, i1 false)
  %small = icmp ult i64 %n, 4
  br i1 %small, label %preheader, label %done
preheader:
  br label %loop
loop:
  %i = phi i64 [0, %preheader], [%i.next, %loop]
  %address = getelementptr i8, ptr %buffer, i64 %i
  store i8 7, ptr %address
  %i.next = add nuw i64 %i, 1
  %more = icmp ult i64 %i.next, %n
  br i1 %more, label %loop, label %copy
copy:
  call void @llvm.memcpy.p0.p0.i64(ptr %out, ptr %buffer, i64 %n, i1 false)
  br label %done
done:
  ret void
}
'''
COPY = module(COPY_BODY)
LONGER = ('i64 %n, i1 false)', 'i64 %n.plus, i1 false)')
LONGER_LENGTH = ('copy:\n', 'copy:\n  %n.plus = add i64 %n, 1\n')
UNDEF = ('i64 noundef %n', 'i64 %n')
# The copy reached through a branch on BRANCH_CONDITION, whose other side spins in a loop
# of its own before it copies.
BRANCHED = varied(COPY, ('label %loop, label %copy', 'label %loop, label %after'), ('copy:\n', '''after:
  BRANCH_CONDITION
  br i1 %wide, label %copy, label %spin
spin:
  br i1 %flag, label %spin, label %copy
copy:
'''))

CASES = {
    'counted-fill': COPY,
    'wide-range': varied(COPY, ('icmp ult i64 %n, 4', 'icmp ult i64 %n, 100')),
    'past-capacity': varied(COPY, ('[16 x i8]', '[2 x i8]'), ('i64 16, i1', 'i64 2, i1')),
    'longer-copy': varied(COPY, LONGER, LONGER_LENGTH),
    'store-after-loop': varied(COPY, LONGER, ('copy:\n', '''copy:
  %n.plus = add i64 %n, 1
  %tail = getelementptr i8, ptr %buffer, i64 %n
  store i8 9, ptr %tail
''')),
    'wide-stores': varied(COPY, ('getelementptr i8, ptr %buffer', 'getelementptr i32, ptr %buffer'),
                          ('store i8 7', 'store i32 7'), LONGER,
                          ('copy:\n', 'copy:\n  %n.plus = shl i64 %n, 2\n')),
    'narrow-store': varied(COPY, ('store i8 7', 'store i1 true')),
    'may-be-undef': varied(COPY, UNDEF),
    'may-be-undef-uncovered': varied(COPY, UNDEF, LONGER, LONGER_LENGTH),
    'filled-again': varied(COPY, ('copy:\n', 'copy:\n  call void @llvm.memcpy.p0.p0.i64(ptr %buffer, ptr %out, i64 1, i1 false)\n')),
    'escaped': varied(COPY, ('copy:\n', 'copy:\n  call void @use(ptr %buffer)\n')),
    'lifetimes': varied(COPY, ('  call void @llvm.memset', '  call void @llvm.lifetime.start.p0(ptr %buffer)\n  call void @llvm.memset'),
                        ('  br label %done\ndone', '  call void @llvm.lifetime.end.p0(ptr %buffer)\n  br label %done\ndone')),
    'lifetime-ends-early': varied(COPY, ('preheader:\n', 'preheader:\n  call void @llvm.lifetime.end.p0(ptr %buffer)\n')),
    'decided-branch': varied(BRANCHED, ('BRANCH_CONDITION', '%wide = icmp ult i64 %n, 8')),
    'masked-branch': varied(BRANCHED, ('BRANCH_CONDITION', '%masked = and i64 %n, 7\n  %wide = icmp ult i64 %masked, 8')),
    'undecided-branch': varied(BRANCHED, ('BRANCH_CONDITION', '%wide = xor i1 %flag, true')),
    'apple-target': module(COPY_BODY, 'arm64-apple-darwin'),
    # Lengths near 2^64: the range [2^64 - 9, 2^64) ends at 0, which the C++ pass read as an
    # empty set of inputs and so removed the fill; every input is checked here instead.
    'range-ending-at-zero': varied(COPY, ('icmp ult i64 %n, 4', 'icmp ugt i64 %n, -10')),
}

# Per case: the count of fills removed, the zero fills and freezes the module is left with,
# and a second run's count.
EXPECTED = {
    'counted-fill': (1, 0, 0, 0),
    'wide-range': (0, 1, 0, 0),
    'past-capacity': (0, 1, 0, 0),
    'longer-copy': (0, 1, 0, 0),
    'store-after-loop': (1, 0, 0, 0),
    'wide-stores': (1, 0, 0, 0),
    'narrow-store': (0, 1, 0, 0),
    'may-be-undef': (1, 0, 1, 0),
    'may-be-undef-uncovered': (0, 1, 0, 0),
    'filled-again': (0, 1, 0, 0),
    'escaped': (0, 1, 0, 0),
    'lifetimes': (1, 0, 0, 0),
    'lifetime-ends-early': (0, 1, 0, 0),
    'decided-branch': (1, 0, 0, 0),
    'masked-branch': (1, 0, 0, 0),
    'undecided-branch': (0, 1, 0, 0),
    'apple-target': (0, 1, 0, 0),
    'range-ending-at-zero': (0, 1, 0, 0),
}
