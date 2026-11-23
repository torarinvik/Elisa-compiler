#!/usr/bin/env python3
"""Verify that remainder tests rebuilt from a quotient select as msub and cbz.

`X == (X / D) * D` (what the optimizer makes of `X % D == 0` next to `X / D`)
is rewritten to `X - (X / D) * D == 0`, which AArch64 selects as `msub` and
`cbz` instead of `mul`, `cmp` and `b.eq`. A product with another use, and a
comparison other than equality, are left alone.
"""
import os, shlex, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=60)


def flags(*arguments):
    return shlex.split(run([CONFIG, *arguments]).stdout)


DRIVER = r'''#include <llvm/IRReader/IRReader.h>
#include <llvm/Support/SourceMgr.h>
#include <llvm/IR/Verifier.h>
#include "llvm_remainder_tests.cpp"
using namespace llvm;
int main(int Count, char **Arguments) {
  LLVMContext Context;
  SMDiagnostic Error;
  auto Module = parseIRFile(Arguments[1], Error, Context);
  if (!Module) { Error.print(Arguments[0], errs()); return 2; }
  unsigned Changed = ElisaRemainderTests::subtractRemainderTests(*Module);
  if (verifyModule(*Module, &errs())) return 3;
  errs() << Changed << "\n";
  Module->print(outs(), nullptr);
}
'''

DIVIDES = '''target triple = "arm64-apple-macosx14.0.0"
define i64 @divide_out(i64 %start, i64 %factor) {
entry:
  br label %loop
loop:
  %value = phi i64 [ %start, %entry ], [ %quotient, %loop ]
  %quotient = sdiv i64 %value, %factor
  %product = mul i64 %quotient, %factor
  %divides = icmp eq i64 %value, %product
  br i1 %divides, label %loop, label %exit
exit:
  ret i64 %value
}
'''

CASES = {
    'divides': (DIVIDES, 1, True),
    'product_on_left': (DIVIDES.replace('icmp eq i64 %value, %product', 'icmp eq i64 %product, %value'), 1, True),
    'not_divides': (DIVIDES.replace('icmp eq', 'icmp ne').replace('label %loop, label %exit', 'label %exit, label %loop'), 1, True),
    # The product is returned too, so it stays a multiplication.
    'shared_product': (DIVIDES.replace('ret i64 %value', 'ret i64 %product'), 0, False),
    'ordered_compare': (DIVIDES.replace('icmp eq', 'icmp slt'), 0, False),
}

with tempfile.TemporaryDirectory(prefix='remainder-tests-') as temporary:
    directory = Path(temporary)
    (directory / 'driver.cpp').write_text(DRIVER)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    run([bindir / 'clang++', *flags('--cxxflags'), '-I' + str(ROOT / 'src/backend'), directory / 'driver.cpp',
         *flags('--ldflags', '--libs', '--system-libs'), '-Wl,-rpath,' + run([CONFIG, '--libdir']).stdout.strip(),
         '-o', directory / 'driver'])
    for name, (source, want, msub) in CASES.items():
        (directory / 'input.ll').write_text(source)
        result = run([directory / 'driver', directory / 'input.ll'])
        assert int(result.stderr.split()[-1]) == want, (name, result.stderr)
        (directory / 'output.ll').write_text(result.stdout)
        assembly = run([bindir / 'llc', '-O3', directory / 'output.ll', '-o', '-']).stdout
        assert ('msub' in assembly) == msub, (name, assembly)
        assert ('cbz' in assembly or 'cbnz' in assembly) == msub, (name, assembly)
        print('PASS', name)
