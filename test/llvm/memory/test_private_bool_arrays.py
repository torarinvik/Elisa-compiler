#!/usr/bin/env python3
"""Check the private Boolean-array packing.

A small entry-block `i1` array used only through GEPs, simple loads and stores, zero
fills (whole or partial) and lifetime markers becomes an integer word, then SROA and
instcombine promote it: no array alloca is left. An escaping pointer, a volatile access
or a non-AArch64 target leaves the array alone.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elisa_llvm_pass import run_pass

ARM64 = 'target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"\ntarget triple = "arm64-apple-macosx14.0.0"\n'
X86 = 'target datalayout = "e-m:e-i64:64-i128:128-n8:16:32:64-S128"\ntarget triple = "x86_64-unknown-linux-gnu"\n'


def flags(length=8, initialize='  call void @llvm.memset.p0.i64(ptr %flags, i8 0, i64 LENGTH, i1 false)\n',
          extra='', load='load i1, ptr %q, align 1', target=ARM64):
    body = initialize.replace('LENGTH', str(length))
    return target + f'''declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)
declare void @llvm.lifetime.start.p0(ptr)
declare void @llvm.lifetime.end.p0(ptr)
declare void @observe(ptr)
define i1 @flags(i64 %i, i64 %j, i1 %v) nounwind {{
entry:
  %flags = alloca [{length} x i1], align 1
  call void @llvm.lifetime.start.p0(ptr %flags)
{body}  %p = getelementptr [{length} x i1], ptr %flags, i64 0, i64 %i
  store i1 %v, ptr %p, align 1
{extra}  %q = getelementptr i1, ptr %flags, i64 %j
  %r = {load}
  call void @llvm.lifetime.end.p0(ptr %flags)
  ret i1 %r
}}
'''


# name: (module, changes)
CASES = {
    'byte_flags': (flags(), 1),
    'wide_flags': (flags(length=100), 1),
    'partial_fill': (flags(initialize='  %third = getelementptr i8, ptr %flags, i64 2\n'
                                      '  call void @llvm.memset.p0.i64(ptr %third, i8 0, i64 3, i1 false)\n'), 1),
    'whole_zero_store': (flags(initialize='  store i64 0, ptr %flags, align 1\n'), 1),
    'escaping': (flags(extra='  call void @observe(ptr %flags)\n'), 0),
    'volatile_load': (flags(load='load volatile i1, ptr %q, align 1'), 0),
    'x86': (flags(target=X86), 0),
}

if __name__ == '__main__':
    for name, (ir, want) in CASES.items():
        got, module = run_pass('private-bool-arrays', ir)
        assert got == want, (name, got, module)
        assert ('alloca [' in module) == (not want), (name, module)
        print('PASS', name)
