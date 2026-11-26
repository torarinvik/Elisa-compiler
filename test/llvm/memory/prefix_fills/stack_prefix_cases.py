"""IR shapes for the stack-prefix zero removal, shared by its test.

`stack-prefix-zeros` removes the zero fill of a private array of 8 to 512 i64 elements
used as a push/pop stack, when every load reads an element pushed since the fill. The
fixture pushes the numbers below a count onto a 64-element stack and pops the top one;
each case varies one part, and its numbers are what the C++ pass did with the same shape
(see EXPECTED).
"""
TRIPLE = 'arm64-apple-macosx14.0.0'
HEADER = f'''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128-Fn32"
target triple = "{TRIPLE}"
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)
declare void @llvm.trap()
declare void @llvm.lifetime.start.p0(ptr)
'''

FIXTURE = '''define i64 @f(i64 %n, i64 %j) ATTRIBUTES {
entry:
  %stack = alloca [SIZE x i64]
  FILL
  br label %push
push:
  %sp = phi i64 [0, %entry], [%sp_next, %push_body]
  %k = phi i64 [0, %entry], [%k_next, %push_body]
  %done = icmp uge i64 %k, %n
  br i1 %done, label %pop_check, label %room
room:
  %fits = icmp ult i64 %sp, SIZE
  br i1 %fits, label %push_body, label %trap
push_body:
  %slot = getelementptr inbounds [SIZE x i64], ptr %stack, i64 0, i64 STORE_INDEX
  store STORE_KIND i64 %k, ptr %slot
  %sp_next = add i64 %sp, 1
  %k_next = add i64 %k, 1
  br label %push
pop_check:
  EMPTY_CHECK
pop:
  %top = add i64 %sp, POP_STEP
  %at = getelementptr inbounds [SIZE x i64], ptr %stack, i64 0, i64 %top
  %value = load i64, ptr %at
  ret i64 %value
miss:
  ret i64 0
trap:
  call void @llvm.trap()
  unreachable
}
'''
PARTS = {
    'ATTRIBUTES': '',
    'SIZE': '64',
    'FILL': 'call void @llvm.memset.p0.i64(ptr %stack, i8 0, i64 512, i1 false)',
    'STORE_INDEX': '%sp',
    'STORE_KIND': '',
    'EMPTY_CHECK': '%empty = icmp eq i64 %sp, 0\n  br i1 %empty, label %miss, label %pop',
    'POP_STEP': '-1',
}


def module(**changes):
    """The fixture with CHANGES replacing its parts."""
    text = FIXTURE
    for name, default in PARTS.items():
        text = text.replace(name, changes.get(name, default))
    return HEADER + text


CASES = {
    'push-then-pop': module(),
    'unchecked-pop': module(EMPTY_CHECK='br label %pop'),
    'nonzero-check': module(EMPTY_CHECK='%some = icmp ne i64 %sp, 0\n  br i1 %some, label %pop, label %miss'),
    'above-zero-check': module(EMPTY_CHECK='%some = icmp ugt i64 %sp, 0\n  br i1 %some, label %pop, label %miss'),
    'read-past-top': module(POP_STEP='0'),
    'read-below-top': module(POP_STEP='-2'),
    'store-at-counter': module(STORE_INDEX='%k'),
    'volatile-push': module(STORE_KIND='volatile'),
    'partial-fill': module(FILL='call void @llvm.memset.p0.i64(ptr %stack, i8 0, i64 256, i1 false)'),
    'nonzero-fill': module(FILL='call void @llvm.memset.p0.i64(ptr %stack, i8 1, i64 512, i1 false)'),
    'volatile-fill': module(FILL='call void @llvm.memset.p0.i64(ptr %stack, i8 0, i64 512, i1 true)'),
    'small-stack': module(SIZE='4', FILL='call void @llvm.memset.p0.i64(ptr %stack, i8 0, i64 32, i1 false)'),
    'size-optimized': module(ATTRIBUTES='optsize'),
    'sanitized': module(ATTRIBUTES='sanitize_address'),
    'lifetime-before-fill': module(FILL='call void @llvm.lifetime.start.p0(ptr %stack)\n  call void @llvm.memset.p0.i64(ptr %stack, i8 0, i64 512, i1 false)'),
    'lifetime-after-fill': module(FILL='call void @llvm.memset.p0.i64(ptr %stack, i8 0, i64 512, i1 false)\n  call void @llvm.lifetime.start.p0(ptr %stack)'),
    'linux-target': module().replace('arm64-apple-macosx14.0.0', 'aarch64-unknown-linux-gnu'),
}


# (fills removed, sorted memset lengths, second run).
EXPECTED = {
    'push-then-pop': (1, [], 0),
    'unchecked-pop': (0, ['512'], 0),
    'nonzero-check': (1, [], 0),
    'above-zero-check': (1, [], 0),
    'read-past-top': (0, ['512'], 0),
    'read-below-top': (0, ['512'], 0),
    'store-at-counter': (1, [], 0),
    'volatile-push': (0, ['512'], 0),
    'partial-fill': (1, [], 0),
    'nonzero-fill': (0, ['512'], 0),
    'volatile-fill': (0, ['512'], 0),
    'small-stack': (0, ['32'], 0),
    'size-optimized': (0, ['512'], 0),
    'sanitized': (0, ['512'], 0),
    'lifetime-before-fill': (1, [], 0),
    'lifetime-after-fill': (0, ['512'], 0),
    'linux-target': (1, [], 0),
}
