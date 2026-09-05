#!/usr/bin/env python3
"""Check raise result-store widths and run native scalar errors at O0/O2."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts/elisac_stage1.sh"
FIXTURE = ROOT / "test/repro/error_result_zero_width.elisa"


def compile_to(mode, optimization, output):
    subprocess.run(
        [str(WRAPPER), "-emit", mode, optimization, "-o", str(output), str(FIXTURE)],
        check=True, text=True, timeout=180,
    )


with tempfile.TemporaryDirectory(prefix="elisa-error-zero-") as directory:
    work = Path(directory)
    ir = work / "errors.ll"
    compile_to("llvm", "-O0", ir)
    text = ir.read_text()
    assert "!elisa.declined" not in text
    for name, llvm_type in (("byte", "i8"), ("short", "i16"), ("flag", "i1"), ("float", "float"), ("void", None)):
        for suffix in ("plain", "payload"):
            function = name + "_" + suffix
            match = re.search(r"^define [^\n]*@" + function + r"\([^\n]*\).*?^}", text, re.M | re.S)
            assert match, function
            stores = re.findall(r"store ([^\n]+), ptr %0(?:,|\n)", match.group())
            if llvm_type is None:
                assert not stores, (function, stores)
            else:
                assert stores, function
                assert all(store.startswith(llvm_type + " ") for store in stores), (function, stores)
    for optimization in ("-O0", "-O2"):
        executable = work / optimization[1:]
        compile_to("exe", optimization, executable)
        # Fresh native executables can wait in the macOS loader before main.
        subprocess.run([str(executable)], check=True, timeout=120)
print("error result zero-width OK: plain/payload stores and native O0/O2")
