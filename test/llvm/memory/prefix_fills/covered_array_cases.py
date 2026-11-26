"""IR shapes for the covered array initializers, shared by their test.

`covered-array-initializers` removes the zero fill of a private array of 128 to 8192
doubles when a counted loop that runs to completion first writes every element a later
load reads. The fixture copies the first `n` inputs into a 128-element array in one
loop and sums them in a second; each case varies one part, and its numbers are what the
C++ pass did with the same shape (see EXPECTED).
"""
TRIPLE = 'arm64-apple-macosx14.0.0'
HEADER = '''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128-Fn32"
target triple = "TRIPLE"
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)
declare ptr @memset(ptr, i32, i64)
'''

FIXTURE = '''define double @f(i64 %n, i64 %m, ptr %source) ATTRIBUTES {
entry:
  %array = alloca [SIZE x double]
  FILL
  br label %write_head
write_head:
  %i = phi i64 [0, %entry], [%next_i, %write_body]
  %more = icmp ult i64 %i, %n
  br i1 %more, label %write_body, label %written
write_body:
  %input_at = getelementptr inbounds double, ptr %source, i64 %i
  %input = load double, ptr %input_at
  INDEX_SETUP
  %slot = getelementptr inbounds double, ptr %array, i64 WRITE_INDEX
  store STORE_KIND double %input, ptr %slot
  %next_i = add nuw i64 %i, 1
  EXIT
written:
  br label %read_head
read_head:
  %j = phi i64 [0, %written], [%next_j, %read_body]
  %sum = phi double [0.0, %written], [%next_sum, %read_body]
  %again = icmp ult i64 %j, READ_BOUND
  br i1 %again, label %read_body, label %done
read_body:
  %at = getelementptr inbounds double, ptr %array, i64 READ_INDEX
  %value = load double, ptr %at
  %next_sum = fadd double %sum, %value
  %next_j = add nuw i64 %j, 1
  br label %read_head
done:
  ret double %sum
stop:
  ret double 0.0
}
'''
PARTS = {
    'ATTRIBUTES': '',
    'SIZE': '128',
    'FILL': 'call void @llvm.memset.p0.i64(ptr %array, i8 0, i64 1024, i1 false)',
    'INDEX_SETUP': '',
    'WRITE_INDEX': '%i',
    'STORE_KIND': '',
    'EXIT': 'br label %write_head',
    'READ_BOUND': '%n',
    'READ_INDEX': '%j',
}


def module(triple=TRIPLE, **changes):
    """The fixture with CHANGES replacing its parts, for TRIPLE."""
    text = FIXTURE
    for name, default in PARTS.items():
        text = text.replace(name, changes.get(name, default))
    return HEADER.replace('TRIPLE', triple) + text


CASES = {
    'copy-then-sum': module(),
    'other-bound': module(READ_BOUND='%m'),
    'shifted-write': module(INDEX_SETUP='%shifted = add i64 %i, 1', WRITE_INDEX='%shifted'),
    'constant-read': module(READ_INDEX='0'),
    'early-exit': module(EXIT='%stop_now = fcmp olt double %input, 0.0\n  br i1 %stop_now, label %stop, label %write_head'),
    'library-memset': module(FILL='%filled = call ptr @memset(ptr %array, i32 0, i64 1024)'),
    'partial-fill': module(FILL='call void @llvm.memset.p0.i64(ptr %array, i8 0, i64 512, i1 false)'),
    'small-array': module(SIZE='64', FILL='call void @llvm.memset.p0.i64(ptr %array, i8 0, i64 512, i1 false)'),
    'volatile-store': module(STORE_KIND='volatile'),
    'size-optimized': module(ATTRIBUTES='optsize'),
    'linux-target': module(triple='aarch64-unknown-linux-gnu'),
    'x86-target': module(triple='x86_64-apple-macosx14.0.0'),
}

EXPECTED = {
    'copy-then-sum': (1, [], 0),
    'other-bound': (0, ['1024'], 0),
    'shifted-write': (0, ['1024'], 0),
    'constant-read': (0, ['1024'], 0),
    'early-exit': (0, ['1024'], 0),
    'library-memset': (1, [], 0),
    'partial-fill': (0, ['512'], 0),
    'small-array': (0, ['512'], 0),
    'volatile-store': (0, ['1024'], 0),
    'size-optimized': (0, ['1024'], 0),
    'linux-target': (1, [], 0),
    'x86-target': (0, ['1024'], 0),
}
