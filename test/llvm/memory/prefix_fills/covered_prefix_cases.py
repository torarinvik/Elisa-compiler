"""IR shapes for the covered-prefix zero removal, shared by its test.

`covered-prefix-zeros` removes the whole-array zero fill of a private i64 array when a
later fill of its first `count` elements (`count << 3` bytes, no unsigned wrap)
dominates every load and each load's index is proved below `count`. The fixture zeroes
a 16-element array, refills its first `count` elements and reads element `j` behind a
check; each case varies one part, and its numbers are what the C++ pass did with the
same shape (see EXPECTED).
"""
TRIPLE = 'arm64-apple-macosx14.0.0'
HEADER = '''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128-Fn32"
target triple = "TRIPLE"
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)
'''

FIXTURE = '''define i64 @f(i64 %count, i64 %j, i1 %flag) ATTRIBUTES {
entry:
  %buffer = alloca [16 x i64]
  call void @llvm.memset.p0.i64(ptr %buffer, i8 0, i64 128, i1 false)
  %fits = icmp ule i64 %count, 16
  br i1 %fits, label %fill, label %miss
fill:
  %bytes = shl SHIFT_FLAGS i64 %count, SHIFT
  call void @llvm.memset.p0.i64(ptr %buffer, i8 0, i64 %bytes, i1 false)
  CHECK
read:
  %at = getelementptr inbounds i64, ptr %buffer, i64 %j
  %value = load i64, ptr %at
  ret i64 %value
miss:
  ret i64 0
}
'''
PARTS = {
    'ATTRIBUTES': '',
    'SHIFT_FLAGS': 'nuw',
    'SHIFT': '3',
    'CHECK': '%below = icmp ult i64 %j, %count\n  br i1 %below, label %read, label %miss',
}


def module(triple=TRIPLE, **changes):
    """The fixture with CHANGES replacing its parts, for TRIPLE."""
    text = FIXTURE
    for name, default in PARTS.items():
        text = text.replace(name, changes.get(name, default))
    return HEADER.replace('TRIPLE', triple) + text


CASES = {
    'checked-read': module(),
    'unchecked-read': module(CHECK='br label %read'),
    'inverse-check': module(CHECK='%outside = icmp uge i64 %j, %count\n  br i1 %outside, label %miss, label %read'),
    'swapped-check': module(CHECK='%above = icmp ugt i64 %count, %j\n  br i1 %above, label %read, label %miss'),
    'and-check': module(CHECK='%below = icmp ult i64 %j, %count\n  %both = and i1 %below, %flag\n  br i1 %both, label %read, label %miss'),
    'or-check': module(CHECK='%outside = icmp uge i64 %j, %count\n  %either = or i1 %outside, %flag\n  br i1 %either, label %miss, label %read'),
    'wrapping-shift': module(SHIFT_FLAGS=''),
    'word-shift': module(SHIFT='2'),
    'size-optimized': module(ATTRIBUTES='optsize'),
    'sanitized': module(ATTRIBUTES='sanitize_address'),
    'linux-target': module(triple='aarch64-unknown-linux-gnu'),
    'x86-target': module(triple='x86_64-apple-macosx14.0.0'),
}

# (fills removed, sorted memset lengths, second run).
EXPECTED = {
    'checked-read': (1, ['%bytes'], 0),
    'unchecked-read': (0, ['%bytes', '128'], 0),
    'inverse-check': (1, ['%bytes'], 0),
    'swapped-check': (0, ['%bytes', '128'], 0),
    'and-check': (1, ['%bytes'], 0),
    'or-check': (1, ['%bytes'], 0),
    'wrapping-shift': (1, ['%bytes'], 0),
    'word-shift': (0, ['%bytes', '128'], 0),
    'size-optimized': (0, ['%bytes', '128'], 0),
    'sanitized': (0, ['%bytes', '128'], 0),
    'linux-target': (1, ['%bytes'], 0),
    'x86-target': (0, ['%bytes', '128'], 0),
}
