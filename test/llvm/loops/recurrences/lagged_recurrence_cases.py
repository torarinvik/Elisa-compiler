"""IR shapes for the lagged-recurrence unroll, shared by its test.

`lagged-recurrences` unrolls a single-block AArch64 loop whose phis rotate a window of
earlier values -- `next = a + b` (two states), `next = a + 2 * b` (a scaled state),
`next = a + b + C` (rebased first, so both states carry C), or `next = a + b` over three
states -- by whole rotations, when the loop runs between 16 and 256 times. Two-state
loops peel their first iteration first. Each case's count, and what it leaves, are what
the C++ pass did with the same shapes (see EXPECTED).
"""
MAC = 'arm64-apple-darwin27.2.0'
LINUX = 'aarch64-unknown-linux-gnu'
X86 = 'x86_64-apple-macosx14.0.0'

# The window update of each recurrence: (phis after the counter, update instructions,
# the value the newest phi takes, the value returned).
UPDATES = {
    'two': ('  %a = phi i64 [ 0, %entry ], [ %b, %loop ]\n  %b = phi i64 [ 1, %entry ], [ %sum, %loop ]\n',
            '  %sum = add i64 %a, %b\n'),
    'scaled': ('  %a = phi i64 [ 0, %entry ], [ %b, %loop ]\n  %b = phi i64 [ 1, %entry ], [ %sum, %loop ]\n',
               '  %double = shl i64 %b, 1\n  %sum = add i64 %a, %double\n'),
    'affine': ('  %a = phi i64 [ 0, %entry ], [ %b, %loop ]\n  %b = phi i64 [ 1, %entry ], [ %sum, %loop ]\n',
               '  %biased = add i64 %a, 7\n  %sum = add i64 %biased, %b\n'),
    'three': ('  %a = phi i64 [ 1, %entry ], [ %b, %loop ]\n  %b = phi i64 [ 1, %entry ], [ %c, %loop ]\n'
              '  %c = phi i64 [ 1, %entry ], [ %sum, %loop ]\n',
              '  %sum = add i64 %a, %b\n'),
}


def recurrence(update='two', limit='90', name='recurrence', attributes='', loop_metadata='', dispatch=False):
    """The UPDATE window advanced from index 2 until the index reaches N; N is in
    [3, LIMIT] (or, with DISPATCH, any value below 128 a switch sends past 0 and 1)."""
    phis, body = UPDATES[update]
    if dispatch:
        entry = f'''entry:
  %n = and i64 %x, 127
  switch i64 %n, label %loop [
    i64 0, label %small
    i64 1, label %small
  ]
small:
  ret i64 %n
'''
    else:
        entry = f'''entry:
  %n = add i64 %x, 0
  %shifted = add i64 %x, -3
  %bad = icmp ugt i64 %shifted, {int(limit) - 3}
  br i1 %bad, label %small, label %loop
small:
  ret i64 0
'''
    return f'''define i64 @{name}(i64 %x) {attributes} {{
{entry}loop:
  %i = phi i64 [ 2, %entry ], [ %i.next, %loop ]
{phis}{body}  %i.next = add i64 %i, 1
  %done = icmp eq i64 %i, %n
  br i1 %done, label %exit, label %loop{loop_metadata}
exit:
  %result = phi i64 [ %sum, %loop ]
  ret i64 %result
}}
'''


def module(*functions, triple=MAC, tail=''):
    return f'target triple = "{triple}"\n' + ''.join(functions) + tail


LOOP_ID = '\n!0 = distinct !{!0, !1}\n!1 = !{!"llvm.loop.mustprogress"}\n'


def padded(update):
    """A recurrence after a chain of 24 branch blocks."""
    text = recurrence(update)
    chain = ''.join(f'pad{index}:\n  br label %pad{index + 1}\n' for index in range(24))
    text = text.replace('entry:\n  %n', 'entry:\n  br label %pad0\n' + chain + 'pad24:\n  %n', 1)
    return text.replace('[ 2, %entry ]', '[ 2, %pad24 ]').replace('[ 0, %entry ]', '[ 0, %pad24 ]').replace('[ 1, %entry ]', '[ 1, %pad24 ]')


CASES = {
    'two': module(recurrence()),
    'two-linux': module(recurrence(), triple=LINUX),
    'two-x86': module(recurrence(), triple=X86),
    'scaled': module(recurrence('scaled')),
    'affine': module(recurrence('affine')),
    'three': module(recurrence('three')),
    'two-trips-15': module(recurrence(limit='16')),
    'two-trips-16': module(recurrence(limit='17')),
    'two-trips-256': module(recurrence(limit='257')),
    'two-trips-257': module(recurrence(limit='258')),
    'three-trips-15': module(recurrence('three', limit='16')),
    'two-dispatch': module(recurrence(dispatch=True)),
    'affine-dispatch': module(recurrence('affine', dispatch=True)),
    'three-dispatch': module(recurrence('three', dispatch=True)),
    'loop-id': module(recurrence(loop_metadata=', !llvm.loop !0'), tail=LOOP_ID),
    'optnone': module(recurrence(attributes='noinline optnone')),
    'affine-nsw': module(recurrence('affine').replace('add i64 %biased, %b', 'add nsw i64 %biased, %b')),
    'affine-zero-offset': module(recurrence('affine').replace('add i64 %a, 7', 'add i64 %a, 0')),
    'affine-variable-seed': module(recurrence('affine').replace('[ 0, %entry ]', '[ %x, %entry ]')),
    'scaled-by-four': module(recurrence('scaled').replace('shl i64 %b, 1', 'shl i64 %b, 2')),
    'counter-step-two': module(recurrence().replace('add i64 %i, 1', 'add i64 %i, 2')),
    'blocks-25': module(padded('two')),
    'two-functions': module(recurrence(name='first'), recurrence('three', name='second')),
}

# What the C++ pass did with each case: (count, loop blocks, recurrence adds, shifts)
# -- see test_lagged_recurrences.shape.
EXPECTED = {
    'affine-dispatch': (3, 16, 9, 0, 2),
    'affine-nsw': (0, 4, 4, 0, 0),
    'affine-variable-seed': (1, 5, 5, 0, 0),
    'affine-zero-offset': (0, 4, 5, 0, 0),
    'affine': (3, 16, 12, 0, 2),
    'blocks-25': (0, 29, 4, 0, 0),
    'counter-step-two': (0, 4, 4, 0, 0),
    'loop-id': (0, 4, 4, 0, 0),
    'optnone': (0, 4, 4, 0, 0),
    'scaled-by-four': (0, 4, 4, 1, 0),
    'scaled': (3, 16, 12, 6, 1),
    'three-dispatch': (0, 4, 2, 0, 0),
    'three-trips-15': (0, 4, 4, 0, 0),
    'three': (2, 10, 13, 0, 1),
    'two-dispatch': (3, 16, 9, 0, 1),
    'two-functions': (5, 26, 25, 0, 2),
    'two-linux': (3, 16, 12, 0, 1),
    'two-trips-15': (0, 4, 4, 0, 0),
    'two-trips-16': (3, 16, 12, 0, 1),
    'two-trips-256': (3, 16, 12, 0, 1),
    'two-trips-257': (0, 4, 4, 0, 0),
    'two-x86': (0, 4, 4, 0, 0),
    'two': (3, 16, 12, 0, 1),
}
