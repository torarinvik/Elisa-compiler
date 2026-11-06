#!/usr/bin/env python3
"""Verify per-iteration covered-array rewrites and unsafe control-flow cases."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CONFIG = os.environ.get("LLVM_CONFIG", "/opt/homebrew/opt/llvm@23/bin/llvm-config")


def run(command):
    return subprocess.run(command, capture_output=True, text=True, check=True, timeout=28)


def flags(*args):
    return shlex.split(run([CONFIG, *args]).stdout)


DRIVER = r'''#include <llvm/IRReader/IRReader.h>
#include <llvm/Support/SourceMgr.h>
#include <llvm/IR/Module.h>
#include <llvm/IR/Verifier.h>
#include <llvm/IR/InstIterator.h>
#include <llvm/IR/IntrinsicInst.h>
#include <llvm/Analysis/LoopInfo.h>
#include <llvm/Analysis/CFG.h>
#include <llvm/IR/Dominators.h>
#include <llvm/Passes/PassBuilder.h>
#include <llvm/ADT/SmallPtrSet.h>
#include <map>
using namespace llvm;
#include "llvm_array_coverage.h"
int main(int argc, char **argv) {
  if (argc != 2) return 1;
  LLVMContext C; SMDiagnostic E;
  auto M = parseIRFile(argv[1], E, C);
  if (!M) { E.print(argv[0], errs()); return 2; }
  if (verifyModule(*M, &errs())) return 3;
  PassBuilder PB; LoopAnalysisManager LAM; FunctionAnalysisManager FAM;
  CGSCCAnalysisManager CGAM; ModuleAnalysisManager MAM;
  PB.registerModuleAnalyses(MAM); PB.registerCGSCCAnalyses(CGAM);
  PB.registerFunctionAnalyses(FAM); PB.registerLoopAnalyses(LAM);
  PB.crossRegisterProxies(LAM, FAM, CGAM, MAM);
  outs() << prepareCoveredArrayInitializers(*M, FAM, PB) << "\n";
  if (verifyModule(*M, &errs())) return 4;
  return 0;
}
'''


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError(f"fixture pattern changed: {before!r}")
    return text.replace(before, after, 1)


base = (ROOT / "test/fixtures/covered_array_nested_iterations.ll").read_text()
base = base.replace("arm64-apple-darwin", os.environ.get("ELISA_TEST_TRIPLE", "arm64-apple-darwin"))
bypass = replace_once(base, "br i1 %parent.cond, label %writer.pre, label %exit",
                      "br i1 %parent.cond, label %choose, label %exit\nchoose:\n br i1 %skip, label %reader.pre, label %writer.pre")
bound = replace_once(base, "%wcond = icmp ult i64 %wi, %n", "%wcond = icmp ult i64 %wi, %rounds")
start = replace_once(base, "%wi = phi i64 [0, %writer.pre]", "%wi = phi i64 [1, %writer.pre]")
stride = replace_once(base, "%wnext = add i64 %wi, 1", "%wnext = add i64 %wi, 2")
volatile = replace_once(base, "%v = load double, ptr %rp", "%v = load volatile double, ptr %rp")
escape = replace_once(base, " br label %parent\nparent:", " call void @escape(ptr %array)\n br label %parent\nparent:") + "\ndeclare void @escape(ptr)\n"
old_store = " store double %value, ptr %wp, align 8\n %wnext = add i64 %wi, 1\n br label %writer"
skipped = replace_once(base, old_store, " br i1 %skip, label %after.store, label %do.store\ndo.store:\n store double %value, ptr %wp, align 8\n br label %after.store\nafter.store:\n %wnext = add i64 %wi, 1\n br label %writer")
skipped = replace_once(skipped, "[%wnext, %writer.body]", "[%wnext, %after.store]")
early = replace_once(base, old_store, " br i1 %skip, label %reader.pre, label %do.store\ndo.store:\n store double %value, ptr %wp, align 8\n %wnext = add i64 %wi, 1\n br label %writer")
early = replace_once(early, "[%wnext, %writer.body]", "[%wnext, %do.store]")
cases = {"covered": (base, 1), "parent_bypass": (bypass, 0), "different_bound": (bound, 0),
         "nonzero_start": (start, 0), "stride_two": (stride, 0), "volatile_read": (volatile, 0),
         "escaped_array": (escape, 0), "skipped_store": (skipped, 0), "early_exit": (early, 0)}

with tempfile.TemporaryDirectory(prefix="covered-array-nested-") as tmp:
    d = Path(tmp)
    (d / "driver.cpp").write_text(DRIVER)
    clang = Path(run([CONFIG, "--bindir"]).stdout.strip()) / "clang++"
    run([str(clang), *flags("--cxxflags"), "-I" + str(ROOT / "src/backend"), str(d / "driver.cpp"),
         *flags("--ldflags", "--libs", "core", "irreader", "passes", "analysis", "--system-libs"),
         "-Wl,-rpath," + run([CONFIG, "--libdir"]).stdout.strip(), "-o", str(d / "driver")])
    for name, (ir, expected) in cases.items():
        path = d / (name + ".ll")
        path.write_text(ir)
        result = int(run([str(d / "driver"), str(path)]).stdout.strip())
        if result != expected:
            raise AssertionError((name, result, expected))
        print("PASS", name)
