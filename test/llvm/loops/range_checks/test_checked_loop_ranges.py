#!/usr/bin/env python3
"""Verify loop-carried ranges in the signed-check prover and its rejections.

A sum of one bounded term per iteration of a loop counted to a guarded limit,
and a stack top pushed below a capacity and popped above zero, make checked
arithmetic over them provably safe. The stack's top scaled by 2e16 fits only
under its capacity of 256, not under the 512 pushes the loop could make.
Euler's totient divides `remaining` by its factors and takes `result -
result / factor`: both only shrink from a nonnegative start, and the counter
`factor` is bounded by the guard `factor <= remaining / factor`. Each
negative removes the fact a proof needs, and the check must stay.
"""
import os, shlex, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')
TRIPLE = os.environ.get('ELISA_TEST_TRIPLE', 'arm64-apple-darwin')


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=60)


def flags(*arguments):
    return shlex.split(run([CONFIG, *arguments]).stdout)


DRIVER = r'''#include <llvm/IRReader/IRReader.h>
#include <llvm/Support/SourceMgr.h>
#include <llvm/IR/Verifier.h>
#include <llvm/IR/Dominators.h>
#include <llvm/IR/InstIterator.h>
#include <llvm/IR/IntrinsicInst.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/PatternMatch.h>
#include <llvm/IR/ConstantRange.h>
#include <llvm/Passes/PassBuilder.h>
#include <llvm/Analysis/AssumptionCache.h>
#include <llvm/Analysis/ValueTracking.h>
#include <llvm/Analysis/LoopInfo.h>
#include <llvm/Analysis/ScalarEvolution.h>
#include <llvm/Analysis/InlineCost.h>
#include <llvm/Transforms/Utils/Cloning.h>
#include <llvm/Target/TargetMachine.h>
using namespace llvm;
#include "llvm_bisection_ranges.h"
#include "llvm_checked_signed_ranges.h"
int main(int Count, char **Arguments) {
  LLVMContext Context;
  SMDiagnostic Error;
  auto Module = parseIRFile(Arguments[1], Error, Context);
  if (!Module) { Error.print(Arguments[0], errs()); return 2; }
  unsigned Folded = foldProvenSignedChecks(*Module, nullptr);
  if (verifyModule(*Module, &errs())) return 3;
  outs() << Folded << "\n";
  Module->print(outs(), nullptr);
}
'''

SUM = '''target triple = "TRIPLE"
declare { i64, i1 } @llvm.sadd.with.overflow.i64(i64, i64)
declare void @llvm.trap()
define i64 @sum(ptr %values, i64 %count) {
entry:
  %large = icmp ugt i64 %count, 1000
  br i1 %large, label %invalid, label %check
check:
  %empty = icmp eq i64 %count, 0
  br i1 %empty, label %invalid, label %loop
loop:
  %index = phi i64 [0, %check], [%next, %latch]
  %total = phi i64 [0, %check], [%added, %latch]
  %address = getelementptr i64, ptr %values, i64 %index
  %value = load i64, ptr %address, !range !0
  %pair = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %total, i64 %value)
  %overflow = extractvalue { i64, i1 } %pair, 1
  br i1 %overflow, label %trap, label %latch
trap:
  call void @llvm.trap()
  unreachable
latch:
  %added = extractvalue { i64, i1 } %pair, 0
  %next = add i64 %index, 1
  %done = icmp eq i64 %next, %count
  br i1 %done, label %exit, label %loop
exit:
  ret i64 %added
invalid:
  ret i64 -1
}
!0 = !{i64 -1000000, i64 1000001}
'''.replace('TRIPLE', TRIPLE)

STACK = '''target triple = "TRIPLE"
declare { i64, i1 } @llvm.smul.with.overflow.i64(i64, i64)
declare void @llvm.trap()
define i64 @stack(ptr %codes, i64 %count) {
entry:
  %large = icmp ugt i64 %count, 512
  br i1 %large, label %invalid, label %check
check:
  %empty = icmp eq i64 %count, 0
  br i1 %empty, label %invalid, label %loop
loop:
  %index = phi i64 [0, %check], [%next, %latch]
  %top = phi i64 [0, %check], [%moved, %latch]
  %address = getelementptr i64, ptr %codes, i64 %index
  %code = load i64, ptr %address
  %push = icmp eq i64 %code, 0
  br i1 %push, label %pushing, label %popping
pushing:
  %full = icmp eq i64 %top, 256
  br i1 %full, label %invalid, label %pushed
pushed:
  %up = add i64 %top, 1
  br label %latch
popping:
  %bottom = icmp eq i64 %top, 0
  br i1 %bottom, label %invalid, label %popped
popped:
  %down = add i64 %top, -1
  br label %latch
latch:
  %moved = phi i64 [%up, %pushed], [%down, %popped]
  %next = add i64 %index, 1
  %done = icmp eq i64 %next, %count
  br i1 %done, label %exit, label %loop
exit:
  %last = phi i64 [%moved, %latch]
  %pair = call { i64, i1 } @llvm.smul.with.overflow.i64(i64 %last, i64 20000000000000000)
  %overflow = extractvalue { i64, i1 } %pair, 1
  br i1 %overflow, label %trap, label %done.exit
trap:
  call void @llvm.trap()
  unreachable
done.exit:
  %scaled = extractvalue { i64, i1 } %pair, 0
  ret i64 %scaled
invalid:
  ret i64 -1
}
'''.replace('TRIPLE', TRIPLE)

TOTIENT = '''target triple = "TRIPLE"
declare { i64, i1 } @llvm.sadd.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.ssub.with.overflow.i64(i64, i64)
declare void @llvm.trap()
define i64 @totient(i64 %argument, i64 %other) {
entry:
  %n = freeze i64 %argument
  %low = icmp slt i64 %n, 1
  br i1 %low, label %invalid, label %check
check:
  %high = icmp sgt i64 %n, 1000000
  br i1 %high, label %invalid, label %head
head:
  %result = phi i64 [ %n, %check ], [ %result.next, %stepped ]
  %remaining = phi i64 [ %n, %check ], [ %remaining.next, %stepped ]
  %factor = phi i64 [ 2, %check ], [ %factor.next, %stepped ]
  %quotient = sdiv i64 %remaining, %factor
  %past = icmp sgt i64 %factor, %quotient
  br i1 %past, label %exit, label %body
body:
  %product = mul i64 %quotient, %factor
  %divides = icmp eq i64 %remaining, %product
  br i1 %divides, label %inner, label %latch
inner:
  %left = phi i64 [ %remaining, %body ], [ %divided, %inner ]
  %divided = sdiv i64 %left, %factor
  %back = mul i64 %divided, %factor
  %again = icmp eq i64 %left, %back
  br i1 %again, label %inner, label %reduce
reduce:
  %share = sdiv i64 %result, %factor
  %pair = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 %result, i64 %share)
  %overflow = extractvalue { i64, i1 } %pair, 1
  br i1 %overflow, label %trap, label %reduced
reduced:
  %smaller = extractvalue { i64, i1 } %pair, 0
  br label %latch
latch:
  %result.next = phi i64 [ %result, %body ], [ %smaller, %reduced ]
  %remaining.next = phi i64 [ %remaining, %body ], [ %left, %reduced ]
  %step = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %factor, i64 1)
  %step.overflow = extractvalue { i64, i1 } %step, 1
  br i1 %step.overflow, label %trap, label %stepped
stepped:
  %factor.next = extractvalue { i64, i1 } %step, 0
  br label %head
exit:
  %rest = icmp sgt i64 %remaining, 1
  br i1 %rest, label %last, label %done
last:
  %last.share = sdiv i64 %result, %remaining
  %last.pair = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 %result, i64 %last.share)
  %last.overflow = extractvalue { i64, i1 } %last.pair, 1
  br i1 %last.overflow, label %trap, label %last.done
last.done:
  %final = extractvalue { i64, i1 } %last.pair, 0
  ret i64 %final
done:
  ret i64 %result
trap:
  call void @llvm.trap()
  unreachable
invalid:
  ret i64 -1
}
'''.replace('TRIPLE', TRIPLE)

CASES = {
    'sum': (SUM, 1),
    'sum_unbounded_count': (SUM.replace('icmp ugt i64 %count, 1000', 'icmp eq i64 %count, 7'), 0),
    'sum_empty_count': (SUM.replace('icmp eq i64 %count, 0', 'icmp eq i64 %count, 5'), 0),
    'sum_large_terms': (SUM.replace('!{i64 -1000000, i64 1000001}', '!{i64 -4611686018427387904, i64 4611686018427387904}'), 0),
    'sum_step_two': (SUM.replace('add i64 %index, 1', 'add i64 %index, 2'), 0),
    'sum_twice': (SUM.replace('%added = extractvalue { i64, i1 } %pair, 0', '%once = extractvalue { i64, i1 } %pair, 0\n  %added = add i64 %once, %value'), 0),
    'stack': (STACK, 1),
    'stack_unguarded_push': (STACK.replace('br i1 %full, label %invalid, label %pushed', 'br label %pushed'), 0),
    'stack_push_two': (STACK.replace('add i64 %top, 1', 'add i64 %top, 2'), 0),
    'stack_wide_capacity': (STACK.replace('icmp eq i64 %top, 256', 'icmp eq i64 %top, 100000'), 0),
    'totient': (TOTIENT, 3),
    # A negative start: the result does not shrink toward zero. The factor
    # still stays below a quotient by at least 2, so its step folds.
    'totient_negative_start': (TOTIENT.replace('br i1 %low, label %invalid, label %check', 'br label %check'), 1),
    # A result that grows: only the factor's guard still bounds its step.
    'totient_growing_result': (TOTIENT.replace('ssub.with.overflow.i64(i64 %result, i64 %share)', 'sadd.with.overflow.i64(i64 %result, i64 %share)'), 1),
    # A divisor that may be -1 negates the remaining value instead of shrinking it.
    'totient_negative_divisor': (TOTIENT.replace('[ 2, %check ]', '[ -1, %check ]'), 0),
    # A guard against an unbounded argument says nothing about the factor.
    'totient_unbounded_guard': (TOTIENT.replace('icmp sgt i64 %factor, %quotient', 'icmp sgt i64 %factor, %other'), 2),
    'non_arm': (SUM.replace(TRIPLE, 'x86_64-unknown-linux-gnu'), 0),
}

with tempfile.TemporaryDirectory(prefix='checked-loop-ranges-') as temporary:
    directory = Path(temporary)
    (directory / 'driver.cpp').write_text(DRIVER)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    run([bindir / 'clang++', *flags('--cxxflags'), '-I' + str(ROOT / 'src/backend'), directory / 'driver.cpp',
         *flags('--ldflags', '--libs', '--system-libs'), '-Wl,-rpath,' + run([CONFIG, '--libdir']).stdout.strip(),
         '-o', directory / 'driver'])
    for name, (source, want) in CASES.items():
        (directory / 'input.ll').write_text(source)
        output = run([directory / 'driver', directory / 'input.ll']).stdout
        got = int(output.splitlines()[0])
        assert got == want, (name, got)
        body = output.split('\n', 1)[1]
        checks = 'call { i64, i1 } @llvm.s'
        assert body.count(checks) == source.count(checks) - want, (name, output)
        # Only the sum's proof uses the guarded count, which it must freeze.
        assert ('freeze i64 %count' in body) == (name == 'sum'), (name, output)
        print('PASS', name)
