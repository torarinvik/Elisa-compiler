#!/usr/bin/env python3
"""Verify per-iteration covered-array rewrites and unsafe control-flow cases.

Each case runs through `elisac llvm-pass covered-array-initializers`.
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from elisa_llvm_pass import run_pass


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

for name, (ir, expected) in cases.items():
    result, _ = run_pass("covered-array-initializers", ir)
    if result != expected:
        raise AssertionError((name, result, expected))
    print("PASS", name)
