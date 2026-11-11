#!/usr/bin/env python3
"""Check conditional subtraction and its recurrence proof boundaries."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CONFIG = os.environ.get("LLVM_CONFIG", "/opt/homebrew/opt/llvm@23/bin/llvm-config")
DRIVER = r"""
#include <llvm-c/Core.h>
#include <llvm/IR/Module.h>
#include <llvm/IR/Verifier.h>
#include <llvm/IRReader/IRReader.h>
#include <llvm/Support/CBindingWrapping.h>
#include <llvm/Support/SourceMgr.h>

extern "C" unsigned elisacoreFoldBoundedRemainders(LLVMModuleRef);

int main(int argc, char **argv) {
  llvm::LLVMContext Context;
  llvm::SMDiagnostic Error;
  auto Module = llvm::parseIRFile(argv[1], Error, Context);
  if (!Module) {
    Error.print(argv[0], llvm::errs());
    return 1;
  }
  llvm::outs() << elisacoreFoldBoundedRemainders(llvm::wrap(Module.get())) << "\n";
  if (llvm::verifyModule(*Module, &llvm::errs()))
    return 2;
  Module->print(llvm::outs(), nullptr);
}
"""
IR = """target triple = "arm64-apple-darwin"
define i64 @recurrence(ptr %data, i64 %length) {
entry:
  %empty = icmp eq i64 %length, 0
  br i1 %empty, label %invalid, label %loop

loop:
  %index = phi i64 [ 0, %entry ], [ %next, %step ]
  %a = phi i64 [ 1, %entry ], [ %a.rem, %step ]
  %b = phi i64 [ 0, %entry ], [ %b.rem, %step ]
  %ptr = getelementptr i64, ptr %data, i64 %index
  %value = load i64, ptr %ptr
  %bad = icmp ugt i64 %value, 96
  br i1 %bad, label %invalid, label %step

step:
  %a.sum = add i64 %a, %value
  %a.rem = srem i64 %a.sum, 97
  %b.sum = add i64 %b, %a.rem
  %b.rem = srem i64 %b.sum, 97
  %next = add i64 %index, 1
  %done = icmp eq i64 %next, %length
  br i1 %done, label %exit, label %loop

exit:
  ret i64 %b.rem

invalid:
  ret i64 -1
}
"""


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=15).stdout


def main():
    bindir = Path(run(CONFIG, "--bindir").strip())
    cxxflags = shlex.split(run(CONFIG, "--cxxflags"))
    libs = shlex.split(run(CONFIG, "--ldflags", "--libs", "--system-libs"))
    cases = [
        ("guarded", IR, 2),
        ("unsigned", IR.replace("srem", "urem"), 2),
        ("mixed", IR.replace("%b.rem = srem", "%b.rem = urem"), 2),
        ("unknown sign", IR.replace("icmp ugt", "icmp sgt"), 0),
        ("undefined seed", IR.replace("[ 1, %entry ]", "[ undef, %entry ]"), 0),
        ("negative seed", IR.replace("[ 1, %entry ]", "[ -1, %entry ]"), 0),
        ("wide dividend", IR.replace("%value, 96", "%value, 98"), 1),
        ("guard bypass", IR.replace("label %invalid, label %step", "label %step, label %invalid"), 0),
    ]
    with tempfile.TemporaryDirectory(prefix="bounded-remainder-") as tmp:
        directory = Path(tmp)
        driver = directory / "driver.cpp"
        driver.write_text(DRIVER)
        executable = directory / "driver"
        source = ROOT / "src/backend/llvm_bounded_remainder.cpp"
        run(bindir / "clang++", *cxxflags, driver, source, *libs, "-o", executable)
        fixture = directory / "fixture.ll"
        for name, ir, expected in cases:
            fixture.write_text(ir)
            count, rewritten = run(executable, fixture).split("\n", 1)
            assert int(count) == expected, (name, count, expected)
            assert ("freeze i64 %value" in rewritten) == bool(expected), name
            assert rewritten.count("srem i64") + rewritten.count("urem i64") == 2 - expected, name
            if name == "wide dividend":
                assert "%a.rem = srem i64" in rewritten, name
            print("PASS", name)


if __name__ == "__main__":
    main()
