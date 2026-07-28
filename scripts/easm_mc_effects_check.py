#!/usr/bin/env python3
"""Cross-check stage1 EASM effect rows against LLVM's MC instruction descriptions."""

from __future__ import annotations

import argparse
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile

WITNESSES = {
    "movq": "movq %rax, %rbx", "movl": "movl %eax, %ecx", "lea": "leaq (%rax), %rbx",
    "leaq": "leaq (%rax), %rbx", "pushq": "pushq %rax", "popq": "popq %rax",
    "xchgq": "xchgq %rax, %rbx", "addq": "addq %rax, %rbx", "subq": "subq %rax, %rbx",
    "andq": "andq %rax, %rbx", "orq": "orq %rax, %rbx", "xorq": "xorq %rax, %rbx",
    "notq": "notq %rax", "negq": "negq %rax", "shlq": "shlq $1, %rax",
    "salq": "salq $1, %rax", "shrq": "shrq $1, %rax", "sarq": "sarq $1, %rax",
    "cmpq": "cmpq %rax, %rbx", "testq": "testq %rax, %rbx", "incq": "incq %rax",
    "decq": "decq %rax", "callq": "callq *%rax", "jmpq": "jmpq *%rax", "retq": "retq",
    "cpuid": "cpuid", "cld": "cld", "std": "std", "lfence": "lfence",
    "rdtsc": "rdtsc", "pause": "pause", "fldcw": "fldcw (%rax)",
    "fnstcw": "fnstcw (%rax)", "stmxcsr": "stmxcsr (%rax)", "ldmxcsr": "ldmxcsr (%rax)",
    "emms": "emms", "vzeroall": "vzeroall", "trap": "ud2",
}
GPR_BITS = {"RAX": 1, "RCX": 2, "RDX": 4, "RBX": 8, "RSI": 16, "RDI": 32,
            "R8": 256, "R9": 512, "R10": 1024, "R11": 2048}
MC_SOURCE = r'''
#include "llvm/MC/MCInstrInfo.h"
#include "llvm/MC/MCRegisterInfo.h"
#include "llvm/MC/TargetRegistry.h"
#include "llvm/Support/TargetSelect.h"
#include <cstdio>
#include <memory>
#include <string>
using namespace llvm;
int main() {
  LLVMInitializeX86TargetInfo(); LLVMInitializeX86TargetMC();
  std::string error; const Target *target = TargetRegistry::lookupTarget("x86_64-apple-darwin", error);
  if (!target) return 2;
  std::unique_ptr<MCInstrInfo> instructions(target->createMCInstrInfo());
  std::unique_ptr<MCRegisterInfo> registers(target->createMCRegInfo("x86_64-apple-darwin"));
  if (!instructions || !registers) return 3;
  for (unsigned i = 0; i < instructions->getNumOpcodes(); ++i) {
    const MCInstrDesc &desc = instructions->get(i);
    std::printf("%s|", instructions->getName(i).str().c_str());
    bool first = true;
    for (MCPhysReg reg : desc.implicit_defs()) { if (!first) std::printf(","); first = false; std::printf("%s", registers->getName(reg)); }
    std::printf("|%d|%d\n", desc.mayLoad(), desc.mayStore());
  }
  return 0;
}
'''


def run(args: argparse.Namespace) -> int:
    llvm_config = args.llvm_config or shutil.which("llvm-config")
    llvm_mc = args.llvm_mc or shutil.which("llvm-mc")
    cxx = args.cxx or shutil.which("clang++")
    if not llvm_config or not llvm_mc or not cxx:
        print("easm_mc_effects_check SKIP: llvm-config, llvm-mc, or clang++ not found")
        return 0
    rows = {}
    for line in subprocess.check_output([str(args.driver)], text=True).splitlines():
        fields = line.split("|")
        if len(fields) != 8:
            raise RuntimeError(f"malformed stage1 effect row: {line!r}")
        rows[fields[0]] = fields[1:]
    with tempfile.TemporaryDirectory(prefix="elisa-mc-effects-") as directory:
        root = pathlib.Path(directory)
        source = root / "probe.cpp"
        binary = root / "probe"
        source.write_text(MC_SOURCE, encoding="utf-8")
        flags = shlex.split(subprocess.check_output([llvm_config, "--cxxflags"], text=True))
        libdir = subprocess.check_output([llvm_config, "--libdir"], text=True).strip()
        command = [cxx, *flags, str(source), "-o", str(binary), f"-L{libdir}", "-lLLVM", f"-Wl,-rpath,{libdir}"]
        probe = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if probe.returncode != 0:
            raise RuntimeError(f"could not compile LLVM MC probe:\n{probe.stderr}")
        mc = {}
        for line in subprocess.check_output([str(binary)], text=True).splitlines():
            name, defs, load, store = line.split("|")
            mc[name] = (set(filter(None, defs.split(","))), load == "1", store == "1")
        checked = 0
        for op, witness in WITNESSES.items():
            output = subprocess.check_output([llvm_mc, "--triple=x86_64-apple-darwin", "--show-inst", "--filetype=asm"], input=witness + "\n", text=True, stderr=subprocess.STDOUT)
            marker = "<MCInst #"
            if marker not in output:
                raise RuntimeError(f"llvm-mc did not expose an opcode for {op}: {output}")
            opcode = output.split(marker, 1)[1].split()[1].rstrip(">")
            defs, _, _ = mc[opcode]
            row = rows[op]
            known, flags, implicit_cc, reads, writes, defined, capability = row
            if known != "1":
                raise RuntimeError(f"stage1 does not know stage0 opcode {op}")
            if ("EFLAGS" in defs or "DF" in defs) and flags != "1" and implicit_cc != "1":
                raise RuntimeError(f"stage1 under-declares flag effects for {op} ({opcode})")
            implicit_gprs = 0
            for name, bit in GPR_BITS.items():
                # MC represents tied explicit operands (notably xchg's first register)
                # in implicit_defs as well; OperationEffect only models implicit state.
                if name in defs and op not in {"callq", "jmpq", "xchgq"}:
                    implicit_gprs |= bit
            if implicit_gprs & ~int(writes):
                raise RuntimeError(f"stage1 under-declares implicit GPR effects for {op}: MC={implicit_gprs} stage1={writes}")
            if any(name in defs for name in {"FPSW", "FPCW", "MXCSR"}) and not capability:
                raise RuntimeError(f"stage1 leaves FPU state effect ungated for {op}")
            checked += 1
    print(f"easm_mc_effects_check OK: {checked} LLVM-MC witnesses cross-checked")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", required=True, type=pathlib.Path)
    parser.add_argument("--llvm-config")
    parser.add_argument("--llvm-mc")
    parser.add_argument("--cxx")
    raise SystemExit(run(parser.parse_args()))
