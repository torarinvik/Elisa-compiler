"""IR shapes for the bounded-copy expansion, shared by its tests.

`bounded-copies` expands a `memcpy` or `memmove` whose length is not a constant but
is at most 32 bytes on every path into fixed-size loads and stores. The bound comes
from the comparisons on the paths to the copy (through logical and/or, joins, loop
entries, even-only edges, additions and right shifts), from constant scalings and
zero extensions of the length, and from the room left in an alloca; the length's
known bits remove lengths it cannot have. Each case's count and the chunks it leaves
are what the C++ pass did with the same shapes (see EXPECTED).
"""
DARWIN = 'arm64-apple-darwin'
DECLARATIONS = '''declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1)
declare void @llvm.memmove.p0.p0.i64(ptr, ptr, i64, i1)
declare void @llvm.memcpy.p1.p0.i64(ptr addrspace(1), ptr, i64, i1)
declare i1 @condition()
'''


def copy_call(length='%n', kind='memcpy', destination='ptr align 8 %d', source='ptr align 4 %s', volatile='false', tail=''):
    return f'  call void @llvm.{kind}.p0.p0.i64({destination}, {source}, i64 {length}, i1 {volatile}){tail}\n'


def guarded(test, length='%n', prelude='', call=None, attributes='', parameters='i64 %n', tail=''):
    """`copy` tests TEST on entry (a value named %small) and copies on its true edge."""
    body = call if call is not None else copy_call(length)
    return f'''target triple = "{DARWIN}"
{DECLARATIONS}define void @copy(ptr %d, ptr %s, {parameters}) {attributes} {{
entry:
{prelude}{test}  br i1 %small, label %go, label %out
go:
{body}  br label %out
out:
  ret void
}}
{tail}'''


def below(bound, value='%n', width='i64'):
    return f'  %small = icmp ult {width} {value}, {bound}\n'


def joined(left_bound, right_bound):
    """Two paths, each bounding %n on its own, meet at the copy."""
    right = f'  %right.small = icmp ult i64 %n, {right_bound}\n  br i1 %right.small, label %go, label %out\n' if right_bound else '  br label %go\n'
    return f'''target triple = "{DARWIN}"
{DECLARATIONS}define void @copy(ptr %d, ptr %s, i64 %n, i1 %which) {{
entry:
  br i1 %which, label %left, label %right
left:
  %left.small = icmp ult i64 %n, {left_bound}
  br i1 %left.small, label %go, label %out
right:
{right}go:
{copy_call()}  br label %out
out:
  ret void
}}
'''


def diamonds(count, bound=20):
    """COUNT diamonds after the bound test, so the join walk runs deeper than its limit."""
    blocks = []
    for index in range(count):
        following = f'diamond{index + 1}' if index + 1 < count else 'go'
        blocks.append(f'''diamond{index}:
  %c{index} = call i1 @condition()
  br i1 %c{index}, label %a{index}, label %b{index}
a{index}:
  br label %{following}
b{index}:
  br label %{following}
''')
    return f'''target triple = "{DARWIN}"
{DECLARATIONS}define void @copy(ptr %d, ptr %s, i64 %n) {{
entry:
  %small = icmp ult i64 %n, {bound}
  br i1 %small, label %diamond0, label %out
{''.join(blocks)}go:
{copy_call()}  br label %out
out:
  ret void
}}
'''


def arm_bounds(count):
    """The bounds sit only in the first diamond's arms, COUNT plain diamonds above the copy."""
    blocks = []
    for index in range(count):
        following = f'diamond{index + 1}' if index + 1 < count else 'go'
        blocks.append(f'''diamond{index}:
  %c{index} = call i1 @condition()
  br i1 %c{index}, label %a{index}, label %b{index}
a{index}:
  br label %{following}
b{index}:
  br label %{following}
''')
    return f'''target triple = "{DARWIN}"
{DECLARATIONS}define void @copy(ptr %d, ptr %s, i64 %n, i1 %which) {{
entry:
  br i1 %which, label %left, label %right
left:
  %left.small = icmp ult i64 %n, 8
  br i1 %left.small, label %diamond0, label %out
right:
  %right.small = icmp ult i64 %n, 16
  br i1 %right.small, label %diamond0, label %out
{''.join(blocks)}go:
{copy_call()}  br label %out
out:
  ret void
}}
'''


def looped(inside_bound=None):
    """The copy in a loop entered after the bound test; the back edge does not compare %n."""
    test = f'  %inner = icmp ult i64 %n, {inside_bound}\n  br i1 %inner, label %body, label %latch\nbody:\n' if inside_bound else ''
    return f'''target triple = "{DARWIN}"
{DECLARATIONS}define void @copy(ptr %d, ptr %s, i64 %n, i64 %count) {{
entry:
  %small = icmp ult i64 %n, 24
  br i1 %small, label %loop, label %out
loop:
  %i = phi i64 [ 0, %entry ], [ %next, %latch ]
{test}{copy_call()}  br label %latch
latch:
  %next = add i64 %i, 1
  %more = icmp ult i64 %next, %count
  br i1 %more, label %loop, label %out
out:
  ret void
}}
'''


def stack(size, offset, length_bound=None):
    """A copy into an alloca of SIZE bytes at OFFSET, its length unbounded unless LENGTH_BOUND."""
    test = below(length_bound) if length_bound else '  %small = call i1 @condition()\n'
    prelude = f'  %buffer = alloca [{size} x i8], align 8\n  %slot = getelementptr inbounds i8, ptr %buffer, i64 {offset}\n'
    return guarded(test, prelude=prelude, call=copy_call(destination='ptr align 4 %slot'))


CASES = {
    'below-33': guarded(below(33)),
    'below-17': guarded(below(17)),
    'below-34': guarded(below(34)),
    'below-9': guarded(below(9)),
    'below-3': guarded(below(3)),
    'below-2': guarded(below(2)),
    'below-1': guarded(below(1)),
    'swapped-compare': guarded('  %small = icmp ugt i64 20, %n\n'),
    'at-least-and-at-most': guarded('  %low = icmp uge i64 %n, 8\n  %high = icmp ule i64 %n, 16\n  %small = and i1 %low, %high\n'),
    'select-and': guarded('  %low = icmp uge i64 %n, 4\n  %high = icmp ult i64 %n, 12\n  %small = select i1 %low, i1 %high, i1 false\n'),
    'or-on-false-edge': guarded('  %big = icmp ugt i64 %n, 16\n  %other = call i1 @condition()\n  %large = or i1 %big, %other\n  %small = xor i1 %large, true\n',
                                ),
    'or-branch-false-edge': guarded('  %big = icmp ugt i64 %n, 16\n  %other = call i1 @condition()\n  %small = or i1 %big, %other\n').replace(
        'br i1 %small, label %go, label %out', 'br i1 %small, label %out, label %go'),
    'select-or-false-edge': guarded('  %big = icmp uge i64 %n, 12\n  %other = call i1 @condition()\n  %small = select i1 %big, i1 true, i1 %other\n').replace(
        'br i1 %small, label %go, label %out', 'br i1 %small, label %out, label %go'),
    'equal-to-masked': guarded('  %mask = and i64 %x, 15\n  %small = icmp eq i64 %n, %mask\n', parameters='i64 %n, i64 %x'),
    'equal-to-unbounded': guarded('  %small = icmp eq i64 %n, %x\n', parameters='i64 %n, i64 %x'),
    'shifted-below': guarded('  %quarter = lshr i64 %n, 2\n  %small = icmp ult i64 %quarter, 4\n'),
    'shifted-wide': guarded('  %quarter = lshr i64 %n, 64\n  %small = icmp ult i64 %quarter, 4\n'),
    'offset-below': guarded('  %moved = add i64 %n, -4\n  %small = icmp ult i64 %moved, 8\n'),
    'offset-shifted-below': guarded('  %moved = add i64 %n, 3\n  %half = lshr i64 %moved, 1\n  %small = icmp ult i64 %half, 9\n'),
    'even-edge': guarded('  %bounded = icmp ult i64 %n, 9\n  %odd = trunc i64 %n to i1\n  %even = xor i1 %odd, true\n  %small = and i1 %bounded, %even\n'),
    'even-branch': guarded('  %bounded = icmp ult i64 %n, 9\n  br i1 %bounded, label %parity, label %out\nparity:\n  %small = trunc i64 %n to i1\n').replace(
        'br i1 %small, label %go, label %out', 'br i1 %small, label %out, label %go'),
    'even-or-branch': guarded('  %bounded = icmp uge i64 %n, 11\n  %odd = trunc i64 %n to i1\n  %small = or i1 %bounded, %odd\n').replace(
        'br i1 %small, label %go, label %out', 'br i1 %small, label %out, label %go'),
    'shift-length': guarded(below(3, '%k'), length='%n', prelude='  %n = shl nuw i64 %k, 3\n', parameters='i64 %k'),
    'shift-length-two': guarded(below(2, '%k'), length='%n', prelude='  %n = shl nuw i64 %k, 3\n', parameters='i64 %k'),
    'shift-length-wrapping': guarded(below(3, '%k'), length='%n', prelude='  %n = shl i64 %k, 3\n', parameters='i64 %k'),
    'shift-length-too-far': guarded(below(3, '%k'), length='%n', prelude='  %n = shl nuw i64 %k, 70\n', parameters='i64 %k'),
    'multiply-length': guarded(below(5, '%k'), length='%n', prelude='  %n = mul nuw i64 %k, 4\n', parameters='i64 %k'),
    'multiply-length-constant-first': guarded(below(5, '%k'), length='%n', prelude='  %n = mul nuw i64 4, %k\n', parameters='i64 %k'),
    'multiply-length-overflow': guarded('  %small = call i1 @condition()\n', length='%n', prelude='  %n = mul nuw i64 %k, 4\n', parameters='i64 %k'),
    'extended-length': guarded(below(10, '%m', 'i32'), length='%n', prelude='  %n = zext i32 %m to i64\n', parameters='i32 %m'),
    'extended-shifted-length': guarded(below(4, '%m', 'i32'), length='%n', prelude='  %wide = zext i32 %m to i64\n  %n = shl nuw i64 %wide, 2\n', parameters='i32 %m'),
    'narrow-compare-ignored': guarded('  %narrow = trunc i64 %n to i32\n  %small = icmp ult i32 %narrow, 8\n'),
    'masked-known-bits': guarded(below(29), length='%n', prelude='  %n = and i64 %x, 28\n', parameters='i64 %x'),
    'masked-known-bits-unbounded': guarded('  %small = call i1 @condition()\n', length='%n', prelude='  %n = and i64 %x, 28\n', parameters='i64 %x'),
    'known-one-bit': guarded(below(20), length='%n', prelude='  %n = or i64 %x, 4\n', parameters='i64 %x'),
    'memmove': guarded(below(25), call=copy_call(kind='memmove')),
    'volatile': guarded(below(25), call=copy_call(volatile='true')),
    'constant-length': guarded(below(25), call=copy_call(length='12')),
    'other-address-space': guarded(below(25), call='  call void @llvm.memcpy.p1.p0.i64(ptr addrspace(1) %far, ptr %s, i64 %n, i1 false)\n',
                                   parameters='i64 %n, ptr addrspace(1) %far'),
    'operand-bundle': guarded(below(25), call=copy_call(tail=' [ "deopt"() ]')),
    'optnone': guarded(below(25), attributes='noinline optnone'),
    'minsize': guarded(below(25), attributes='minsize'),
    'unaligned': guarded(below(25), call=copy_call(destination='ptr %d', source='ptr %s')),
    'aligned-16': guarded(below(25), call=copy_call(destination='ptr align 16 %d', source='ptr align 16 %s')),
    'debug-location': guarded(below(25), call=copy_call(tail=', !dbg !9'), tail='''!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!3}
!0 = distinct !DICompileUnit(language: DW_LANG_C, file: !1, emissionKind: FullDebug)
!1 = !DIFile(filename: "copy.elisa", directory: "/")
!3 = !{i32 2, !"Debug Info Version", i32 3}
!5 = distinct !DISubprogram(name: "copy", scope: !1, file: !1, line: 1, type: !6, unit: !0, spFlags: DISPFlagDefinition)
!6 = !DISubroutineType(types: !{})
!9 = !DILocation(line: 4, column: 3, scope: !5)
''').replace('define void @copy(ptr %d, ptr %s, i64 %n)  {', 'define void @copy(ptr %d, ptr %s, i64 %n) !dbg !5 {'),
    'two-copies': guarded(below(13), call=copy_call() + copy_call(length='%n', destination='ptr align 8 %s', source='ptr align 8 %d')),
    'joined-bounds': joined(8, 4),
    'joined-one-unbounded': joined(8, None),
    'joined-wide': joined(40, 4),
    'diamonds-shallow': diamonds(3),
    'diamonds-deep': diamonds(14),
    'arm-bounds-shallow': arm_bounds(3),
    'arm-bounds-deep': arm_bounds(12),
    'arm-bounds-limit': arm_bounds(11),
    'loop-entry-bound': looped(),
    'loop-inner-bound': looped(9),
    'stack-room': stack(24, 4),
    'stack-room-large': stack(64, 8),
    'stack-room-past-end': stack(16, 20),
    'stack-room-and-bound': stack(64, 0, 11),
    'unbounded': guarded('  %small = call i1 @condition()\n'),
}


# What the C++ pass did with each case: count, chunk blocks, loads, stores and library
# copies left.
EXPECTED = {
    'below-33': (1, 5, 9, 9, 0),
    'below-17': (1, 5, 8, 8, 0),
    'below-34': (0, 0, 0, 0, 1),
    'below-9': (1, 4, 6, 6, 0),
    'below-3': (1, 2, 2, 2, 0),
    'below-2': (1, 1, 1, 1, 0),
    'below-1': (0, 0, 0, 0, 1),
    'swapped-compare': (1, 5, 9, 9, 0),
    'at-least-and-at-most': (1, 2, 3, 3, 0),
    'select-and': (1, 2, 4, 4, 0),
    'or-on-false-edge': (0, 0, 0, 0, 1),
    'or-branch-false-edge': (1, 5, 8, 8, 0),
    'select-or-false-edge': (1, 4, 7, 7, 0),
    'equal-to-masked': (1, 4, 7, 7, 0),
    'equal-to-unbounded': (0, 0, 0, 0, 1),
    'shifted-below': (1, 4, 7, 7, 0),
    'shifted-wide': (0, 0, 0, 0, 1),
    'offset-below': (1, 2, 4, 4, 0),
    'offset-shifted-below': (0, 0, 0, 0, 1),
    'even-edge': (1, 4, 6, 6, 0),
    'even-branch': (1, 4, 6, 6, 0),
    'even-or-branch': (1, 4, 7, 7, 0),
    'shift-length': (1, 2, 2, 2, 0),
    'shift-length-two': (1, 1, 1, 1, 0),
    'shift-length-wrapping': (0, 0, 0, 0, 1),
    'shift-length-too-far': (0, 0, 0, 0, 1),
    'multiply-length': (1, 3, 4, 4, 0),
    'multiply-length-constant-first': (1, 3, 4, 4, 0),
    'multiply-length-overflow': (0, 0, 0, 0, 1),
    'extended-length': (1, 4, 7, 7, 0),
    'extended-shifted-length': (1, 2, 3, 3, 0),
    'narrow-compare-ignored': (0, 0, 0, 0, 1),
    'masked-known-bits': (1, 3, 5, 5, 0),
    'masked-known-bits-unbounded': (0, 0, 0, 0, 1),
    'known-one-bit': (1, 2, 4, 4, 0),
    'memmove': (1, 5, 9, 9, 0),
    'volatile': (0, 0, 0, 0, 1),
    'constant-length': (0, 0, 0, 0, 1),
    'other-address-space': (0, 0, 0, 0, 1),
    'operand-bundle': (0, 0, 0, 0, 1),
    'optnone': (0, 0, 0, 0, 1),
    'minsize': (0, 0, 0, 0, 1),
    'unaligned': (1, 5, 9, 9, 0),
    'aligned-16': (1, 5, 9, 9, 0),
    'debug-location': (1, 5, 9, 9, 0),
    'two-copies': (2, 8, 14, 14, 0),
    'joined-bounds': (1, 3, 5, 5, 0),
    'joined-one-unbounded': (0, 0, 0, 0, 1),
    'joined-wide': (0, 0, 0, 0, 1),
    'diamonds-shallow': (1, 5, 9, 9, 0),
    'diamonds-deep': (1, 5, 9, 9, 0),
    'arm-bounds-shallow': (1, 4, 7, 7, 0),
    'arm-bounds-deep': (0, 0, 0, 0, 1),
    'arm-bounds-limit': (1, 4, 7, 7, 0),
    'loop-entry-bound': (1, 5, 9, 9, 0),
    'loop-inner-bound': (1, 4, 6, 6, 0),
    'stack-room': (1, 5, 9, 9, 0),
    'stack-room-large': (0, 0, 0, 0, 1),
    'stack-room-past-end': (0, 0, 0, 0, 1),
    'stack-room-and-bound': (1, 4, 7, 7, 0),
    'unbounded': (0, 0, 0, 0, 1),
}
