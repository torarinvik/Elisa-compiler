"""IR shapes for the private array copy elision, shared by its test.

`round_trip` copies T into U, writes U and copies it back; `forward_copy` copies T into U
and never uses T again; `copy_temporary` passes a loop result through a temporary used
only by two adjacent copies; `libcall_round_trip` spells the copies as `memcpy` or
`memmove` calls; `reverse_fill` zero-fills an array a descending loop then rewrites
before an ascending loop reads it. Each case maps to the change count the C++ pass
reported for the same input: a copy shorter than either block, or a T less aligned than
U, keeps both copies.
"""
DECLARATIONS = '''declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1)
declare void @llvm.memmove.p0.p0.i64(ptr, ptr, i64, i1)
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)
declare void @llvm.lifetime.start.p0(ptr)
declare void @llvm.lifetime.end.p0(ptr)
declare ptr @memcpy(ptr, ptr, i64)
declare ptr @malloc(i64)
declare void @free(ptr)
declare void @observe(ptr)
declare void @abort()
'''


def module(body):
    return f'target triple = "arm64-apple-macosx14.0.0"\n{DECLARATIONS}{body}'


def round_trip(between='', after_second='', u_size=64, t_size=64, first_length=64, second_length=64, volatile='false', u_align=16, t_align=16,
               attributes='', markers=False, branch=None):
    lifetime_start = '  call void @llvm.lifetime.start.p0(ptr %u)\n' if markers else ''
    lifetime_end = '  call void @llvm.lifetime.end.p0(ptr %u)\n' if markers else ''
    body = between
    if branch == 'return':
        body += '  br i1 %c, label %early, label %late\nearly:\n  ret void\nlate:\n'
    elif branch == 'trap':
        body += '  br i1 %c, label %early, label %late\nearly:\n  call void @abort()\n  unreachable\nlate:\n'
    elif branch == 'loop':
        body += '  br label %again\nagain:\n  br i1 %c, label %again, label %late\nlate:\n'
    return module(f'''define void @f(ptr %out, i1 %c, i32 %x) {attributes} {{
entry:
  %t = alloca [{t_size // 4} x i32], align {t_align}
  %u = alloca [{u_size // 4} x i32], align {u_align}
  call void @llvm.memset.p0.i64(ptr %t, i8 0, i64 {t_size}, i1 false)
{lifetime_start}  call void @llvm.memcpy.p0.p0.i64(ptr %u, ptr %t, i64 {first_length}, i1 {volatile})
  %slot = getelementptr [16 x i32], ptr %u, i64 0, i64 3
  store i32 %x, ptr %slot
{body}  call void @llvm.memcpy.p0.p0.i64(ptr %t, ptr %u, i64 {second_length}, i1 false)
{lifetime_end}{after_second}  %read = getelementptr [16 x i32], ptr %t, i64 0, i64 3
  %value = load i32, ptr %read
  store i32 %value, ptr %out
  ret void
}}
''')


def forward_copy(after='', t_end=False, u_before=''):
    end = '  call void @llvm.lifetime.end.p0(ptr %t)\n' if t_end else ''
    return module(f'''define i64 @f(i64 %x) {{
entry:
  %t = alloca [8 x i64], align 8
  %u = alloca [8 x i64], align 8
  call void @llvm.lifetime.start.p0(ptr %t)
  %t.slot = getelementptr [8 x i64], ptr %t, i64 0, i64 2
  store i64 %x, ptr %t.slot
{u_before}  call void @llvm.memcpy.p0.p0.i64(ptr %u, ptr %t, i64 64, i1 false)
{end}{after}  %u.slot = getelementptr [8 x i64], ptr %u, i64 0, i64 2
  %value = load i64, ptr %u.slot
  ret i64 %value
}}
''')


def copy_temporary(adjacent=True, temporary_length=64, extra_use=''):
    gap = '' if adjacent else '  %gap = add i32 0, 1\n'
    return module(f'''define void @f(ptr %out) {{
entry:
  %source = alloca [16 x i32], align 4
  %temporary = alloca [16 x i32], align 4
  %destination = alloca [16 x i32], align 4
  call void @llvm.memset.p0.i64(ptr %source, i8 1, i64 64, i1 false)
  call void @observe(ptr %source)
  call void @observe(ptr %destination)
  call void @llvm.memcpy.p0.p0.i64(ptr align 4 %temporary, ptr align 4 %source, i64 {temporary_length}, i1 false)
{gap}  call void @llvm.memcpy.p0.p0.i64(ptr align 8 %destination, ptr align 4 %temporary, i64 {temporary_length}, i1 false)
{extra_use}  ret void
}}
''')


def libcall_round_trip(spelling='memcpy', used=False, variable_length=False):
    length = '%n' if variable_length else '64'
    if spelling == 'memcpy':
        result = '%copy = ' if used else ''
        first = f'  {result}call ptr @memcpy(ptr %u, ptr %t, i64 {length})\n'
        if used:
            first += '  call void @observe(ptr %copy)\n'
        second = '  call ptr @memcpy(ptr %t, ptr %u, i64 64)\n'
    else:
        first = f'  call void @llvm.memmove.p0.p0.i64(ptr %u, ptr %t, i64 {length}, i1 false)\n'
        second = '  call void @llvm.memmove.p0.p0.i64(ptr %t, ptr %u, i64 64, i1 false)\n'
    return module(f'''define void @f(ptr %out, i32 %x, i64 %n) {{
entry:
  %t = alloca [16 x i32], align 16
  %u = alloca [16 x i32], align 16
  call void @llvm.memset.p0.i64(ptr %t, i8 0, i64 64, i1 false)
{first}  %slot = getelementptr [16 x i32], ptr %u, i64 0, i64 1
  store i32 %x, ptr %slot
{second}  %read = getelementptr [16 x i32], ptr %t, i64 0, i64 1
  %value = load i32, ptr %read
  store i32 %value, ptr %out
  ret void
}}
''')


def malloc_round_trip(free_u=True):
    free = '  call void @free(ptr %u)\n' if free_u else ''
    return module(f'''define void @f(ptr %out, i32 %x) {{
entry:
  %t = call ptr @malloc(i64 64)
  %u = call ptr @malloc(i64 64)
  call void @llvm.memset.p0.i64(ptr %t, i8 0, i64 64, i1 false)
  call void @llvm.memcpy.p0.p0.i64(ptr %u, ptr %t, i64 64, i1 false)
  %slot = getelementptr i32, ptr %u, i64 5
  store i32 %x, ptr %slot
  call void @llvm.memcpy.p0.p0.i64(ptr %t, ptr %u, i64 64, i1 false)
{free}  %read = getelementptr i32, ptr %t, i64 5
  %value = load i32, ptr %read
  store i32 %value, ptr %out
  call void @free(ptr %t)
  ret void
}}
''')


def reverse_fill(byte=0, volatile='false', step='add i64 %i, -1', read_start='0', latch='icmp eq', read_element='i32', bypass=False, second_read='', fill_in_loop=False, lifetime=''):
    entry_branch = '  br i1 %skip, label %reader.entry, label %writer\n' if bypass else '  br label %writer\n'
    fill = f'  call void @llvm.memset.p0.i64(ptr %array, i8 {byte}, i64 128, i1 {volatile})\n'
    prelude = f'{fill}{entry_branch}' if not fill_in_loop else f'  br label %fill.loop\nfill.loop:\n  %k = phi i32 [ 0, %entry ], [ %k.next, %fill.loop ]\n{fill}  %k.next = add i32 %k, 1\n  %k.done = icmp eq i32 %k.next, 2\n  br i1 %k.done, label %writer.pre, label %fill.loop\nwriter.pre:\n{entry_branch}'
    preheader = '%writer.pre' if fill_in_loop else '%entry'
    exit_compare = f'{latch} i64 %i.next, 0'
    exit_order = 'label %reader.entry, label %writer' if latch == 'icmp eq' else 'label %writer, label %reader.entry'
    return module(f'''define i32 @f(i64 %n, i32 %v, i1 %skip) {{
entry:
  %array = alloca [32 x i32], align 16
{lifetime}{prelude}writer:
  %i = phi i64 [ %n, {preheader} ], [ %i.next, %writer ]
  %i.next = {step}
  %write.slot = getelementptr i32, ptr %array, i64 %i.next
  store i32 %v, ptr %write.slot
  %writer.done = {exit_compare}
  br i1 %writer.done, {exit_order}
reader.entry:
  br label %reader
reader:
  %j = phi i64 [ {read_start}, %reader.entry ], [ %j.next, %reader ]
  %sum = phi i32 [ 0, %reader.entry ], [ %sum.next, %reader ]
  %read.slot = getelementptr {read_element}, ptr %array, i64 %j
  %element = load i32, ptr %read.slot
{second_read}  %sum.next = add i32 %sum, %element
  %j.next = add i64 %j, 1
  %reader.done = icmp eq i64 %j.next, %n
  br i1 %reader.done, label %exit, label %reader
exit:
  ret i32 %sum.next
}}
''')


CASES = {
    'round-trip': (round_trip(), 1),
    'round-trip-markers': (round_trip(markers=True), 1),
    'round-trip-t-read-while-dirty': (round_trip(between='  %peek.slot = getelementptr [16 x i32], ptr %t, i64 0, i64 1\n  %peek = load i32, ptr %peek.slot\n  store i32 %peek, ptr %out\n'), 0),
    'round-trip-t-written-then-u-used': (round_trip(between='  %t.slot = getelementptr [16 x i32], ptr %t, i64 0, i64 1\n  store i32 1, ptr %t.slot\n  store i32 2, ptr %slot\n'), 0),
    'round-trip-u-escapes': (round_trip(between='  call void @observe(ptr %u)\n'), 0),
    'round-trip-size-mismatch': (round_trip(u_size=128), 0),
    'round-trip-short-copy': (round_trip(first_length=32), 0),
    'round-trip-short-copy-back': (round_trip(second_length=32), 0),
    'round-trip-volatile': (round_trip(volatile='true'), 0),
    'round-trip-less-aligned-t': (round_trip(t_align=4), 0),
    'round-trip-early-return': (round_trip(branch='return'), 0),
    'round-trip-trap': (round_trip(branch='trap'), 1),
    'round-trip-loop-between': (round_trip(branch='loop'), 1),
    'round-trip-optnone': (round_trip(attributes='noinline optnone'), 0),
    'round-trip-malloc': (malloc_round_trip(), 1),
    'round-trip-malloc-no-free': (malloc_round_trip(free_u=False), 1),
    'forward': (forward_copy(), 1),
    'forward-t-used-after': (forward_copy(after='  %again = getelementptr [8 x i64], ptr %t, i64 0, i64 1\n  store i64 5, ptr %again\n'), 0),
    'forward-t-ends-before-u-use': (forward_copy(t_end=True), 0),
    'forward-t-ends-after-u-use': (forward_copy(after='  %u.first = getelementptr [8 x i64], ptr %u, i64 0, i64 1\n  %early = load i64, ptr %u.first\n  call void @llvm.lifetime.end.p0(ptr %t)\n'), 0),
    'forward-u-written-before-copy': (forward_copy(u_before='  %u.early = getelementptr [8 x i64], ptr %u, i64 0, i64 1\n  store i64 3, ptr %u.early\n'), 0),
    'temporary': (copy_temporary(), 1),
    'temporary-not-adjacent': (copy_temporary(adjacent=False), 0),
    'temporary-short': (copy_temporary(temporary_length=32), 0),
    'temporary-extra-use': (copy_temporary(extra_use='  call void @observe(ptr %temporary)\n'), 0),
    'libcall-memcpy': (libcall_round_trip(), 1),
    'libcall-memcpy-used': (libcall_round_trip(used=True), 0),
    'libcall-memcpy-variable-length': (libcall_round_trip(variable_length=True), 0),
    'libcall-memmove': (libcall_round_trip(spelling='memmove'), 1),
    'reverse-fill': (reverse_fill(), 1),
    'reverse-fill-nonzero-byte': (reverse_fill(byte=1), 0),
    'reverse-fill-volatile': (reverse_fill(volatile='true'), 0),
    'reverse-fill-sub-step': (reverse_fill(step='sub i64 %i, 1'), 1),
    'reverse-fill-ascending-writer': (reverse_fill(step='add i64 %i, 1'), 0),
    'reverse-fill-reader-from-one': (reverse_fill(read_start='1'), 0),
    'reverse-fill-ne-latch': (reverse_fill(latch='icmp ne'), 1),
    'reverse-fill-wide-reader': (reverse_fill(read_element='i64'), 0),
    'reverse-fill-bypass': (reverse_fill(bypass=True), 0),
    'reverse-fill-second-read': (reverse_fill(second_read='  %again.slot = getelementptr i32, ptr %array, i64 %j\n  %again = load i32, ptr %again.slot\n'), 0),
    'reverse-fill-in-loop': (reverse_fill(fill_in_loop=True), 0),
    'reverse-fill-lifetime': (reverse_fill(lifetime='  call void @llvm.lifetime.start.p0(ptr %array)\n'), 1),
}

# The (allocations, copies, fills) left in `@f` after the C++ pass, copies counting
# `llvm.memcpy`, `llvm.memmove` and `memcpy` calls.
SHAPES = {
    'round-trip': (1, 0, 1),
    'round-trip-markers': (1, 0, 1),
    'round-trip-t-read-while-dirty': (2, 2, 1),
    'round-trip-t-written-then-u-used': (2, 2, 1),
    'round-trip-u-escapes': (2, 2, 1),
    'round-trip-size-mismatch': (2, 2, 1),
    'round-trip-short-copy': (2, 2, 1),
    'round-trip-short-copy-back': (2, 2, 1),
    'round-trip-volatile': (2, 2, 1),
    'round-trip-less-aligned-t': (2, 2, 1),
    'round-trip-early-return': (2, 2, 1),
    'round-trip-trap': (1, 0, 1),
    'round-trip-loop-between': (1, 0, 1),
    'round-trip-optnone': (2, 2, 1),
    'round-trip-malloc': (1, 0, 1),
    'round-trip-malloc-no-free': (1, 0, 1),
    'forward': (1, 0, 0),
    'forward-t-used-after': (2, 1, 0),
    'forward-t-ends-before-u-use': (2, 1, 0),
    'forward-t-ends-after-u-use': (2, 1, 0),
    'forward-u-written-before-copy': (2, 1, 0),
    'temporary': (2, 1, 1),
    'temporary-not-adjacent': (3, 2, 1),
    'temporary-short': (3, 2, 1),
    'temporary-extra-use': (3, 2, 1),
    'libcall-memcpy': (1, 0, 1),
    'libcall-memcpy-used': (2, 2, 1),
    'libcall-memcpy-variable-length': (2, 2, 1),
    'libcall-memmove': (1, 0, 1),
    'reverse-fill': (1, 0, 0),
    'reverse-fill-nonzero-byte': (1, 0, 1),
    'reverse-fill-volatile': (1, 0, 1),
    'reverse-fill-sub-step': (1, 0, 0),
    'reverse-fill-ascending-writer': (1, 0, 1),
    'reverse-fill-reader-from-one': (1, 0, 1),
    'reverse-fill-ne-latch': (1, 0, 0),
    'reverse-fill-wide-reader': (1, 0, 1),
    'reverse-fill-bypass': (1, 0, 1),
    'reverse-fill-second-read': (1, 0, 1),
    'reverse-fill-in-loop': (1, 0, 1),
    'reverse-fill-lifetime': (1, 0, 0),
}
