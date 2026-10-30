"""Exercise the source-bound Stage1 pass probe; each probe has an external cap."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


IR = '''target triple = "aarch64-unknown-linux-gnu"
define i64 @reduce(i64 %arg) {
entry:
  br label %loop
loop:
  %n = phi i64 [ %arg, %entry ], [ %q, %loop ]
  %sum = phi i64 [ 0, %entry ], [ %next, %loop ]
  %q = udiv i64 %n, 10
  %neg = mul nsw i64 %q, -10
  %inner = add i64 %n, %sum
  %next = add i64 %inner, %neg
  %done = icmp ult i64 %n, 10
  br i1 %done, label %exit, label %loop
exit:
  ret i64 %next
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", type=Path)
    parser.add_argument("--foreign-flag-library", type=Path)
    args = parser.parse_args()
    probe = args.probe.resolve(strict=True)
    timeout = shutil.which("gtimeout") or shutil.which("timeout")
    if timeout is None:
        parser.error("GNU timeout is required")
    positive = {
        "plain": IR,
        "commuted": IR.replace("%n, %sum", "%sum, %n").replace("%inner, %neg", "%neg, %inner"),
        "divisor13": IR.replace("10", "13"),
        "exact": IR.replace("udiv i64", "udiv exact i64"),
        "unsigned_product": IR.replace("mul nsw", "mul nuw"),
        "high_bit_divisor": IR.replace("10", "9223372036854775808"),
        "commuted_product": IR.replace("%q, -10", "-10, %q"),
        "arm64_alias": IR.replace("aarch64-unknown-linux-gnu", "arm64-apple-darwin"),
    }
    negative = {
        "signed_divide": IR.replace("udiv", "sdiv"),
        "inner_nsw": IR.replace("inner = add", "inner = add nsw"),
        "inner_nuw": IR.replace("inner = add", "inner = add nuw"),
        "outer_nsw": IR.replace("next = add", "next = add nsw"),
        "outer_nuw": IR.replace("next = add", "next = add nuw"),
        "wrong_product": IR.replace(", -10", ", -11"),
        "non_phi": IR.replace("%n, %sum", "%n, %arg"),
        "shared_inner": IR.replace("  %done =", "  %extra = add i64 %inner, 1\n  %done ="),
        "x86": IR.replace("aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu"),
        "optnone": IR.replace("@reduce(i64 %arg) {", "@reduce(i64 %arg) noinline optnone {"),
        "zero_divisor": IR.replace("10", "0"),
        "width32": IR.replace("i64", "i32"),
    }
    for should_change, cases in ((True, positive), (False, negative)):
        for name, source in cases.items():
            with tempfile.TemporaryDirectory(prefix="stage1-remainder-") as temporary:
                directory = Path(temporary)
                (directory / "input.ll").write_text(source)
                subprocess.run([timeout, "-k", "0.1s", "29.7s", str(probe)],
                               cwd=directory, check=True)
                before = (directory / "before.ll").read_text()
                after = (directory / "output.ll").read_text()
                if should_change:
                    assert "add i64 %n, %neg" in after, name
                    assert "add i64 %elisa.remainder.grouped, %sum" in after, name
                    for line in before.splitlines():
                        if "%q = udiv" in line or "%neg = mul" in line:
                            assert line in after, f"{name}: arithmetic flags or operands changed"
                else:
                    assert after == before, f"declined case {name} changed"
    print(f"Stage1 remainder grouping: {len(positive)} positive and {len(negative)} decline cases passed")
    if args.foreign_flag_library is not None:
        with tempfile.TemporaryDirectory(prefix="stage1-remainder-foreign-") as temporary:
            directory = Path(temporary)
            (directory / "input.ll").write_text(IR)
            environment = os.environ.copy()
            environment["LD_PRELOAD"] = str(args.foreign_flag_library.resolve(strict=True))
            subprocess.run([timeout, "-k", "0.1s", "29.7s", str(probe)],
                           cwd=directory, env=environment, check=True)
            assert (directory / "before.ll").read_bytes() == (directory / "output.ll").read_bytes()
        print("Foreign LLVM flag API declined without invoking it")


if __name__ == "__main__":
    main()
