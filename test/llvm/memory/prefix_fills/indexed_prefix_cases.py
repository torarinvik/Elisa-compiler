"""IR shapes for the indexed-prefix fill removal, shared by its test.

`indexed-prefix-fills` removes the zero fill of a local array whose every read stays in
a prefix a loop or a copy wrote completely, or below a stack's pushes; a stack that
needs seeds the fill wrote keeps the fill, shortened to them. Each case is one shape;
its numbers are what the C++ pass did with the same shape (see EXPECTED): the count of
fills removed or shortened, the module's memset lengths, whether the array gained the
written-prefix mark, and a second run's count.
"""
TRIPLE = 'arm64-apple-darwin'
HEADER = f'''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128-Fn32"
target triple = "{TRIPLE}"
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)
declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1)
declare i64 @llvm.umin.i64(i64, i64)
declare void @llvm.trap()
declare void @use(i64)
'''

# A fill loop stores a[i] = i for i < n (n <= 64), then reads a[j] for j < n.
FILL_LOOP = '''define i64 @f(i64 %n0, i64 %j) {
entry:
  %a = alloca [64 x i64]
  call void @llvm.memset.p0.i64(ptr %a, i8 0, i64 512, i1 false)
  %n = call i64 @llvm.umin.i64(i64 %n0, i64 64)
  %empty = icmp eq i64 %n, 0
  br i1 %empty, label %done, label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %loop]
  %slot = getelementptr inbounds [64 x i64], ptr %a, i64 0, i64 %i
  store i64 %i, ptr %slot
  %next = add nuw nsw i64 %i, 1
  %more = icmp ult i64 %next, %n
  br i1 %more, label %loop, label %after
after:
  %inside = icmp ult i64 %j, %n
  br i1 %inside, label %read, label %done
read:
  %at = getelementptr inbounds [64 x i64], ptr %a, i64 0, i64 READ
  %value = load i64, ptr %at
  ret i64 %value
done:
  ret i64 0
}
'''

# A copy of n elements from an argument buffer, read below n.
COPY = '''define i32 @f(ptr %source, i64 %n0, i64 %j) {
entry:
  %a = alloca [32 x i32]
  call void @llvm.memset.p0.i64(ptr %a, i8 0, i64 128, i1 false)
  %n = call i64 @llvm.umin.i64(i64 %n0, i64 32)
  %bytes = shl nuw nsw i64 %n, 2
  call void @llvm.memcpy.p0.p0.i64(ptr %a, ptr %source, i64 %bytes, i1 false)
  %inside = icmp ult i64 %j, LIMIT
  br i1 %inside, label %read, label %done
read:
  %at = getelementptr inbounds [32 x i32], ptr %a, i64 0, i64 %j
  %value = load i32, ptr %at
  ret i32 %value
done:
  ret i32 0
}
'''

# A ring's sentinel: the store of a[n] after the loop extends the prefix to n + 1.
SENTINEL = '''define i64 @f(i64 %n0, i64 %j) {
entry:
  %a = alloca [65 x i64]
  call void @llvm.memset.p0.i64(ptr %a, i8 0, i64 520, i1 false)
  %n = call i64 @llvm.umin.i64(i64 %n0, i64 64)
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %loop]
  %slot = getelementptr inbounds [65 x i64], ptr %a, i64 0, i64 %i
  store i64 %i, ptr %slot
  %next = add nuw nsw i64 %i, 1
  %more = icmp ule i64 %next, %n
  br i1 %more, label %loop, label %after
after:
  %end = add nuw nsw i64 %n, 1
  %last = getelementptr inbounds [65 x i64], ptr %a, i64 0, i64 %end
  store i64 -1, ptr %last
  %inside = icmp ule i64 %j, %end
  br i1 %inside, label %read, label %done
read:
  %at = getelementptr inbounds [65 x i64], ptr %a, i64 0, i64 %j
  %value = load i64, ptr %at
  ret i64 %value
done:
  ret i64 0
}
'''

# A permutation array indexes a value array: order[k] < n for every stored value.
PERMUTATION = '''define i64 @f(i64 %n0, i64 %k) {
entry:
  %order = alloca [64 x i64]
  %values = alloca [64 x i64]
  call void @llvm.memset.p0.i64(ptr %order, i8 0, i64 512, i1 false)
  call void @llvm.memset.p0.i64(ptr %values, i8 0, i64 512, i1 false)
  %n = call i64 @llvm.umin.i64(i64 %n0, i64 64)
  %empty = icmp eq i64 %n, 0
  br i1 %empty, label %done, label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %loop]
  %reversed = sub nuw i64 %n, %i
  %position = add i64 %reversed, -1
  %order_slot = getelementptr inbounds [64 x i64], ptr %order, i64 0, i64 %i
  store i64 STORED, ptr %order_slot
  %value_slot = getelementptr inbounds [64 x i64], ptr %values, i64 0, i64 %i
  %square = mul i64 %i, %i
  store i64 %square, ptr %value_slot
  %next = add nuw nsw i64 %i, 1
  %more = icmp ult i64 %next, %n
  br i1 %more, label %loop, label %after
after:
  %inside = icmp ult i64 %k, %n
  br i1 %inside, label %read, label %done
read:
  %order_at = getelementptr inbounds [64 x i64], ptr %order, i64 0, i64 %k
  %index = load i64, ptr %order_at
  %value_at = getelementptr inbounds [64 x i64], ptr %values, i64 0, i64 %index
  %value = load i64, ptr %value_at
  ret i64 %value
done:
  ret i64 0
}
'''

# A stack: push x at top, pop while nonzero, reading the element below the top.
STACK = '''define i64 @f(ptr %input, i64 %count) {
entry:
  %stack = alloca [64 x i64]
  call void @llvm.memset.p0.i64(ptr %stack, i8 0, i64 512, i1 false)
  SEED
  br label %loop
loop:
  %top = phi i64 [START, %entry], [%after_push, %store], [%after_pop, %pop]
  %k = phi i64 [0, %entry], [%k_next, %store], [%k_next, %pop]
  %k_next = add nuw i64 %k, 1
  %finished = icmp uge i64 %k, %count
  br i1 %finished, label %exit, label %step
step:
  %item_at = getelementptr inbounds i64, ptr %input, i64 %k
  %item = load i64, ptr %item_at
  %is_push = icmp sgt i64 %item, 0
  br i1 %is_push, label %push, label %try_pop
push:
  %full = icmp uge i64 %top, 64
  br i1 %full, label %trap, label %store
store:
  %slot = getelementptr inbounds [64 x i64], ptr %stack, i64 0, i64 %top
  store i64 %item, ptr %slot
  %after_push = add nuw nsw i64 %top, 1
  br label %loop
try_pop:
  %empty = icmp eq i64 %top, 0
  br i1 %empty, label %exit, label %pop
pop:
  %after_pop = add nsw i64 %top, -1
  %peek = getelementptr inbounds [64 x i64], ptr %stack, i64 0, i64 %after_pop
  %value = load i64, ptr %peek
  call void @use(i64 %value)
  br label %loop
trap:
  call void @llvm.trap()
  unreachable
exit:
  ret i64 %top
}
'''

# A struct stack of {i32, i32} pairs pushed whole, popped one field at a time.
STRUCT_STACK = '''%pair = type { i32, i32 }
define i32 @f(ptr %input, i64 %count) {
entry:
  %stack = alloca [32 x %pair]
  call void @llvm.memset.p0.i64(ptr %stack, i8 0, i64 256, i1 false)
  br label %loop
loop:
  %top = phi i64 [0, %entry], [%after_push, %push], [%after_pop, %pop]
  %k = phi i64 [0, %entry], [%k_next, %push], [%k_next, %pop]
  %sum = phi i32 [0, %entry], [%sum, %push], [%total, %pop]
  %k_next = add nuw i64 %k, 1
  %finished = icmp uge i64 %k, %count
  br i1 %finished, label %exit, label %step
step:
  %item_at = getelementptr inbounds i32, ptr %input, i64 %k
  %item = load i32, ptr %item_at
  %is_push = icmp sgt i32 %item, 0
  br i1 %is_push, label %push_check, label %try_pop
push_check:
  %full = icmp uge i64 %top, 32
  br i1 %full, label %trap, label %push
push:
  %first = getelementptr inbounds [32 x %pair], ptr %stack, i64 0, i64 %top
  store i32 %item, ptr %first
  %second = getelementptr inbounds i8, ptr %first, i64 4
  store i32 SECOND, ptr %second
  %after_push = add nuw nsw i64 %top, 1
  br label %loop
try_pop:
  %empty = icmp eq i64 %top, 0
  br i1 %empty, label %exit, label %pop
pop:
  %after_pop = add nsw i64 %top, -1
  %element = getelementptr inbounds [32 x %pair], ptr %stack, i64 0, i64 %after_pop
  %field = getelementptr inbounds i8, ptr %element, i64 4
  %value = load i32, ptr %field
  %total = add i32 %sum, %value
  br label %loop
trap:
  call void @llvm.trap()
  unreachable
exit:
  ret i32 %sum
}
'''

# Records of three i64 fields in a flat array: records[3 * i + f] for f < 3.
RECORDS = '''define i64 @f(ptr %input, i64 %count) {
entry:
  %records = alloca [96 x i64]
  call void @llvm.memset.p0.i64(ptr %records, i8 0, i64 768, i1 false)
  br label %loop
loop:
  %top = phi i64 [0, %entry], [%after_push, %push], [%after_pop, %pop]
  %k = phi i64 [0, %entry], [%k_next, %push], [%k_next, %pop]
  %k_next = add nuw i64 %k, 1
  %finished = icmp uge i64 %k, %count
  br i1 %finished, label %exit, label %step
step:
  %item_at = getelementptr inbounds i64, ptr %input, i64 %k
  %item = load i64, ptr %item_at
  %is_push = icmp sgt i64 %item, 0
  br i1 %is_push, label %push_check, label %try_pop
push_check:
  %full = icmp uge i64 %top, 32
  br i1 %full, label %trap, label %push
push:
  %base = mul nuw nsw i64 %top, 24
  %field0 = getelementptr inbounds i8, ptr %records, i64 %base
  store i64 %item, ptr %field0
  %field1 = getelementptr inbounds i8, ptr %field0, i64 8
  store i64 %k, ptr %field1
  %field2 = getelementptr inbounds i8, ptr %field0, i64 16
  STORE2
  %after_push = add nuw nsw i64 %top, 1
  br label %loop
try_pop:
  %empty = icmp eq i64 %top, 0
  br i1 %empty, label %exit, label %pop
pop:
  %after_pop = add nsw i64 %top, -1
  %popped_base = mul nuw nsw i64 %after_pop, 24
  %record = getelementptr inbounds i8, ptr %records, i64 %popped_base
  %read_at = getelementptr inbounds i8, ptr %record, i64 8
  %value = load i64, ptr %read_at
  call void @use(i64 %value)
  br label %loop
trap:
  call void @llvm.trap()
  unreachable
exit:
  ret i64 %top
}
'''

# A fill repeated per query: each query's loop writes [0, n) and reads below n.
REPEATED = '''define i64 @f(i64 %queries, i64 %n0, i64 %j) {
entry:
  %n = call i64 @llvm.umin.i64(i64 %n0, i64 64)
  %a = alloca [64 x i64]
  br label %query
query:
  %q = phi i64 [0, %entry], [%q_next, %read]
  %acc = phi i64 [0, %entry], [%sum, %read]
  call void @llvm.memset.p0.i64(ptr %a, i8 0, i64 512, i1 false)
  br label %loop
loop:
  %i = phi i64 [0, %query], [%next, %loop]
  %slot = getelementptr inbounds [64 x i64], ptr %a, i64 0, i64 %i
  store i64 %q, ptr %slot
  %next = add nuw nsw i64 %i, 1
  %more = icmp ule i64 %next, %n
  br i1 %more, label %loop, label %read
read:
  %index = call i64 @llvm.umin.i64(i64 %j, i64 %n)
  %at = getelementptr inbounds [64 x i64], ptr %a, i64 0, i64 %index
  %value = load i64, ptr %at
  %sum = add i64 %acc, %value
  %q_next = add nuw i64 %q, 1
  %again = icmp ult i64 %q_next, %queries
  br i1 %again, label %query, label %done
done:
  ret i64 %sum
}
'''

# A view of the written prefix passed to a helper that reads below the view's length.
VIEW = '''define internal i64 @helper({ ptr, i64 } %view) {
entry:
  %data = extractvalue { ptr, i64 } %view, 0
  %length = extractvalue { ptr, i64 } %view, 1
  %empty = icmp eq i64 %length, 0
  br i1 %empty, label %done, label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %loop]
  %sum = phi i64 [0, %entry], [%total, %loop]
  %slot = getelementptr i64, ptr %data, i64 %i
  %value = load i64, ptr %slot
  %total = add i64 %sum, %value
  %next = add nuw i64 %i, 1
  %more = icmp ult i64 %next, LENGTH
  br i1 %more, label %loop, label %done
done:
  %result = phi i64 [0, %entry], [%total, %loop]
  ret i64 %result
}
define i64 @f(i64 %n0) {
entry:
  %a = alloca [64 x i64]
  call void @llvm.memset.p0.i64(ptr %a, i8 0, i64 512, i1 false)
  %n = call i64 @llvm.umin.i64(i64 %n0, i64 64)
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %loop]
  %slot = getelementptr inbounds [64 x i64], ptr %a, i64 0, i64 %i
  store i64 %i, ptr %slot
  %next = add nuw nsw i64 %i, 1
  %more = icmp ult i64 %next, %n
  br i1 %more, label %loop, label %after
after:
  %data = insertvalue { ptr, i64 } undef, ptr %a, 0
  %view = insertvalue { ptr, i64 } %data, i64 %next, 1
  %result = call i64 @helper({ ptr, i64 } %view)
  ret i64 %result
}
'''

# A parent array of -1 or an index below n, followed from a node while it is not -1.
SENTINEL_PARENTS = '''define i64 @f(ptr %links, i64 %n0, i64 %start) {
entry:
  %parent = alloca [64 x i64]
  call void @llvm.memset.p0.i64(ptr %parent, i8 0, i64 512, i1 false)
  %n = call i64 @llvm.umin.i64(i64 %n0, i64 64)
  %empty = icmp eq i64 %n, 0
  br i1 %empty, label %done, label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %latch]
  %link_at = getelementptr inbounds i64, ptr %links, i64 %i
  %link = load i64, ptr %link_at
  %valid = icmp ult i64 %link, %n
  %slot = getelementptr inbounds [64 x i64], ptr %parent, i64 0, i64 %i
  br i1 %valid, label %good, label %bad
good:
  store i64 %link, ptr %slot
  br label %latch
bad:
  store i64 -1, ptr %slot
  br label %latch
latch:
  %next = add nuw nsw i64 %i, 1
  %more = icmp ult i64 %next, %n
  br i1 %more, label %loop, label %walk_entry
walk_entry:
  %first = icmp ult i64 %start, %n
  br i1 %first, label %walk, label %done
walk:
  %node = phi i64 [%start, %walk_entry], [%up, %walk_next]
  %depth = phi i64 [0, %walk_entry], [%deeper, %walk_next]
  %node_at = getelementptr inbounds [64 x i64], ptr %parent, i64 0, i64 %node
  %up = load i64, ptr %node_at
  %root = icmp eq i64 %up, -1
  br i1 %root, label %done, label %walk_next
walk_next:
  %deeper = add nuw i64 %depth, 1
  br label %walk
done:
  %result = phi i64 [0, %entry], [0, %walk_entry], [%depth, %walk]
  ret i64 %result
}
'''

# A vector load of four lanes in a loop of whole groups below n.
VECTOR = '''define <4 x i32> @f(i64 %n0) {
entry:
  %a = alloca [64 x i32]
  call void @llvm.memset.p0.i64(ptr %a, i8 0, i64 256, i1 false)
  %n = call i64 @llvm.umin.i64(i64 %n0, i64 64)
  %groups = lshr i64 %n, 2
  %whole = shl nuw nsw i64 %groups, 2
  %none = icmp eq i64 %whole, 0
  br i1 %none, label %done, label %fill
fill:
  %i = phi i64 [0, %entry], [%next, %fill]
  %slot = getelementptr inbounds [64 x i32], ptr %a, i64 0, i64 %i
  %narrow = trunc i64 %i to i32
  store i32 %narrow, ptr %slot
  %next = add nuw nsw i64 %i, 1
  %more = icmp ult i64 %next, %whole
  br i1 %more, label %fill, label %sum
sum:
  %v = phi i64 [0, %fill], [%v_next, %sum]
  %acc = phi <4 x i32> [zeroinitializer, %fill], [%total, %sum]
  %lane = getelementptr inbounds [64 x i32], ptr %a, i64 0, i64 %v
  %lanes = load <4 x i32>, ptr %lane
  %total = add <4 x i32> %acc, %lanes
  %v_next = add nuw nsw i64 %v, 4
  %again = icmp ult i64 %v_next, LIMIT
  br i1 %again, label %sum, label %done
done:
  %result = phi <4 x i32> [zeroinitializer, %entry], [%total, %sum]
  ret <4 x i32> %result
}
'''


def module(body, **parts):
    """BODY with each named part replaced, after the shared header."""
    for name, text in parts.items():
        body = body.replace(name, text)
    return HEADER + body


CASES = {
    'fill-loop-read-below': module(FILL_LOOP, READ='%j'),
    'fill-loop-read-past': module(FILL_LOOP, READ='%n', **{'%inside = icmp ult i64 %j, %n': '%inside = icmp ult i64 %j, 64'}),
    'copy-read-below': module(COPY, LIMIT='%n'),
    'copy-read-past': module(COPY, LIMIT='32'),
    'sentinel-extends': module(SENTINEL),
    'sentinel-missing': module(SENTINEL, **{'store i64 -1, ptr %last': 'call void @use(i64 0)'}),
    'permutation-below': module(PERMUTATION, STORED='%position'),
    'permutation-unbounded': module(PERMUTATION, STORED='%k'),
    'stack-plain': module(STACK, SEED='', START='0'),
    'stack-seeded': module(STACK, SEED='%seed = getelementptr inbounds [64 x i64], ptr %stack, i64 0, i64 0\n  store i64 7, ptr %seed', START='1'),
    'stack-folded-seed': module(STACK, SEED='', START='1'),
    'stack-unseeded-start': module(STACK, SEED='', START='3'),
    'stack-copied-out': module(STACK, SEED='', START='0', **{'exit:\n  ret i64 %top': 'exit:\n  %bytes = shl nuw nsw i64 %top, 3\n  call void @llvm.memcpy.p0.p0.i64(ptr %input, ptr %stack, i64 %bytes, i1 false)\n  ret i64 %top'}),
    'stack-copied-past': module(STACK, SEED='', START='0', **{'exit:\n  ret i64 %top': 'exit:\n  %one_more = add nuw nsw i64 %top, 1\n  %bytes = shl nuw nsw i64 %one_more, 3\n  call void @llvm.memcpy.p0.p0.i64(ptr %input, ptr %stack, i64 %bytes, i1 false)\n  ret i64 %top'}),
    'struct-stack-whole': module(STRUCT_STACK, SECOND='%item'),
    'struct-stack-half': module(STRUCT_STACK, SECOND='%item', **{'  %second = getelementptr inbounds i8, ptr %first, i64 4\n  store i32 %item, ptr %second\n': ''}),
    'records-whole': module(RECORDS, STORE2='store i64 0, ptr %field2'),
    'records-partial': module(RECORDS, STORE2='call void @use(i64 0)'),
    'repeated-fill': module(REPEATED),
    'view-below': module(VIEW, LENGTH='%length'),
    'view-past': module(VIEW, LENGTH='64'),
    'sentinel-parents': module(SENTINEL_PARENTS),
    'vector-below': module(VECTOR, LIMIT='%whole'),
    'vector-past': module(VECTOR, LIMIT='61'),
}

# (fills removed or shortened, sorted memset lengths, written-prefix mark, second run).
EXPECTED = {
    'fill-loop-read-below': (1, [], True, 0),
    'fill-loop-read-past': (0, ['512'], False, 0),
    'copy-read-below': (1, [], True, 0),
    'copy-read-past': (0, ['128'], False, 0),
    'sentinel-extends': (1, [], True, 0),
    'sentinel-missing': (0, ['520'], False, 0),
    'permutation-below': (2, [], True, 0),
    'permutation-unbounded': (1, ['512'], True, 0),
    'stack-plain': (1, [], True, 0),
    'stack-seeded': (1, [], True, 0),
    'stack-folded-seed': (1, ['8'], False, 1),
    'stack-unseeded-start': (1, ['24'], False, 1),
    'stack-copied-out': (1, [], True, 0),
    'stack-copied-past': (0, ['512'], False, 0),
    'struct-stack-whole': (1, [], True, 0),
    'struct-stack-half': (0, ['256'], False, 0),
    'records-whole': (1, [], True, 0),
    'records-partial': (0, ['768'], False, 0),
    'repeated-fill': (0, ['512'], False, 0),
    'view-below': (1, [], True, 0),
    'view-past': (0, ['512'], False, 0),
    'sentinel-parents': (0, ['512'], False, 0),
    'vector-below': (0, ['256'], False, 0),
    'vector-past': (0, ['256'], False, 0),
}
