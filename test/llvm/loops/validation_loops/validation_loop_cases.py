"""IR shapes for the validation-loop passes, shared by their test.

Five passes rewrite the loops of input validation and scanning code:
`private-bit-updates` makes a conditional OR into a private bit array unconditional,
`private-initializations` sinks a large zero fill off a return-only edge,
`small-recursion` inlines a small `void` function's one self-call, `validation-peel`
peels and unrolls a two-block validation scan, and `nested-scans` unrolls a short inner
scan with conditional stores (Linux only). Each fixture is one pass's shape; each case
varies one, and its count is what the C++ pass did with the same shape (see EXPECTED).
"""
MAC = 'arm64-apple-darwin27.2.0'
LINUX = 'aarch64-unknown-linux-gnu'
HEADER = f'target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"\ntarget triple = "{MAC}"\n\n'
MEMSET = 'declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)\n'


def varied(text, *replacements):
    """TEXT with each (old, new) replacement made once."""
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new, 1)
    return text


def on(text, triple):
    return text.replace(MAC, triple)


BIT_LOOP = HEADER + '''define i32 @bits(ptr %input, i64 %n) {
entry:
  %a = alloca [8 x i32], align 4
  call void @llvm.memset.p0.i64(ptr align 4 %a, i8 0, i64 32, i1 false)
  %empty = icmp eq i64 %n, 0
  br i1 %empty, label %exit, label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %zero]
  %p = getelementptr i8, ptr %input, i64 %i
  %c = load i8, ptr %p
  %slot = and i64 %i, 7
  %bit = trunc i64 %i to i32
  %shift = and i32 %bit, 31
  %mask = shl i32 1, %shift
  DECISION
one:
  %q = getelementptr i32, ptr %a, i64 %slot
  %old = load i32, ptr %q, align 4
  %new = or i32 %old, %mask
  store i32 %new, ptr %q, align 4
  br label %zero
zero:
  %next = add i64 %i, 1
  %done = icmp eq i64 %next, %n
  br i1 %done, label %exit, label %loop
exit:
  %h = phi i32 [0, %entry], [1, %zero]
  %r0 = load i32, ptr %a, align 4
  %p3 = getelementptr i32, ptr %a, i64 3
  %r3 = load i32, ptr %p3, align 4
  %p7 = getelementptr i32, ptr %a, i64 7
  %r7 = load i32, ptr %p7, align 4
  %x = xor i32 %r0, %r3
  %y = mul i32 %r7, 31
  %z = add i32 %x, %y
  %r = add i32 %z, %h
  ret i32 %r
}
''' + MEMSET
CONDITIONAL = '%set = icmp eq i8 %c, 49\n  br i1 %set, label %one, label %zero'
SWITCHED = '%d = sub i8 %c, 48\n  switch i8 %d, label %invalid [ i8 0, label %zero\n                                 i8 1, label %one ]\ninvalid:\n  ret i32 -1'
BITS = BIT_LOOP.replace('DECISION', CONDITIONAL)
BITS_SWITCH = BIT_LOOP.replace('DECISION', SWITCHED)
LIFETIME = 'declare void @llvm.lifetime.start.p0(ptr)\ndeclare void @llvm.lifetime.end.p0(ptr)\n'
SECOND_BITS = BITS[BITS.index('define'):BITS.index('declare')].replace('@bits(', '@bits2(')

BIT_CASES = {
    'bits': BITS,
    'bits-switch': BITS_SWITCH,
    'bits-linux': on(BITS, LINUX),
    'bits-x86': on(BITS, 'x86_64-apple-macosx15.0.0'),
    'bits-mask-first': varied(BITS, ('or i32 %old, %mask', 'or i32 %mask, %old')),
    'bits-unbounded-index': varied(BITS, ('%slot = and i64 %i, 7', '%slot = and i64 %i, 8')),
    'bits-index-in-range-edge': varied(BITS, ('%slot = and i64 %i, 7', '%slot = and i64 %i, 6')),
    'bits-byte-elements': varied(BITS, ('getelementptr i32, ptr %a, i64 %slot', 'getelementptr i8, ptr %a, i64 %slot'), ('%slot = and i64 %i, 7', '%slot = and i64 %i, 28')),
    'bits-byte-elements-overrun': varied(BITS, ('getelementptr i32, ptr %a, i64 %slot', 'getelementptr i8, ptr %a, i64 %slot'), ('%slot = and i64 %i, 7', '%slot = and i64 %i, 29')),
    'bits-captured': varied(BITS, ('  %empty = icmp', '  call void @keep(ptr %a)\n  %empty = icmp')) + 'declare void @keep(ptr)\n',
    'bits-volatile-load': varied(BITS, ('load i32, ptr %q, align 4', 'load volatile i32, ptr %q, align 4')),
    'bits-atomic-store': varied(BITS, ('store i32 %new, ptr %q, align 4', 'store atomic i32 %new, ptr %q monotonic, align 4')),
    'bits-extra-instruction': varied(BITS, ('  br label %zero\nzero:', '  %unused = add i32 %new, 1\n  br label %zero\nzero:')),
    'bits-mask-in-one': varied(BITS, ('  %old = load', '  %m2 = add i32 %mask, 0\n  %old = load'), ('or i32 %old, %mask', 'or i32 %old, %m2')),
    'bits-xor-update': varied(BITS, ('or i32 %old, %mask', 'xor i32 %old, %mask')),
    'bits-i128': varied(BITS, ('[8 x i32], align 4', '[2 x i128], align 16'), ('ptr align 4 %a', 'ptr align 16 %a'), ('getelementptr i32, ptr %a, i64 %slot', 'getelementptr i128, ptr %a, i64 %slot'), ('load i32, ptr %q, align 4', 'load i128, ptr %q, align 16'), ('or i32 %old, %mask', 'or i128 %old, %wide'), ('store i32 %new, ptr %q, align 4', 'store i128 %new, ptr %q, align 16'), ('%slot = and i64 %i, 7', '%slot = and i64 %i, 1'), ('%mask = shl i32 1, %shift', '%mask = shl i32 1, %shift\n  %wide = zext i32 %mask to i128')),
    'bits-big-array': varied(BITS, ('[8 x i32], align 4', '[80 x i32], align 4')),
    'bits-under-aligned-array': varied(BITS, ('[8 x i32], align 4', '[8 x i32], align 2')),
    'bits-pointer-argument': varied(BITS, ('getelementptr i32, ptr %a, i64 %slot', 'getelementptr i32, ptr %input, i64 %slot')),
    'bits-zero-has-phi': varied(BITS, ('zero:\n  %next', 'zero:\n  %seen = phi i32 [1, %one], [0, %loop]\n  %next')),
    'bits-lifetime-start': varied(BITS, ('  call void @llvm.memset', '  call void @llvm.lifetime.start.p0(ptr %a)\n  call void @llvm.memset')) + LIFETIME,
    'bits-lifetime-end-after': varied(BITS, ('  ret i32 %r', '  call void @llvm.lifetime.end.p0(ptr %a)\n  ret i32 %r')) + LIFETIME,
    'bits-lifetime-start-in-loop': varied(BITS, ('  %p = getelementptr i8', '  call void @llvm.lifetime.start.p0(ptr %a)\n  %p = getelementptr i8')) + LIFETIME,
    'bits-lifetime-end-in-loop': varied(BITS, ('  %next = add i64 %i, 1', '  call void @llvm.lifetime.end.p0(ptr %a)\n  %next = add i64 %i, 1')) + LIFETIME,
    'bits-metadata': varied(BITS, ('load i32, ptr %q, align 4', 'load i32, ptr %q, align 4, !range !0, !noundef !1'), ('store i32 %new, ptr %q, align 4', 'store i32 %new, ptr %q, align 4, !nontemporal !2')) + '!0 = !{i32 0, i32 1000}\n!1 = !{}\n!2 = !{i32 1}\n',
    'bits-optsize': varied(BITS, ('@bits(ptr %input, i64 %n) {', '@bits(ptr %input, i64 %n) optsize {')),
    'bits-two-functions': BITS + SECOND_BITS,
    'bits-switch-case-two': varied(BITS_SWITCH, ('i8 1, label %one', 'i8 2, label %one')),
    'bits-switch-default-zero': varied(BITS_SWITCH, ('label %invalid [', 'label %zero [')),
    'bits-switch-i64': varied(BITS_SWITCH, ('%d = sub i8 %c, 48\n  switch i8 %d', '%d8 = sub i8 %c, 48\n  %d = zext i8 %d8 to i64\n  switch i64 %d'), ('[ i8 0, label %zero', '[ i64 0, label %zero'), ('i8 1, label %one', 'i64 1, label %one')),
    'bits-one-shared': varied(BITS, ('br i1 %done, label %exit, label %loop', 'br i1 %done, label %exit, label %again\nagain:\n  br i1 %done, label %one, label %loop'), ('[%next, %zero]', '[%next, %again]')),
}

INIT = HEADER + '''define i32 @init(i64 %n, ptr %source) {
entry:
  %a = alloca [512 x i8], align 16
  call void @llvm.memset.p0.i64(ptr align 16 %a, i8 0, i64 512, i1 false)
  %empty = icmp eq i64 %n, 0
  br i1 %empty, label %none, label %work
none:
  ret i32 0
work:
  %index = and i64 %n, 511
  %at = getelementptr i8, ptr %a, i64 %index
  %v = load i8, ptr %source
  store i8 %v, ptr %at
  %first = load i8, ptr %a
  %back = getelementptr i8, ptr %a, i64 37
  %other = load i8, ptr %back
  %sum = add i8 %first, %other
  %r = zext i8 %sum to i32
  ret i32 %r
}
''' + MEMSET
SECOND_INIT = INIT[INIT.index('define'):INIT.index('declare')].replace('@init(', '@init2(')

INIT_CASES = {
    'init': INIT,
    'init-linux': on(INIT, LINUX),
    'init-x86': on(INIT, 'x86_64-unknown-linux-gnu'),
    'init-swapped': varied(INIT, ('label %none, label %work', 'label %work, label %none'), ('icmp eq i64 %n, 0', 'icmp ne i64 %n, 0')),
    'init-small': varied(INIT, ('i64 512, i1 false', 'i64 255, i1 false')),
    'init-smallest': varied(INIT, ('i64 512, i1 false', 'i64 256, i1 false')),
    'init-nonzero': varied(INIT, ('i8 0, i64 512', 'i8 1, i64 512')),
    'init-volatile': varied(INIT, ('i64 512, i1 false', 'i64 512, i1 true')),
    'init-overrun': varied(INIT, ('[512 x i8]', '[300 x i8]')),
    'init-offset': varied(INIT, ('call void @llvm.memset.p0.i64(ptr align 16 %a, i8 0, i64 512', '%tail = getelementptr i8, ptr %a, i64 256\n  call void @llvm.memset.p0.i64(ptr align 16 %tail, i8 0, i64 256')),
    'init-offset-overrun': varied(INIT, ('call void @llvm.memset.p0.i64(ptr align 16 %a, i8 0, i64 512', '%tail = getelementptr i8, ptr %a, i64 257\n  call void @llvm.memset.p0.i64(ptr align 16 %tail, i8 0, i64 256')),
    'init-captured': varied(INIT, ('  %r = zext', '  call void @keep(ptr %a)\n  %r = zext')) + 'declare void @keep(ptr)\n',
    'init-store-between': varied(INIT, ('  %empty = icmp', '  store i8 1, ptr %source\n  %empty = icmp')),
    'init-arithmetic-between': varied(INIT, ('  %empty = icmp eq i64 %n, 0', '  %m = mul i64 %n, 3\n  %empty = icmp eq i64 %m, 0')),
    'init-both-return': varied(INIT, ('  %index = and', '  ret i32 1\nunused:\n  %index = and')),
    'init-return-reads': varied(INIT, ('none:\n  ret i32 0', 'none:\n  %peek = load i8, ptr %a\n  %pr = zext i8 %peek to i32\n  ret i32 %pr')),
    'init-return-lifetime': varied(INIT, ('none:\n  ret i32 0', 'none:\n  call void @llvm.lifetime.end.p0(ptr %a)\n  ret i32 0')) + LIFETIME,
    'init-work-phi': varied(INIT, ('work:\n  %index', 'work:\n  %w = phi i8 [7, %entry]\n  %index'), ('  %r = zext i8 %sum to i32', '  %s2 = add i8 %sum, %w\n  %r = zext i8 %s2 to i32')),
    'init-metadata': varied(INIT, ('i64 512, i1 false)', 'i64 512, i1 false), !tbaa !0')) + '!0 = !{!1, !1, i64 0}\n!1 = !{!"omnipotent char", !2}\n!2 = !{!"root"}\n',
    'init-sanitized': varied(INIT, ('@init(i64 %n, ptr %source) {', '@init(i64 %n, ptr %source) sanitize_address {')),
    'init-dynamic-alloca': varied(INIT, ('%a = alloca [512 x i8], align 16', '%a = alloca [512 x i8], i64 1, align 16')),
    'init-two-fills': varied(INIT, ('  %empty = icmp', '  %b = alloca [256 x i8], align 16\n  %empty = icmp'), ('  %empty = icmp', '  call void @llvm.memset.p0.i64(ptr align 16 %b, i8 0, i64 256, i1 false)\n  %empty = icmp'), ('  %r = zext', '  %bv = load i8, ptr %b\n  %r = zext')),
    'init-two-functions': INIT + SECOND_INIT,
}

RECURSION = HEADER + '''define internal void @walk(ptr %p, i64 %n) {
entry:
  %done = icmp eq i64 %n, 0
  br i1 %done, label %exit, label %body
body:
  %v = load i64, ptr %p, align 8
  %w = add i64 %v, %n
  store i64 %w, ptr %p, align 8
  %q = getelementptr i64, ptr %p, i64 1
  %m = sub i64 %n, 1
  call void @walk(ptr %q, i64 %m)
  br label %exit
exit:
  ret void
}

define void @outer(ptr %p, i64 %n) {
entry:
  call void @walk(ptr %p, i64 %n)
  ret void
}
'''
TRAP = 'declare void @llvm.trap()\n'

RECURSION_CASES = {
    'recursion': RECURSION,
    'recursion-linux': on(RECURSION, LINUX),
    'recursion-x86': on(RECURSION, 'x86_64-unknown-linux-gnu'),
    'recursion-external': varied(RECURSION, ('define internal void @walk', 'define void @walk')),
    'recursion-private': varied(RECURSION, ('define internal void @walk', 'define private void @walk')),
    'recursion-noinline': varied(RECURSION, ('i64 %n) {\nentry:\n  %done', 'i64 %n) noinline {\nentry:\n  %done')),
    'recursion-noinline-call': varied(RECURSION, ('call void @walk(ptr %q, i64 %m)', 'call void @walk(ptr %q, i64 %m) noinline')),
    'recursion-two-self-calls': varied(RECURSION, ('  br label %exit\nexit:', '  call void @walk(ptr %q, i64 %m)\n  br label %exit\nexit:')),
    'recursion-no-store': varied(RECURSION, ('  store i64 %w, ptr %p, align 8\n', '')),
    'recursion-no-load': varied(RECURSION, ('%v = load i64, ptr %p, align 8', '%v = add i64 %n, 3')),
    'recursion-alloca': varied(RECURSION, ('  %done = icmp', '  %slot = alloca i64\n  %done = icmp')),
    'recursion-address-taken': RECURSION + '@table = global ptr @walk\n',
    'recursion-only-self': varied(RECURSION, ('  call void @walk(ptr %p, i64 %n)\n  ret void', '  ret void')),
    'recursion-marked': varied(RECURSION, ('i64 %n) {\nentry:\n  %done', 'i64 %n) "elisa.recursion.expanded" {\nentry:\n  %done')),
    'recursion-other-call': varied(RECURSION, ('  br label %exit\nexit:', '  call void @log(i64 %w)\n  br label %exit\nexit:')) + 'declare void @log(i64)\n',
    'recursion-trap': varied(RECURSION, ('  %v = load', '  %bad = icmp ugt i64 %n, 1000\n  br i1 %bad, label %fail, label %go\nfail:\n  call void @llvm.trap()\n  unreachable\ngo:\n  %v = load')) + TRAP,
    'recursion-returns-value': varied(RECURSION, ('define internal void @walk', 'define internal i64 @walk'), ('call void @walk(ptr %q', 'call i64 @walk(ptr %q'), ('exit:\n  ret void\n}', 'exit:\n  ret i64 0\n}'), ('call void @walk(ptr %p, i64 %n)', 'call i64 @walk(ptr %p, i64 %n)')),
    'recursion-optsize': varied(RECURSION, ('i64 %n) {\nentry:\n  %done', 'i64 %n) optsize {\nentry:\n  %done')),
    'recursion-volatile': varied(RECURSION, ('load i64, ptr %p, align 8', 'load volatile i64, ptr %p, align 8')),
    'recursion-mismatched-call': varied(RECURSION, ('call void @walk(ptr %q, i64 %m)', 'call void @walk(ptr %q, i64 %m, i64 0)')),
    'recursion-long': varied(RECURSION, ('  %q = getelementptr', ''.join(f'  %pad{index} = add i64 %w, {index}\n' for index in range(75)) + '  %q = getelementptr')),
}

VALIDATION = HEADER + '''define i1 @valid(ptr %s, i64 %n) {
entry:
  %limit = BOUND
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %check]
  %end = icmp eq i64 %i, %limit
  br i1 %end, label %ok, label %check
check:
  %p = getelementptr inbounds i8, ptr %s, i64 %i
  %c = load i8, ptr %p
  %bad = icmp slt i8 %c, 0
  %next = add nuw i64 %i, 1
  br i1 %bad, label %fail, label %loop
ok:
  AFTER
fail:
  ret i1 false
}
'''
SEARCH = '''br label %outer
outer:
  %k = phi i64 [0, %ok], [%kn, %outer_latch]
  br label %inner
inner:
  %j = phi i64 [%k, %outer], [%jn, %inner_body]
  %pj = getelementptr i8, ptr %s, i64 %j
  %x = load i8, ptr %pj
  %jn = add i64 %j, 1
  br label %inner_body
inner_body:
  %pk = getelementptr i8, ptr %s, i64 %jn
  %y = load i8, ptr %pk
  %same = icmp eq i8 %x, %y
  br i1 %same, label %inner, label %outer_latch
outer_latch:
  %kn = add i64 %k, 1
  %kdone = icmp eq i64 %kn, %limit
  br i1 %kdone, label %found, label %outer
found:
  ret i1 true'''


def validation(bound='and i64 %n, -1', after='ret i1 true'):
    return VALIDATION.replace('BOUND', bound).replace('AFTER', after)


SCAN = validation()
BOUNDED = validation('and i64 %n, 1023')
TINY = validation('and i64 %n, 7')
SEARCHING = validation('and i64 %n, 1023', SEARCH).replace('@valid(ptr %s, i64 %n) {', '@valid(ptr %s, i64 %n) memory(read) {')

PEEL_CASES = {
    'peel': SCAN,
    'peel-linux': on(SCAN, LINUX),
    'peel-x86': on(SCAN, 'x86_64-unknown-linux-gnu'),
    'peel-bounded': BOUNDED,
    'peel-bounded-linux': on(BOUNDED, LINUX),
    'peel-bounded-x86': on(BOUNDED, 'x86_64-unknown-linux-gnu'),
    'peel-bounded-small': validation('and i64 %n, 31'),
    'peel-bounded-large': validation('and i64 %n, 8191'),
    'peel-tiny': TINY,
    'peel-tiny-one': validation('and i64 %n, 0'),
    'peel-tiny-x86': on(TINY, 'x86_64-unknown-linux-gnu'),
    'peel-search': SEARCHING,
    'peel-search-writes': SEARCHING.replace(' memory(read) {', ' {'),
    'peel-search-unbounded': validation('and i64 %n, -1', SEARCH).replace('@valid(ptr %s, i64 %n) {', '@valid(ptr %s, i64 %n) memory(read) {'),
    'peel-search-x86': on(SEARCHING, 'x86_64-unknown-linux-gnu'),
    'peel-store': varied(SCAN, ('  %next = add nuw', '  store i8 0, ptr %p\n  %next = add nuw')),
    'peel-two-loads': varied(SCAN, ('  %bad = icmp slt i8 %c, 0', '  %c2 = load i8, ptr %s\n  %c3 = add i8 %c, %c2\n  %bad = icmp slt i8 %c3, 0')),
    'peel-volatile': varied(SCAN, ('load i8, ptr %p', 'load volatile i8, ptr %p')),
    'peel-third-compare': varied(SCAN, ('  %next = add nuw', '  %odd = icmp eq i8 %c, 7\n  %next = add nuw')),
    'peel-loop-id': varied(SCAN, ('br i1 %bad, label %fail, label %loop', 'br i1 %bad, label %fail, label %loop, !llvm.loop !0')) + '!0 = distinct !{!0}\n',
    'peel-optsize': varied(SCAN, ('@valid(ptr %s, i64 %n) {', '@valid(ptr %s, i64 %n) optsize {')),
    'peel-long': varied(SCAN, ('  %next = add nuw', ''.join(f'  %pad{index} = add i64 %i, {index}\n' for index in range(9)) + '  %next = add nuw')),
    'peel-sixteen': varied(SCAN, ('  %next = add nuw', ''.join(f'  %pad{index} = add i64 %i, {index}\n' for index in range(8)) + '  %next = add nuw')),
    'peel-two-loops': SCAN + SCAN[SCAN.index('define'):].replace('@valid(', '@valid2('),
}

NESTED = on(HEADER, LINUX) + '''define void @scan(ptr %a, ptr %b, i64 %n, i64 %m) {
entry:
  %none = icmp eq i64 %m, 0
  br i1 %none, label %exit, label %outer
outer:
  %o = phi i64 [0, %entry], [%onext, %outer_latch]
  br label %inner
inner:
  %j = phi i64 [0, %outer], [%jn, %inner_latch]
  %pa = getelementptr i64, ptr %a, i64 %j
  %va = load i64, ptr %pa, align 8
  %negative = icmp slt i64 %va, 0
  br i1 %negative, label %outer_latch, label %second
second:
  %pb = getelementptr i64, ptr %b, i64 %j
  %vb = load i64, ptr %pb, align 8
  %greater = icmp sgt i64 %va, %vb
  br i1 %greater, label %third, label %inner_latch
third:
  %small = icmp ult i64 %vb, 1000
  br i1 %small, label %write, label %inner_latch
write:
  STORED
  br label %inner_latch
inner_latch:
  %jn = add i64 %j, 1
  %end = icmp eq i64 %jn, %m
  br i1 %end, label %outer_latch, label %inner
outer_latch:
  %onext = add i64 %o, 1
  %odone = icmp eq i64 %onext, %n
  br i1 %odone, label %exit, label %outer
exit:
  ret void
}
'''
SADD = 'declare {i64, i1} @llvm.sadd.with.overflow.i64(i64, i64)\n'
NEST = NESTED.replace('STORED', 'store i64 %va, ptr %pb, align 8')
CHECKED = NESTED.replace('STORED', '%sum = call {i64, i1} @llvm.sadd.with.overflow.i64(i64 %va, i64 %vb)\n  %total = extractvalue {i64, i1} %sum, 0\n  store i64 %total, ptr %pb, align 8') + SADD

NESTED_CASES = {
    'nested': NEST,
    'nested-mac': NEST.replace(LINUX, MAC),
    'nested-checked': CHECKED,
    'nested-two-checked': varied(CHECKED, ('  store i64 %total', '  %again = call {i64, i1} @llvm.sadd.with.overflow.i64(i64 %total, i64 1)\n  store i64 %total')),
    'nested-checked-long': varied(CHECKED, ('  %small = icmp', ''.join(f'  %pad{index} = add i64 %vb, {index}\n' for index in range(25)) + '  %small = icmp')),
    'nested-other-call': varied(NEST, ('  br label %inner_latch\ninner_latch:', '  call void @log(i64 %va)\n  br label %inner_latch\ninner_latch:')) + 'declare void @log(i64)\n',
    'nested-no-store': NESTED.replace('STORED', '%unused = add i64 %va, 1'),
    'nested-volatile': varied(NEST, ('load i64, ptr %pb, align 8', 'load volatile i64, ptr %pb, align 8')),
    'nested-four-blocks': varied(NEST, ('br i1 %greater, label %third, label %inner_latch\nthird:\n  %small = icmp ult i64 %vb, 1000\n  br i1 %small, label %write, label %inner_latch', 'br i1 %greater, label %write, label %inner_latch')),
    'nested-step-two': varied(NEST, ('%jn = add i64 %j, 1', '%jn = add i64 %j, 2')),
    'nested-unsigned-exit': varied(NEST, ('%end = icmp eq i64 %jn, %m', '%end = icmp uge i64 %jn, %m')),
    'nested-loop-id': varied(NEST, ('br i1 %end, label %outer_latch, label %inner', 'br i1 %end, label %outer_latch, label %inner, !llvm.loop !0')) + '!0 = distinct !{!0}\n',
    'nested-entry-count': varied(NEST, ('i64 %m) {', 'i64 %m) !prof !0 {')) + '!0 = !{!"function_entry_count", i64 10}\n',
    'nested-convergent': varied(NEST, ('i64 %m) {', 'i64 %m) convergent {')),
    'nested-top-level': on(HEADER, LINUX) + NEST[NEST.index('define'):].replace('  br i1 %none, label %exit, label %outer\nouter:\n  %o = phi i64 [0, %entry], [%onext, %outer_latch]\n  br label %inner', '  br i1 %none, label %exit, label %inner').replace('[0, %outer], [%jn', '[0, %entry], [%jn').replace('outer_latch:\n  %onext = add i64 %o, 1\n  %odone = icmp eq i64 %onext, %n\n  br i1 %odone, label %exit, label %outer', 'outer_latch:\n  br label %exit'),
}

CASES = {}
for family, cases in [('private-bit-updates', BIT_CASES), ('private-initializations', INIT_CASES), ('small-recursion', RECURSION_CASES), ('validation-peel', PEEL_CASES), ('nested-scans', NESTED_CASES)]:
    for name, ir in cases.items():
        CASES[name] = (family, ir)

# What the C++ passes did with each shape: the change count, the count of a second run, then
# the loads, stores, selects, freezes, terminators and calls the module is left with.
EXPECTED = {
    'bits': (1, 0, 5, 1, 1, 1, 5, 1),
    'bits-switch': (1, 0, 5, 1, 1, 1, 6, 1),
    'bits-linux': (1, 0, 5, 1, 1, 1, 5, 1),
    'bits-x86': (0, 0, 5, 1, 0, 0, 5, 1),
    'bits-mask-first': (1, 0, 5, 1, 1, 1, 5, 1),
    'bits-unbounded-index': (0, 0, 5, 1, 0, 0, 5, 1),
    'bits-index-in-range-edge': (1, 0, 5, 1, 1, 1, 5, 1),
    'bits-byte-elements': (0, 0, 5, 1, 0, 0, 5, 1),
    'bits-byte-elements-overrun': (0, 0, 5, 1, 0, 0, 5, 1),
    'bits-captured': (0, 0, 5, 1, 0, 0, 5, 2),
    'bits-volatile-load': (0, 0, 5, 1, 0, 0, 5, 1),
    'bits-atomic-store': (0, 0, 5, 1, 0, 0, 5, 1),
    'bits-extra-instruction': (0, 0, 5, 1, 0, 0, 5, 1),
    'bits-mask-in-one': (0, 0, 5, 1, 0, 0, 5, 1),
    'bits-xor-update': (0, 0, 5, 1, 0, 0, 5, 1),
    'bits-i128': (0, 0, 5, 1, 0, 0, 5, 1),
    'bits-big-array': (0, 0, 5, 1, 0, 0, 5, 1),
    'bits-under-aligned-array': (0, 0, 5, 1, 0, 0, 5, 1),
    'bits-pointer-argument': (0, 0, 5, 1, 0, 0, 5, 1),
    'bits-zero-has-phi': (0, 0, 5, 1, 0, 0, 5, 1),
    'bits-lifetime-start': (1, 0, 5, 1, 1, 1, 5, 2),
    'bits-lifetime-end-after': (1, 0, 5, 1, 1, 1, 5, 2),
    'bits-lifetime-start-in-loop': (1, 0, 5, 1, 1, 1, 5, 2),
    'bits-lifetime-end-in-loop': (0, 0, 5, 1, 0, 0, 5, 2),
    'bits-metadata': (1, 0, 5, 1, 1, 1, 5, 1),
    'bits-optsize': (0, 0, 5, 1, 0, 0, 5, 1),
    'bits-two-functions': (2, 0, 10, 2, 2, 2, 10, 2),
    'bits-switch-case-two': (0, 0, 5, 1, 0, 0, 6, 1),
    'bits-switch-default-zero': (0, 0, 5, 1, 0, 0, 6, 1),
    'bits-switch-i64': (1, 0, 5, 1, 1, 1, 6, 1),
    'bits-one-shared': (0, 0, 5, 1, 0, 0, 6, 1),
    'init': (1, 0, 3, 1, 0, 0, 4, 1),
    'init-linux': (1, 0, 3, 1, 0, 0, 4, 1),
    'init-x86': (0, 0, 3, 1, 0, 0, 3, 1),
    'init-swapped': (1, 0, 3, 1, 0, 0, 4, 1),
    'init-small': (0, 0, 3, 1, 0, 0, 3, 1),
    'init-smallest': (1, 0, 3, 1, 0, 0, 4, 1),
    'init-nonzero': (0, 0, 3, 1, 0, 0, 3, 1),
    'init-volatile': (0, 0, 3, 1, 0, 0, 3, 1),
    'init-overrun': (0, 0, 3, 1, 0, 0, 3, 1),
    'init-offset': (1, 0, 3, 1, 0, 0, 4, 1),
    'init-offset-overrun': (0, 0, 3, 1, 0, 0, 3, 1),
    'init-captured': (0, 0, 3, 1, 0, 0, 3, 2),
    'init-store-between': (0, 0, 3, 2, 0, 0, 3, 1),
    'init-arithmetic-between': (1, 0, 3, 1, 0, 0, 4, 1),
    'init-both-return': (0, 0, 3, 1, 0, 0, 4, 1),
    'init-return-reads': (0, 0, 4, 1, 0, 0, 3, 1),
    'init-return-lifetime': (1, 0, 3, 1, 0, 0, 4, 2),
    'init-work-phi': (1, 0, 3, 1, 0, 0, 4, 1),
    'init-metadata': (0, 0, 3, 1, 0, 0, 3, 1),
    'init-sanitized': (0, 0, 3, 1, 0, 0, 3, 1),
    'init-dynamic-alloca': (1, 0, 3, 1, 0, 0, 4, 1),
    'init-two-fills': (1, 1, 4, 1, 0, 0, 4, 2),
    'init-two-functions': (2, 0, 6, 2, 0, 0, 8, 2),
    'recursion': (1, 0, 2, 2, 0, 0, 6, 2),
    'recursion-linux': (1, 0, 2, 2, 0, 0, 6, 2),
    'recursion-x86': (0, 0, 1, 1, 0, 0, 4, 2),
    'recursion-external': (0, 0, 1, 1, 0, 0, 4, 2),
    'recursion-private': (1, 0, 2, 2, 0, 0, 6, 2),
    'recursion-noinline': (0, 0, 1, 1, 0, 0, 4, 2),
    'recursion-noinline-call': (0, 0, 1, 1, 0, 0, 4, 2),
    'recursion-two-self-calls': (0, 0, 1, 1, 0, 0, 4, 3),
    'recursion-no-store': (0, 0, 1, 0, 0, 0, 4, 2),
    'recursion-no-load': (0, 0, 0, 1, 0, 0, 4, 2),
    'recursion-alloca': (0, 0, 1, 1, 0, 0, 4, 2),
    'recursion-address-taken': (0, 0, 1, 1, 0, 0, 4, 2),
    'recursion-only-self': (0, 0, 1, 1, 0, 0, 4, 1),
    'recursion-marked': (0, 0, 1, 1, 0, 0, 4, 2),
    'recursion-other-call': (0, 0, 1, 1, 0, 0, 4, 3),
    'recursion-trap': (1, 0, 2, 2, 0, 0, 10, 4),
    'recursion-returns-value': (0, 0, 1, 1, 0, 0, 4, 0),
    'recursion-optsize': (0, 0, 1, 1, 0, 0, 4, 2),
    'recursion-volatile': (0, 0, 1, 1, 0, 0, 4, 2),
    'recursion-mismatched-call': (0, 0, 1, 1, 0, 0, 4, 2),
    'recursion-long': (0, 0, 1, 1, 0, 0, 4, 2),
    'peel': (1, 0, 5, 0, 0, 0, 19, 0),
    'peel-linux': (1, 0, 5, 0, 0, 0, 19, 0),
    'peel-x86': (1, 0, 5, 0, 0, 0, 19, 0),
    'peel-bounded': (1, 0, 16, 0, 0, 0, 35, 0),
    'peel-bounded-linux': (1, 0, 9, 0, 0, 0, 27, 0),
    'peel-bounded-x86': (1, 0, 9, 0, 0, 0, 27, 0),
    'peel-bounded-small': (1, 0, 5, 0, 0, 0, 19, 0),
    'peel-bounded-large': (1, 0, 5, 0, 0, 0, 19, 0),
    'peel-tiny': (1, 0, 7, 0, 0, 0, 19, 0),
    'peel-tiny-one': (1, 0, 0, 0, 0, 0, 4, 0),
    'peel-tiny-x86': (1, 0, 5, 0, 0, 0, 19, 0),
    'peel-search': (0, 0, 3, 0, 0, 0, 10, 0),
    'peel-search-writes': (1, 0, 18, 0, 0, 0, 40, 0),
    'peel-search-unbounded': (1, 0, 7, 0, 0, 0, 24, 0),
    'peel-search-x86': (1, 0, 11, 0, 0, 0, 32, 0),
    'peel-store': (0, 0, 1, 1, 0, 0, 5, 0),
    'peel-two-loads': (0, 0, 2, 0, 0, 0, 5, 0),
    'peel-volatile': (0, 0, 1, 0, 0, 0, 5, 0),
    'peel-third-compare': (0, 0, 1, 0, 0, 0, 5, 0),
    'peel-loop-id': (0, 0, 1, 0, 0, 0, 5, 0),
    'peel-optsize': (0, 0, 1, 0, 0, 0, 5, 0),
    'peel-long': (0, 0, 1, 0, 0, 0, 5, 0),
    'peel-sixteen': (1, 0, 5, 0, 0, 0, 19, 0),
    'peel-two-loops': (2, 0, 10, 0, 0, 0, 38, 0),
    'nested': (1, 0, 6, 3, 0, 1, 25, 1),
    'nested-mac': (0, 0, 2, 1, 0, 0, 9, 0),
    'nested-checked': (1, 0, 30, 15, 0, 1, 80, 1),
    'nested-two-checked': (0, 0, 2, 1, 0, 0, 9, 0),
    'nested-checked-long': (0, 0, 2, 1, 0, 0, 9, 0),
    'nested-other-call': (0, 0, 2, 1, 0, 0, 9, 1),
    'nested-no-store': (0, 0, 2, 0, 0, 0, 9, 0),
    'nested-volatile': (0, 0, 2, 1, 0, 0, 9, 0),
    'nested-four-blocks': (0, 0, 2, 1, 0, 0, 8, 0),
    'nested-step-two': (0, 0, 2, 1, 0, 0, 9, 0),
    'nested-unsigned-exit': (0, 0, 2, 1, 0, 0, 9, 0),
    'nested-loop-id': (0, 0, 2, 1, 0, 0, 9, 0),
    'nested-entry-count': (0, 0, 2, 1, 0, 0, 9, 0),
    'nested-convergent': (0, 0, 2, 1, 0, 0, 9, 0),
    'nested-top-level': (0, 0, 2, 1, 0, 0, 8, 0),
}
