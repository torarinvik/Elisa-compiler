"""IR shapes for the AArch64 signed range masks, shared by their test.

Each case loads `x = p[i]` inside a loop, checks `(x + offset) <pred> limit` and, on the
edge the check allows, stores `x + ((x >> shift) & bit)` to `q`. With the default operands
the check keeps x in the signed 32-bit range, so the sum is x's unsigned 32-bit value.
"""

MAC = 'arm64-apple-macosx14.0.0'
LINUX = 'aarch64-unknown-linux-gnu'
X86 = 'x86_64-apple-macosx14.0.0'
SIGNED_WORD_OFFSET = 2147483648
WORD_MODULUS = 4294967296


def normalization_case(offset=SIGNED_WORD_OFFSET, limit=WORD_MODULUS, predicate='ult', bad_edge='bad', good_edge='good',
                       triple=MAC, attributes='', swapped=False, shift=31, bit=WORD_MODULUS, in_loop=True,
                       volatile='', guarded=True, sums=1, trailer=''):
    """The loop (or straight-line) function described in the module docstring."""
    lines = []
    for index in range(sums):
        left, right = ('%mask', '%x') if swapped else ('%x', '%mask')
        lines.append(f'  %sum{index} = add i64 {left}, {right}\n  store i64 %sum{index}, ptr %q\n')
    stores = ''.join(lines)
    if guarded:
        check = (f'  %biased = add i64 %x, {offset}\n  %check = icmp {predicate} i64 %biased, {limit}\n'
                 f'  br i1 %check, label %{good_edge}, label %{bad_edge}\n')
    else:
        check = '  br label %good\n'
    body = (f'  %x = load {volatile}i64, ptr %address\n{check}good:\n  %high = lshr i64 %x, {shift}\n'
            f'  %mask = and i64 %high, {bit}\n{stores}')
    if not in_loop:
        return (f'target triple = "{triple}"\ndefine void @f(ptr %p, ptr %q, i64 %n) {attributes} {{\nentry:\n'
                f'  %address = getelementptr i64, ptr %p, i64 %n\n{body}  ret void\nbad:\n  ret void\n}}\n{trailer}')
    return (f'target triple = "{triple}"\ndefine void @f(ptr %p, ptr %q, i64 %n) {attributes} {{\nentry:\n'
            f'  br label %loop\nloop:\n  %i = phi i64 [0, %entry], [%next, %good]\n'
            f'  %address = getelementptr i64, ptr %p, i64 %i\n{body}  %next = add i64 %i, 1\n'
            f'  %done = icmp eq i64 %next, %n\n  br i1 %done, label %exit, label %loop\n'
            f'bad:\n  ret void\nexit:\n  ret void\n}}\n{trailer}')


SANITIZER_FLAG = '!llvm.module.flags = !{!0}\n!0 = !{i32 1, !"SanitizeAddress", i32 1}\n'

# name -> (IR, sums the C++ pass rewrote)
CASES = {
    'basic': (normalization_case(), 1),
    'swapped': (normalization_case(swapped=True), 1),
    'inverted': (normalization_case(predicate='uge', good_edge='bad', bad_edge='good'), 1),
    'linux': (normalization_case(triple=LINUX), 1),
    'x86': (normalization_case(triple=X86), 0),
    'not_loop': (normalization_case(in_loop=False), 0),
    'unguarded': (normalization_case(guarded=False), 0),
    'wide_range': (normalization_case(offset=SIGNED_WORD_OFFSET + 1), 0),
    'narrow_range': (normalization_case(offset=1000, limit=2000), 1),
    'signed_predicate': (normalization_case(predicate='slt', offset=0, limit=2147483647), 0),
    'shift_30': (normalization_case(shift=30), 0),
    'bit_31': (normalization_case(bit=2147483648, shift=32), 0),
    'volatile': (normalization_case(volatile='volatile '), 0),
    'optsize': (normalization_case(attributes='optsize'), 0),
    'asan': (normalization_case(attributes='sanitize_address'), 0),
    'memtag': (normalization_case(attributes='sanitize_memtag'), 0),
    'realtime': (normalization_case(attributes='sanitize_realtime'), 0),
    'sanitizer_flag': (normalization_case(trailer=SANITIZER_FLAG), 0),
    'two_sums': (normalization_case(sums=2), 2),
    'sixty_four': (normalization_case(sums=64), 64),
    'sixty_five': (normalization_case(sums=65), 0),
    'empty_range': (normalization_case(limit=0), 0),
}
