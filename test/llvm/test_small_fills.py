#!/usr/bin/env python3
"""Check the small-fill expansion and byte-store merges on little-endian AArch64.

- A runtime-length constant-byte memset is inlined through `__elisacore_smallzero_fill`;
  nonzero fills only while a module has at most sixteen.
- On macOS, a function's single aligned 1024..2048-byte zero memset (a multiple of 128)
  becomes `llvm.memset.inline`, and its single constant word-pattern fill of a fixed
  `[N x i64]` stack array (N <= 64) is inlined.
- A low byte store followed by a 7-byte zero fill is one i64 store; four stores of a word's
  bytes, most significant first, are one byte-swapped i32 store.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass

MAC = 'arm64-apple-macosx14.0.0'
LINUX = 'aarch64-unknown-linux-gnu'
LAYOUT = 'e-m:o-i64:64-i128:128-n32:64-S128'
DECLARATIONS = '''declare void @llvm.memset.p0.i64(ptr, i8, i64, i1 immarg)
declare void @llvm.experimental.memset.pattern.p0.i64.i64(ptr, i64, i64, i1 immarg)
'''


def module(body, triple=MAC, attributes='nounwind', parameters='ptr %p, i64 %n, i8 %b, i32 %w'):
    return f'''target datalayout = "{LAYOUT}"
target triple = "{triple}"
{DECLARATIONS}define void @f({parameters}) {attributes} {{
entry:
{body}  ret void
}}
'''


def pattern_fill(elements=16, align=8, value='i64 7', count=1):
    fills = ''.join(f'  call void @llvm.experimental.memset.pattern.p0.i64.i64(ptr align {align} %cells, {value}, i64 {elements}, i1 false)\n'
                    for _ in range(count))
    return f'  %cells = alloca [{elements} x i64], align 8\n{fills}  call void @use(ptr %cells)\n'


def with_use(text):
    return text.replace('  ret void\n}', '  ret void\n}\ndeclare void @use(ptr)')


ZERO_EXTENDED = '''  store i8 %b, ptr %p, align 1
  %q = getelementptr i8, ptr %p, i64 OFFSET
BETWEEN  call void @llvm.memset.p0.i64(ptr %q, i8 0, i64 7, i1 false)
'''


def zero_extended(offset=1, between=''):
    return ZERO_EXTENDED.replace('OFFSET', str(offset)).replace('BETWEEN', between)


def big_endian(order=(0, 1, 2, 3)):
    """Stores of `w`'s bytes, most significant first, at p + 0..3."""
    lines = ''
    for position in order:
        shift = 24 - 8 * position
        source = '%w' if shift == 0 else f'%s{position}'
        if shift:
            lines += f'  %s{position} = lshr i32 %w, {shift}\n'
        lines += f'  %t{position} = trunc i32 {source} to i8\n  %a{position} = getelementptr i8, ptr %p, i64 {position}\n'
    for position in order:
        lines += f'  store i8 %t{position}, ptr %a{position}, align 1\n'
    return lines


def sign_extended_word(high_offset=4, high='%h = ashr i32 %w, 31'):
    """`store_i64_le(w.i64())` after instruction combining: the low word, then its sign word."""
    return f'''  store i32 %w, ptr %p, align 1
  {high}
  %q = getelementptr i8, ptr %p, i64 {high_offset}
  store i32 %h, ptr %q, align 1
'''


def i16_pieces(count=4):
    """The four 16-bit pieces of `x = zext w`, lowest first."""
    lines = '  %x = zext i32 %w to i64\n'
    for k in range(count):
        lines += f'  %s{k} = lshr i64 %x, {16 * k}\n  %t{k} = trunc i64 %s{k} to i16\n  %a{k} = getelementptr i8, ptr %p, i64 {2 * k}\n  store i16 %t{k}, ptr %a{k}, align 2\n'
    return lines


def fixed_fill(bytes_=1024, align=8, value=0, count=1):
    return ''.join(f'  %z{k} = alloca [{bytes_} x i8], align 16\n  call void @llvm.memset.p0.i64(ptr align {align} %z{k}, i8 {value}, i64 {bytes_}, i1 false)\n  call void @use(ptr %z{k})\n'
                   for k in range(count))


def runtime_fills(value=0, count=1):
    return ''.join(f'  call void @llvm.memset.p0.i64(ptr %p, i8 {value}, i64 %n, i1 false)\n' for _ in range(count))


# name: (module, changes, expected text, unexpected text)
CASES = {
    'pattern_fill': (with_use(module(pattern_fill())), 1, 'store <2 x i64> splat (i64 7)', 'call void @llvm.experimental.memset.pattern'),
    'pattern_fill_twice': (with_use(module(pattern_fill(count=2))), 0, 'memset.pattern.p0', 'fill_stack_words'),
    'pattern_fill_aligned_4': (with_use(module(pattern_fill(align=4))), 0, 'memset.pattern.p0', 'fill_stack_words'),
    'pattern_fill_65': (with_use(module(pattern_fill(elements=65))), 0, 'memset.pattern.p0', 'fill_stack_words'),
    'pattern_fill_linux': (with_use(module(pattern_fill(), triple=LINUX)), 0, 'memset.pattern.p0', 'fill_stack_words'),
    'pattern_fill_optsize': (with_use(module(pattern_fill(), attributes='nounwind optsize')), 0, 'memset.pattern.p0', 'fill_stack_words'),
    'zero_extended': (module(zero_extended()), 1, 'store i64 %', 'call void @llvm.memset'),
    'zero_extended_offset_2': (module(zero_extended(offset=2)), 0, 'call void @llvm.memset', 'store i64'),
    'zero_extended_read_between': (module(zero_extended(between='  %r = load i8, ptr %p\n')), 0, 'call void @llvm.memset', 'store i64'),
    'zero_extended_sanitized': (module(zero_extended(), attributes='nounwind sanitize_address'), 0, 'call void @llvm.memset', 'store i64'),
    'big_endian': (module(big_endian()), 1, 'call i32 @llvm.bswap.i32(i32 %w)', 'store i8'),
    'big_endian_reordered': (module(big_endian(order=(1, 0, 2, 3))), 0, 'store i8', 'bswap'),
    'sign_extended_word': (module(sign_extended_word(), triple=LINUX), 1, 'sext i32 %w to i64', 'store i32'),
    'sign_word_gap': (module(sign_extended_word(high_offset=5), triple=LINUX), 0, 'store i32 %h', 'sext i32'),
    'shifted_high_word': (module(sign_extended_word(high='%h = lshr i32 %w, 31'), triple=LINUX), 0, 'store i32 %h', 'sext i32'),
    'zero_extended_pieces': (module(i16_pieces(), triple=LINUX), 1, 'store i64 %0, ptr %a0, align 2', 'store i16'),
    'three_pieces': (module(i16_pieces(count=3), triple=LINUX), 0, 'store i16', 'store i64'),
    'fixed_zero_fill': (with_use(module(fixed_fill())), 1, 'call void @llvm.memset.inline.p0.i64(ptr align 8 %z0, i8 0, i64 1024, i1 false)', 'call void @llvm.memset.p0'),
    'fixed_zero_fill_1000': (with_use(module(fixed_fill(bytes_=1000))), 0, 'call void @llvm.memset.p0', 'memset.inline'),
    'fixed_zero_fill_twice': (with_use(module(fixed_fill(count=2))), 0, 'call void @llvm.memset.p0', 'memset.inline'),
    'fixed_zero_fill_linux': (with_use(module(fixed_fill(), triple=LINUX)), 0, 'call void @llvm.memset.p0', 'memset.inline'),
    # The inlined helper keeps a fallback memset for fills over 64 bytes, marked as such.
    'runtime_zero_fill': (module(runtime_fills()), 1, 'store i128 0', 'i64 %n, i1 false)\n'),
    'runtime_nonzero_fill': (module(runtime_fills(value=7)), 1, 'store i64 506381209866536711', 'i64 %n, i1 false)\n'),
    'seventeen_nonzero_fills': (module(runtime_fills(value=7, count=17)), 0, 'call void @llvm.memset.p0.i64(ptr %p, i8 7', 'smallzero'),
    'x86': (module(runtime_fills(), triple='x86_64-apple-macosx14.0.0'), 0, 'call void @llvm.memset.p0.i64(ptr %p', 'smallzero'),
    'big_endian_target': (module(runtime_fills(), triple='aarch64_be-unknown-linux-gnu').replace('target datalayout = "e-', 'target datalayout = "E-'), 0, 'call void @llvm.memset.p0', 'smallzero'),
    'helper_already_present': (module(runtime_fills()) + 'define void @__elisacore_smallzero_fill() { ret void }\n', 0, 'call void @llvm.memset.p0.i64(ptr %p', 'store i128'),
}

if __name__ == '__main__':
    for name, (ir, want, expected, unexpected) in CASES.items():
        got, result = run_pass('small-fills', ir)
        assert got == want, (name, got, result)
        assert expected in result, (name, expected, result)
        assert unexpected not in result, (name, unexpected, result)
        print('PASS', name)
