#!/usr/bin/env python3
"""Execute the modelable stage0 lockstep-oracle subset.

Reference and target bodies are assembled independently with llvm-mc, then called from a small
C harness over deterministic scalar vectors. The supported gate is intentionally explicit: leaf
x86_64 bodies, unchanged stack/return control, at most one HostPtr input, and locally-structured
conditional branches whose flags come directly from cmp/test. Unsupported bodies produce a
structured ``skip`` result instead of being treated as equivalent.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tempfile

REGS = {"rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp", "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"}
HEADER = re.compile(r"^export\s+def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\).*->\s*([^\s]+)")


def operands(text: str) -> list[str]:
    pieces = text.split(None, 1)
    return [part.strip() for part in pieces[1].split(",")] if len(pieces) == 2 else []


def register_after_equals(text: str) -> str | None:
    if "=" not in text:
        return None
    value = text.split("=", 1)[1].strip().lstrip("%").lower()
    return value if value in REGS else None


def parse_source(source: str) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    section: str | None = None
    for raw in source.splitlines():
        text = raw.split("#", 1)[0].strip()
        match = HEADER.match(text)
        if match:
            if current and current.get("reference") and current.get("target"):
                found.append(current)
            params = []
            for item in match.group(2).split(","):
                item = item.strip()
                if not item:
                    continue
                name, _, typ = item.partition(":")
                params.append((name.strip(), typ.strip()))
            current = {"name": match.group(1), "params": params, "return": match.group(3), "inputs": [], "outputs": [], "stack": [], "control": [], "reference": [], "target": []}
            section = None
            continue
        if current is None:
            continue
        if text.startswith("inputs:"):
            section = "inputs"
            continue
        if text.startswith("outputs:"):
            section = "outputs"
            continue
        if text.startswith("stack:"):
            section = "stack"
            continue
        if text.startswith("control:"):
            section = "control"
            continue
        if text == "reference:":
            section = "reference"
            continue
        if text.startswith("target ") and " lockstep " in text:
            section = "target"
            continue
        if section in {"reference", "target"} and text.endswith(":"):
            current[section].append(text)
            continue
        if text.endswith(":"):
            section = None
            continue
        if section == "inputs" and "=" in text:
            current["inputs"].extend(item.strip() for item in text.split(",") if item.strip())
        elif section == "outputs" and "=" in text:
            current["outputs"].extend(item.strip().split("=")[-1].strip().lstrip("%") for item in text.split(","))
        elif section in {"stack", "control"} and text:
            current[section].extend(item.strip() for item in text.split(",") if item.strip())
        elif section in {"reference", "target"} and text:
            current[section].append(text)
    if current and current.get("reference") and current.get("target"):
        found.append(current)
    return found


def gate(pair: dict[str, object]) -> str | None:
    if "unchanged" not in {str(x).strip().lower() for x in pair["stack"]}:
        return "stack contract is not unchanged"
    if "returns" not in {str(x).strip().lower() for x in pair["control"]}:
        return "control contract is not returns"
    ptr_count = 0
    params = dict(pair["params"])
    for binding in pair["inputs"]:
        reg = register_after_equals(binding)
        name = binding.split("=", 1)[0].strip()
        if not reg:
            return f"input binding {binding!r} is not a concrete x86_64 GPR"
        if name not in params:
            return f"input binding {binding!r} names no signature parameter"
        if params[name].strip().startswith("HostPtr["):
            ptr_count += 1
    if ptr_count > 1:
        return "more than one HostPtr input"
    for body_name in ("reference", "target"):
        flags_live = False
        for raw in pair[body_name]:
            op = raw.split(None, 1)[0].lower()
            if op in {"call", "callq", "rdtsc", "cpuid", "pause", "lfence", "mrs", "isb", "syscall", "sysenter"}:
                return f"{body_name} contains non-leaf or ambient-side-effect instruction {op!r}"
            if op.startswith("j") and op not in {"jmp", "jmpq"}:
                if op not in {"je", "jz", "jne", "jnz", "jl", "jle", "jg", "jge", "jb", "jbe", "ja", "jae", "js", "jns", "jo", "jno"}:
                    return f"{body_name} contains unsupported conditional control flow {op!r}"
                if not flags_live:
                    return f"{body_name} branches on flags not established by cmp/test"
                branch_args = operands(raw)
                if len(branch_args) != 1 or branch_args[0].startswith("*") or branch_args[0].startswith("%"):
                    return f"{body_name} contains an indirect conditional branch"
                continue
            if op in {"jmp", "jmpq"}:
                return f"{body_name} contains non-local control transfer {op!r}"
            if op in {"cmp", "cmpq", "test", "testq"}:
                flags_live = True
            elif op not in {"label"} and (op.startswith(("add", "sub", "and", "or", "xor", "inc", "dec", "neg", "shl", "shr", "sal", "sar"))):
                flags_live = False
            lower = raw.lower()
            if "%fs:" in lower or "%gs:" in lower:
                return f"{body_name} contains segment memory access"
            for operand in operands(raw):
                if "(" not in operand:
                    continue
                base = re.search(r"\(%([a-z0-9]+)\)", operand.lower())
                ptr_regs = {register_after_equals(x) for x in pair["inputs"] if dict(pair["params"]).get(x.split("=", 1)[0].strip(), "").strip().startswith("HostPtr[")}
                if not base or base.group(1) not in ptr_regs:
                    return f"{body_name} contains memory operand {operand!r} whose base is not the HostPtr input"
                if "," in operand:
                    return f"{body_name} contains indexed memory addressing, which is outside the oracle gate"
    return None


def asm_object(llvm_mc: str, directory: pathlib.Path, symbol: str, body: list[str]) -> pathlib.Path:
    leading = "_" if platform.system() == "Darwin" else ""
    asm = ".text\n.globl " + leading + symbol + "\n" + leading + symbol + ":\n" + "".join("\t" + line + "\n" for line in body if line.strip())
    source = directory / f"{symbol}.s"
    output = directory / f"{symbol}.o"
    source.write_text(asm, encoding="utf-8")
    triple = "x86_64-apple-darwin" if platform.system() == "Darwin" else "x86_64-pc-linux-gnu"
    command = [llvm_mc, "--assemble", "--filetype=obj", f"--triple={triple}", "-o", str(output), str(source)]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode:
        raise RuntimeError(f"llvm-mc failed: {completed.stderr.decode().strip()}")
    return output


def c_harness(pair: dict[str, object]) -> str:
    leading = "_" if platform.system() == "Darwin" else ""
    params = pair["params"]
    count = len(pair["inputs"])
    args = ", ".join("uint64_t" for _ in range(count)) or "void"
    values = []
    for index, binding in enumerate(pair["inputs"]):
        name = binding.split("=", 1)[0].strip()
        typ = dict(params).get(name, "")
        values.append("(uint64_t)buf" if typ.strip().startswith("HostPtr[") else f"vectors[i][{index}]" )
    call = ", ".join(values)
    return f'''#include <stdint.h>\n#include <stdio.h>\n#include <string.h>\nextern uint64_t {pair["name"]}_reference({args}) asm("{leading}{pair["name"]}_reference");\nextern uint64_t {pair["name"]}_target({args}) asm("{leading}{pair["name"]}_target");\nstatic const uint64_t vectors[8][8] = {{\n  {{0,1,2,3,4,5,6,7}},\n  {{UINT64_MAX,0x8000000000000000ULL,0x0123456789abcdefULL,7,9,11,13,15}},\n  {{0xaaaaaaaa55555555ULL,0xfedcba9876543210ULL,19,23,29,31,37,41}},\n  {{1,1,1,1,1,1,1,1}},\n  {{0xffff0000ffff0000ULL,0x0000ffff0000ffffULL,3,5,7,11,13,17}},\n  {{0x7fffffffffffffffULL,0x8000000000000000ULL,2,4,6,8,10,12}},\n  {{0xdeadbeefdeadbeefULL,0xcafebabecafebabeULL,43,47,53,59,61,67}},\n  {{0,UINT64_MAX,71,73,79,83,89,97}}\n}};\nint main(void) {{\n  for (unsigned i=0; i<8; ++i) {{\n    unsigned char ref_mem[128], target_mem[128];\n    for (unsigned j=0; j<sizeof(ref_mem); ++j) ref_mem[j] = target_mem[j] = (unsigned char)(0xa5u ^ (i*17u+j*29u));\n    unsigned char *buf = ref_mem;\n    uint64_t rr = {pair["name"]}_reference({call});\n    buf = target_mem;\n    uint64_t tr = {pair["name"]}_target({call});\n    (void)rr; (void)tr;\n    if (rr != tr || memcmp(ref_mem, target_mem, sizeof(ref_mem)) != 0) {{ fprintf(stderr, "lockstep-divergence vector=%u\\n", i); return 1; }}\n  }}\n  return 0;\n}}\n'''


def run(pair: dict[str, object], llvm_mc: str, clang: str) -> dict[str, object]:
    reason = gate(pair)
    if reason:
        return {"name": pair["name"], "status": "skip", "reason": reason}
    with tempfile.TemporaryDirectory(prefix="elisa-easm-oracle-") as temporary:
        directory = pathlib.Path(temporary)
        try:
            reference = asm_object(llvm_mc, directory, f"{pair['name']}_reference", pair["reference"])
            target = asm_object(llvm_mc, directory, f"{pair['name']}_target", pair["target"])
            c_path = directory / "oracle.c"
            executable = directory / "oracle"
            c_path.write_text(c_harness(pair), encoding="utf-8")
            command = [clang]
            if platform.system() == "Darwin":
                command.extend(["-arch", "x86_64"])
            command.extend([str(c_path), str(reference), str(target), "-o", str(executable)])
            linked = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if linked.returncode:
                return {"name": pair["name"], "status": "skip", "reason": f"link failed: {linked.stderr.decode().strip()}"}
            executed = subprocess.run([str(executable)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if executed.returncode:
                return {"name": pair["name"], "status": "diverged", "reason": executed.stderr.decode().strip() or "oracle executable failed"}
            return {"name": pair["name"], "status": "proved"}
        except (OSError, RuntimeError) as error:
            return {"name": pair["name"], "status": "skip", "reason": str(error)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=pathlib.Path)
    parser.add_argument("--llvm-mc", default=shutil.which("llvm-mc"))
    parser.add_argument("--clang", default=shutil.which("clang") or shutil.which("clang++"))
    args = parser.parse_args()
    if not args.llvm_mc or not args.clang:
        json.dump({"results": [{"status": "skip", "reason": "llvm-mc and clang not found"}]}, sys.stdout, separators=(",", ":"))
        sys.stdout.write("\n")
        return 0
    results = [run(pair, args.llvm_mc, args.clang) for pair in parse_source(args.source.read_text(encoding="utf-8"))]
    json.dump({"results": results}, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 1 if any(item["status"] == "diverged" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
