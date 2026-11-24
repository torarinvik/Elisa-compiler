#!/usr/bin/env python3
"""Check the short-trip versioning.

A function whose only loop counts from 0 to an argument N, and which zeroes 1 KiB to
8 KiB of static stack, gets a dispatch on its frozen N: N == 1 runs an inlined copy
specialized to one iteration, when that copy drops at least 512 zeroed bytes and is at
most 64 instructions. Other loops, smaller fills, opaque calls, size optimization and
non-AArch64 targets are left alone.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elisa_llvm_pass import run_pass

ARM64 = 'target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"\ntarget triple = "arm64-apple-macosx14.0.0"\n'
X86 = 'target datalayout = "e-m:e-i64:64-i128:128-n8:16:32:64-S128"\ntarget triple = "x86_64-unknown-linux-gnu"\n'


def counted(bytes_zeroed=4096, attributes='nounwind', count='%n', body_extra='', target=ARM64,
            count_type='i64'):
    widen = f'  %wide = zext i32 %next to i64\n' if count_type == 'i32' else ''
    index = '%wide_i' if count_type == 'i32' else '%i'
    widen_index = f'  %wide_i = zext i32 %i to i64\n' if count_type == 'i32' else ''
    return target + f'''declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)
declare void @opaque(ptr)
define i64 @fill({count_type} %n, ptr %out) {attributes} {{
entry:
  %buf = alloca [1024 x i64], align 8
  call void @llvm.memset.p0.i64(ptr %buf, i8 0, i64 {bytes_zeroed}, i1 false)
  br label %loop
loop:
  %i = phi {count_type} [ 0, %entry ], [ %next, %loop ]
{widen_index}  %slot = getelementptr i64, ptr %buf, i64 {index}
  %value = load i64, ptr %slot, align 8
  %bumped = add i64 %value, {index}
  store i64 %bumped, ptr %slot, align 8
{body_extra}  %next = add {count_type} %i, 1
  %done = icmp eq {count_type} %next, {count}
  br i1 %done, label %exit, label %loop
exit:
  %third = getelementptr i64, ptr %buf, i64 3
  %result = load i64, ptr %third, align 8
  ret i64 %result
}}
'''


# name: (module, changes)
CASES = {
    'counted': (counted(), 1),
    'counted_i32': (counted(count_type='i32'), 1),
    'small_fill': (counted(bytes_zeroed=512), 0),
    'loaded_count': (counted(count='%loaded', body_extra='  %loaded = load i64, ptr %out, align 8\n'), 0),
    'opaque_call': (counted(body_extra='  call void @opaque(ptr %buf)\n'), 0),
    'size_optimized': (counted(attributes='nounwind optsize'), 0),
    'may_throw': (counted(attributes=''), 0),
    'x86': (counted(target=X86), 0),
}

if __name__ == '__main__':
    for name, (ir, want) in CASES.items():
        got, module = run_pass('short-trips', ir)
        assert got == want, (name, got, module)
        assert ('short_trip.dispatch' in module) == bool(want), (name, module)
        print('PASS', name)
