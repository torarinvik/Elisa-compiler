#!/usr/bin/env python3
"""Check hash vectors, its inverse, and erasure of production proof witnesses."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
COMPILER = os.environ.get("ELISACORE_BIN", str(ROOT / "../../Go projects/Elisa-core/compiler/bin/elisac"))


def run(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"30-second timeout: {command[0]}")
    if result.returncode:
        raise SystemExit(f"command failed ({result.returncode}): {command[0]}\n{result.stdout}{result.stderr}")
    return result.stdout


def reference(value):
    mask = (1 << 64) - 1
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & mask
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & mask
    return value ^ (value >> 31)


production = (ROOT / "elisacore_std/collections.elisa").read_text()
start = production.index("const CTX_HASH_U64_INV_MUL_1")
end = production.index("# Open-addressing probe", start)
source = production[start:end] + "\ndef main() -> i64:\n"
values = (0, 1, 2, 255, 1 << 31, 1 << 32, 1 << 63,
          (1 << 63) - 1, (1 << 64) - 2, (1 << 64) - 1,
          0x123456789ABCDEF0, 0xFEDCBA9876543210)
for index, value in enumerate(values):
    source += f"    value_{index}: u64 = 0x{value:x}\n"
    source += f"    expected_{index}: u64 = 0x{reference(value):x}\n"
    source += f"    hash_{index}: u64 = ctx_hash_u64(value_{index})\n"
    source += f"    return {2 * index + 1} if hash_{index} != expected_{index}\n"
    source += f"    return {2 * index + 2} if ctx_unhash_u64(hash_{index}) != value_{index}\n"
source += "    return 0\n"

with tempfile.TemporaryDirectory(prefix="elisa-scalar-hash-") as directory:
    work = Path(directory)
    path, ir, obj, binary = (work / name for name in ("probe.elisa", "probe.ll", "probe.o", "probe"))
    path.write_text(source)
    run([COMPILER, "-strict", "-emit", "llvm", "-O0", "-o", str(ir), str(path)])
    match = re.search(r"(?ms)^define[^\n]*@ctx_hash_u64\([^\n]*\).*?^}", ir.read_text())
    if match is None:
        raise SystemExit("missing production ctx_hash_u64 LLVM function")
    # A remaining call may enforce the public inverse postcondition. The
    # implementation's proof-witness calls must disappear even without LLVM optimization.
    inverse_calls = re.findall(r"call[^\n]*@ctx_unhash", match[0])
    if len(inverse_calls) > 1:
        raise SystemExit(f"hash still executes proof witnesses: {len(inverse_calls)} inverse calls")
    # The hash rounds need three shifts, three XORs, and two multiplications.
    # Count the actual operations too, so an inverse witness expanded inline
    # cannot evade the helper-call check above.
    for opcode, expected in (("lshr", 3), ("xor", 3), ("mul", 2)):
        operations = re.findall(rf"(?m)^\s*%[^=\n]+ = {opcode} i64\b", match[0])
        if len(operations) != expected:
            raise SystemExit(
                f"hash IR has {len(operations)} {opcode} operations; expected {expected}"
            )
    hooks = work / "hooks.c"
    hooks.write_text(run(["bash", str(ROOT / "scripts/write_profiler_hook_fallbacks.sh")]))
    link_flags = ["-Wl,-dead_strip"] if sys.platform == "darwin" else ["-Wl,--gc-sections"]
    run(["clang", "-Wno-override-module", "-x", "ir", "-c", str(ir), "-o", str(obj)])
    run(["clang", *link_flags, "-o", str(binary), str(obj), str(hooks)])
    run([str(binary)])
    print(f"scalar hash: {len(values)} native vectors and inverses pass; proof witnesses erased")
