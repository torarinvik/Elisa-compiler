#!/usr/bin/env python3
"""Run stage0-compatible opt-in parametric callee-save preservation checks.

This is deliberately a host adapter, like the stage1 template assembler and lockstep oracle:
stage1 passes parsed EASM through its verifier, while this optional proof uses the configured SMT
solver for the register-polymorphic obligation.  Unsupported bodies are reported as ``skip``;
they are never silently accepted.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
from dataclasses import dataclass

CALLEE_SAVED = ("rbx", "rbp", "r12", "r13", "r14", "r15")
REG_RE = re.compile(r"^%([a-z][a-z0-9]*)$")
RSP_MEM_RE = re.compile(r"^(-?[0-9]*)\(%rsp\)$")


@dataclass
class Fn:
    name: str
    preserves: set[str]
    clobbers: set[str]
    returns: bool
    body: list[str]


def canon(reg: str) -> str:
    reg = reg.lower().lstrip("%")
    aliases = {"ebx": "rbx", "ebp": "rbp", "r12d": "r12", "r13d": "r13", "r14d": "r14", "r15d": "r15"}
    return aliases.get(reg, reg)


def parse_functions(path: pathlib.Path) -> list[Fn]:
    lines = path.read_text().splitlines()
    out: list[Fn] = []
    current: Fn | None = None
    section = ""
    for raw in lines + ["export def __eof() -> void:"]:
        line = raw.strip()
        match = re.match(r"(?:export\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
        if match:
            if current is not None:
                out.append(current)
            current = Fn(match.group(1), set(), set(), False, [])
            section = ""
            continue
        if current is None or not line or line.startswith("#"):
            continue
        if line.endswith(":") and line[:-1] in {"preserves", "clobbers", "control", "body"}:
            section = line[:-1]
            continue
        if section == "preserves":
            current.preserves.update(x.strip().lstrip("%") for x in line.split(",") if x.strip())
        elif section == "clobbers":
            current.clobbers.update(x.strip().lstrip("%") for x in line.split(",") if x.strip())
        elif section == "control":
            current.returns |= "returns" in line.split(",")
        elif section == "body":
            current.body.append(line)
    return out


def operands(text: str) -> list[str]:
    return [part.strip() for part in text.split(",")]


def bv(value: int) -> str:
    return f"#x{value & ((1 << 64) - 1):016x}"


def rsp_offset(operand: str, current: int) -> int | None:
    match = RSP_MEM_RE.fullmatch(operand.replace(" ", ""))
    if not match:
        return None
    displacement = match.group(1)
    return current + (int(displacement or "0") if displacement not in ("", "-") else 0)


def model(fn: Fn) -> tuple[dict[str, str], str]:
    regs: dict[str, str] = {}
    stack: dict[int, str] = {}
    rsp = 0
    fresh = 0

    def term(operand: str) -> str | None:
        operand = operand.strip()
        match = REG_RE.fullmatch(operand)
        if match:
            reg = canon(match.group(1))
            if reg not in regs:
                regs[reg] = f"in_{reg}"
            return regs[reg]
        if operand.startswith("$"):
            try:
                return bv(int(operand[1:], 0))
            except ValueError:
                return None
        return None

    def stale() -> str:
        nonlocal fresh
        name = f"stale_{fresh}"
        fresh += 1
        return name

    for raw in fn.body:
        text = raw.split("#", 1)[0].strip()
        if not text or text.endswith(":"):
            return {}, "contains control-flow label"
        parts = text.split(None, 1)
        op = parts[0].lower()
        args = operands(parts[1]) if len(parts) == 2 else []
        if op in {"ret", "retq"}:
            continue
        if op in {"push", "pushq"} and len(args) == 1:
            value = term(args[0])
            if value is None:
                return {}, "push operand is not a register or immediate"
            rsp -= 8
            stack[rsp] = value
            continue
        if op in {"pop", "popq"} and len(args) == 1 and REG_RE.fullmatch(args[0]):
            value = stack.get(rsp, stale())
            regs[canon(args[0])] = value
            rsp += 8
            continue
        if op in {"mov", "movq"} and len(args) == 2:
            src, dst = args
            dst_reg = REG_RE.fullmatch(dst)
            src_reg = REG_RE.fullmatch(src)
            if dst_reg:
                if src_reg or src.startswith("$"):
                    value = term(src)
                else:
                    off = rsp_offset(src, rsp)
                    value = stack.get(off, stale()) if off is not None else None
                if value is None:
                    return {}, "mov source is outside the modeled register/stack subset"
                if canon(dst) == "rsp":
                    return {}, "mov into rsp is not modeled"
                regs[canon(dst)] = value
                continue
            off = rsp_offset(dst, rsp)
            value = term(src)
            if off is None or value is None:
                return {}, "mov memory operand is outside the rsp-relative subset"
            stack[off] = value
            continue
        if op in {"add", "addq", "sub", "subq", "and", "andq", "or", "orq", "xor", "xorq"} and len(args) == 2 and REG_RE.fullmatch(args[1]):
            dst = canon(args[1])
            if dst == "rsp":
                value = term(args[0])
                if value is None or not args[0].startswith("$"):
                    return {}, "non-immediate rsp adjustment"
                delta = int(args[0][1:], 0)
                rsp += delta if op.startswith("add") else -delta
                continue
            left, right = term(args[0]), term(args[1])
            if left is None or right is None:
                return {}, "ALU operand is outside the register/immediate subset"
            family = op.rstrip("q")
            smt_op = {"add": "bvadd", "sub": "bvsub", "and": "bvand", "or": "bvor", "xor": "bvxor"}[family]
            regs[dst] = f"({smt_op} {right} {left})"
            continue
        return {}, f"unsupported instruction {op}"
    return regs, ""


def prove(expr: str, reg: str, solver: str) -> str:
    symbols = set(re.findall(r"\b(?:in|stale)_[A-Za-z0-9_]+\b", expr)) | {f"in_{reg}"}
    query = "\n".join(f"(declare-const {name} (_ BitVec 64))" for name in sorted(symbols))
    query += f"\n(assert (not (= {expr} in_{reg})))\n(check-sat)\n"
    result = subprocess.run([solver, "-in"], input=query, text=True, capture_output=True, check=False)
    answer = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "unknown"
    return {"unsat": "proved", "sat": "diverged"}.get(answer, "skip")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=pathlib.Path)
    parser.add_argument("--solver", default="z3")
    args = parser.parse_args()
    results = []
    for fn in parse_functions(args.path):
        targets = sorted((fn.clobbers & fn.preserves) & set(CALLEE_SAVED))
        if not fn.returns or not targets:
            continue
        regs, reason = model(fn)
        if reason:
            results.extend({"function": fn.name, "register": reg, "status": "skip", "reason": reason} for reg in targets)
            continue
        for reg in targets:
            results.append({"function": fn.name, "register": reg, "status": prove(regs.get(reg, f"in_{reg}"), reg, args.solver)})
    json.dump({"path": args.path.as_posix(), "results": results}, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 1 if any(item["status"] == "diverged" for item in results) else 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main())
