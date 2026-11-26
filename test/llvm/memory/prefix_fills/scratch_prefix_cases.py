"""IR shapes for the scratch-prefix fill removal, shared by its test.

`scratch-prefix-fills` removes the zero fill of a private byte array (256 to 8192 bytes)
when every store appends at a cursor proved below the capacity and is followed at once
by `cursor + 1`, and every load reads an index proved below the cursor and below the
capacity. The fixture appends the bytes of an input to a 256-byte buffer in a loop and
then reads one byte back; each case varies one part, and its numbers are what the C++
pass did with the same shape (see EXPECTED).
"""
TRIPLE = 'arm64-apple-darwin'
HEADER = f'''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128-Fn32"
target triple = "{TRIPLE}"
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)
declare ptr @memset(ptr, i32, i64)
declare void @llvm.trap()
declare void @clobber(ptr)
declare i64 @peek(i64) memory(read)
'''

FIXTURE = '''define i8 @f(ptr %input, i64 %count, i64 %j) ATTRIBUTES {
entry:
  %buffer = alloca [SIZE x i8]
  FILL
  br label %loop
loop:
  %cursor = phi i64 [0, %entry], [%next_cursor, %append]
  %k = phi i64 [0, %entry], [%next_k, %append]
  %done = icmp uge i64 %k, %count
  br i1 %done, label %read_check, label %room
room:
  %fits = icmp ult i64 %cursor, SIZE
  br i1 %fits, label %append, label %trap
append:
  %byte_at = getelementptr inbounds i8, ptr %input, i64 %k
  %byte = load i8, ptr %byte_at
  %slot = getelementptr inbounds [SIZE x i8], ptr %buffer, i64 0, i64 STORE_INDEX
  store i8 %byte, ptr %slot
  %next_cursor = add INCREMENT_FLAGS i64 %cursor, 1
  CALL
  %next_k = add nuw i64 %k, 1
  br label %loop
read_check:
  PREFIX_CHECK
read_bounds:
  CAPACITY_CHECK
read:
  %at = getelementptr inbounds [SIZE x i8], ptr %buffer, i64 0, i64 %j
  %value = LOAD i8, ptr %at
  ret i8 %value
miss:
  ret i8 0
trap:
  call void @llvm.trap()
  unreachable
}
'''
PARTS = {
    'ATTRIBUTES': '',
    'SIZE': '256',
    'FILL': 'call void @llvm.memset.p0.i64(ptr %buffer, i8 0, i64 256, i1 false)',
    'STORE_INDEX': '%cursor',
    'INCREMENT_FLAGS': '',
    'CALL': '',
    'PREFIX_CHECK': '%below = icmp ult i64 %j, %cursor\n  br i1 %below, label %read_bounds, label %miss',
    'CAPACITY_CHECK': '%inside = icmp ult i64 %j, 256\n  br i1 %inside, label %read, label %miss',
    'LOAD': 'load',
}


def module(**changes):
    """The fixture with CHANGES replacing its parts."""
    text = FIXTURE
    for name, default in PARTS.items():
        text = text.replace(name, changes.get(name, default))
    return HEADER + text


CASES = {
    'append-and-read': module(),
    'read-unchecked-prefix': module(PREFIX_CHECK='br label %read_bounds'),
    'read-unchecked-capacity': module(CAPACITY_CHECK='br label %read'),
    'reversed-prefix-check': module(PREFIX_CHECK='%below = icmp ugt i64 %cursor, %j\n  br i1 %below, label %read_bounds, label %miss'),
    'inverse-capacity-check': module(CAPACITY_CHECK='%outside = icmp uge i64 %j, 256\n  br i1 %outside, label %miss, label %read'),
    'flagged-increment': module(INCREMENT_FLAGS='nuw'),
    'gap-store': module(STORE_INDEX='%k'),
    'library-memset': module(FILL='%filled = call ptr @memset(ptr %buffer, i32 0, i64 256)'),
    'library-memset-kept': module(FILL='%filled = call ptr @memset(ptr %buffer, i32 0, i64 256)', PREFIX_CHECK='br label %read_bounds'),
    'partial-fill': module(FILL='call void @llvm.memset.p0.i64(ptr %buffer, i8 0, i64 128, i1 false)'),
    'clobbering-call': module(CALL='call void @clobber(ptr %input)'),
    'reading-call': module(CALL='%seen = call i64 @peek(i64 %k)'),
    'volatile-read': module(LOAD='load volatile'),
    'small-buffer': module(SIZE='128', FILL='call void @llvm.memset.p0.i64(ptr %buffer, i8 0, i64 128, i1 false)'),
    'sanitized': module(ATTRIBUTES='sanitize_address'),
    'twice-filled': module(FILL='call void @llvm.memset.p0.i64(ptr %buffer, i8 0, i64 256, i1 false)\n  call void @llvm.memset.p0.i64(ptr %buffer, i8 0, i64 256, i1 false)'),
}

# (fills removed, sorted memset lengths, second run).
EXPECTED = {
    'append-and-read': (1, [], 0),
    'read-unchecked-prefix': (0, ['256'], 0),
    'read-unchecked-capacity': (0, ['256'], 0),
    'reversed-prefix-check': (1, [], 0),
    'inverse-capacity-check': (1, [], 0),
    'flagged-increment': (0, ['256'], 0),
    'gap-store': (0, ['256'], 0),
    'library-memset': (1, [], 0),
    'library-memset-kept': (0, ['256'], 0),
    'partial-fill': (0, ['128'], 0),
    'clobbering-call': (0, ['256'], 0),
    'reading-call': (1, [], 0),
    'volatile-read': (0, ['256'], 0),
    'small-buffer': (0, ['128'], 0),
    'sanitized': (0, ['256'], 0),
    'twice-filled': (0, ['256', '256'], 0),
}
