"""IR shapes for the AArch64 reverse byte reductions, shared by their test.

Each case stores bytes `b0..b{n-1}` into a private 16-byte array through a chain of blocks
that each store one more byte and pick the prefix length, then hashes the prefix from its
end: `hash = hash * radix + zext(bytes[i - 1])` for i from the length down to 1.
"""

MAC = 'arm64-apple-macosx14.0.0'
LINUX = 'aarch64-unknown-linux-gnu'
X86 = 'x86_64-apple-macosx14.0.0'


def reduction_case(lengths=4, radix=31, zero_fill=True, fill_after_store=False, triple=MAC, attributes='',
                   constant_bytes=False, extra_entry='', length_shift=0, extra_body='', swapped_offsets=False, volatile=''):
    """The function described in the module docstring, with LENGTHS storing blocks."""
    parameters = ', '.join([f'i8 %b{index}' for index in range(lengths)] + [f'i1 %c{index}' for index in range(lengths)])
    blocks = ''
    for index in range(lengths):
        offset = 3 - index if swapped_offsets and index in (1, 2) else index
        pointer = '%array' if offset == 0 else f'%p{index}'
        address = '' if offset == 0 else f'  %p{index} = getelementptr i8, ptr %array, i64 {offset}\n'
        value = f'i8 {index + 7}' if constant_bytes else f'i8 %b{index}'
        fill = '  call void @llvm.memset.p0.i64(ptr %array, i8 0, i64 16, i1 false)\n' if zero_fill and index == 0 else ''
        store = f'  store {volatile}{value}, ptr {pointer}\n'
        first, second = (store, fill) if fill_after_store else (fill, store)
        successor = f'  br i1 %c{index}, label %prefix, label %s{index + 1}\n' if index < lengths - 1 else '  br label %prefix\n'
        blocks += f's{index}:\n{address}{first}{second}{successor}'
    incoming = ', '.join(f'[{index + 1 + (length_shift if index == 1 else 0)}, %s{index}]' for index in range(lengths))
    return f'''target triple = "{triple}"
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)
define i64 @f({parameters}) {attributes} {{
entry:
  %array = alloca [16 x i8]
{extra_entry}  br label %s0
{blocks}prefix:
  %length = phi i64 {incoming}
  br label %body
body:
  %i = phi i64 [%length, %prefix], [%step, %body]
  %hash = phi i64 [0, %prefix], [%next, %body]
  %step = add i64 %i, -1
  %slot = getelementptr i8, ptr %array, i64 %step
  %byte = load i8, ptr %slot
  %wide = zext i8 %byte to i64
  %scaled = mul i64 %hash, {radix}
  %next = add i64 %scaled, %wide
  %done = icmp eq i64 %step, 0
{extra_body}  br i1 %done, label %exit, label %body
exit:
  ret i64 %next
}}
'''


# name -> (IR, storing blocks, reductions the C++ pass folded)
CASES = {
    'four': (reduction_case(), 4, 1),
    'eight': (reduction_case(8), 8, 1),
    'twelve': (reduction_case(12), 12, 1),
    'three': (reduction_case(3), 3, 0),
    'thirteen': (reduction_case(13), 13, 0),
    'large_radix': (reduction_case(8, radix=1000003), 8, 1),
    'negative_radix': (reduction_case(radix=-3), 4, 1),
    'no_fill': (reduction_case(zero_fill=False), 4, 1),
    'fill_after_store': (reduction_case(fill_after_store=True), 4, 0),
    'constant_bytes': (reduction_case(constant_bytes=True), 4, 1),
    'x86': (reduction_case(triple=X86), 4, 0),
    'linux': (reduction_case(triple=LINUX), 4, 1),
    'optsize': (reduction_case(attributes='optsize'), 4, 0),
    'wrong_length': (reduction_case(length_shift=5), 4, 0),
    'extra_load': (reduction_case(extra_entry='  %peek = load i8, ptr %array\n'), 4, 0),
    'swapped_offsets': (reduction_case(swapped_offsets=True), 4, 0),
    'volatile_store': (reduction_case(volatile='volatile '), 4, 0),
    'longer_body': (reduction_case(extra_body='  %unused = add i64 %hash, 1\n'), 4, 0),
}
