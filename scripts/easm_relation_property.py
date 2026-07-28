#!/usr/bin/env python3
"""Behavioral relation property suite for stage1 EASM verification (stage0 mirror).

Generates random straight-line bodies, executes them with a concrete interpreter, and
checks that stage1's shipped verifier (`Easm::verify_module` via
``test/breadth/easm_verify_stdin.elisa``):

* REJECTS bodies where the concrete interpreter sees an undefined register read, and
* ACCEPTS fully-declared bodies with no concrete undefined reads.

This is the stage0 relation-property idea reduced to the stage1-visible contract:
verifier rejection tracks real uninit reads; accepted bodies are not under-declared.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import random
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REGS = ["rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11"]
OPS = ["movq", "addq", "subq", "andq", "xorq", "incq", "decq", "xchgq"]
DRIVER = ROOT / "build" / "easm_verify_stdin"


def generate_body(rng: random.Random, force_undef: bool = False) -> tuple[list[str], dict[str, int]]:
    """Generate a body. When force_undef is False, only touch initialized registers."""
    inputs: dict[str, int] = {}
    for reg in REGS:
        if force_undef:
            if rng.randrange(3) != 0:
                inputs[reg] = rng.randrange(17)
        else:
            # Sound bodies: every register starts defined so no uninit reads are possible.
            inputs[reg] = rng.randrange(17)
    live = list(inputs.keys()) if inputs else list(REGS)
    body: list[str] = []
    n = 1 + rng.randrange(12)
    imms = [0, 1, 2, 3, 7, 15, 16, 31]
    while len(body) < n:
        op = OPS[rng.randrange(len(OPS))]
        reg = live[rng.randrange(len(live))]
        other = live[rng.randrange(len(live))]
        imm = f"${imms[rng.randrange(len(imms))]}"
        if op == "movq":
            body.append(f"        movq {imm if rng.randrange(2) == 0 else '%' + other}, %{reg}")
        elif op in {"addq", "subq", "andq", "xorq"}:
            body.append(f"        {op} {imm if rng.randrange(2) == 0 else '%' + other}, %{reg}")
        elif op in {"incq", "decq"}:
            body.append(f"        {op} %{reg}")
        else:
            body.append(f"        xchgq %{reg}, %{other}")
    if force_undef:
        cold = next((r for r in REGS if r not in inputs), None)
        if cold is None:
            # All regs were inputs; drop one from inputs and use it cold.
            cold = REGS[rng.randrange(len(REGS))]
            inputs.pop(cold, None)
            # Drop prior writes to cold.
            body = [line for line in body if not re.search(rf"%{cold}\b", line.split(",")[-1] if "," in line else "")]
        else:
            body = [line for line in body if not re.search(rf"%{cold}\b", line.split(",")[-1] if "," in line else "")]
        # Ensure rax is defined so addq %cold, %rax only faults on cold.
        if "rax" not in inputs:
            body.insert(0, "        movq $0, %rax")
            inputs["rax"] = 0
        body.append(f"        addq %{cold}, %rax")
    body.append("        ret")
    return body, inputs


def wrap(body: list[str], inputs: dict[str, int]) -> str:
    params = [f"{r}_in: u64" for r in REGS if r in inputs]
    binds = [f"{r}_in = {r}" for r in REGS if r in inputs]
    # Multi-line contract form matches stage1's .easm parser.
    lines = [
        "module relation_property",
        "target x86_64",
        f"export def relation_prop({', '.join(params) if params else ''}) -> void abi c:",
    ]
    if binds:
        lines.append("    inputs:")
        for b in binds:
            lines.append(f"        {b}")
    lines.append("    clobbers:")
    for c in ["rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11", "cc", "memory"]:
        lines.append(f"        {c}")
    lines.append("    stack:")
    lines.append("        synthetic")
    lines.append("    control:")
    lines.append("        returns")
    lines.append("    requires:")
    lines.append("        input.unused")
    lines.append("        x86_64.atomic.rmw")
    lines.append("    body:")
    lines.extend(body)
    return "\n".join(lines) + "\n"


def concrete_undefined_read(body: list[str], inputs: dict[str, int]) -> bool:
    defined = {r: True for r in inputs}
    for raw in body:
        text = raw.strip()
        if text == "ret":
            break
        pieces = text.split(None, 1)
        op = pieces[0]
        ops = [p.strip() for p in pieces[1].split(",")] if len(pieces) == 2 else []
        if op in {"incq", "decq"}:
            r = ops[0].lstrip("%")
            if r not in defined:
                return True
            defined[r] = True
            continue
        if op == "xchgq":
            a, b = ops[0].lstrip("%"), ops[1].lstrip("%")
            if a not in defined or b not in defined:
                return True
            defined[a] = defined[b] = True
            continue
        if op == "movq":
            src, dst = ops[0], ops[1].lstrip("%")
            if src.startswith("%") and src.lstrip("%") not in defined:
                return True
            defined[dst] = True
            continue
        if op in {"addq", "subq", "andq", "xorq"}:
            src, dst = ops[0], ops[1].lstrip("%")
            if dst not in defined:
                return True
            if src.startswith("%") and src.lstrip("%") not in defined:
                return True
            defined[dst] = True
    return False


def ensure_driver(elisac: str, llvm_config: str) -> pathlib.Path:
    src = ROOT / "test" / "breadth" / "easm_verify_stdin.elisa"
    obj = ROOT / "build" / "easm_verify_stdin.o"
    log = ROOT / "build" / "easm_verify_stdin.log"
    ROOT.joinpath("build").mkdir(parents=True, exist_ok=True)
    if not DRIVER.exists() or src.stat().st_mtime > DRIVER.stat().st_mtime:
        with open(log, "w", encoding="utf-8") as fh:
            proc = subprocess.run(
                [elisac, "-emit", "obj", "-O2", "-o", str(obj), str(src)],
                stdout=fh,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if proc.returncode != 0 or not obj.exists():
            raise RuntimeError(f"failed to compile easm_verify_stdin (see {log})")
        libdir = subprocess.check_output([llvm_config, "--libdir"], text=True).strip()
        subprocess.check_call(
            ["clang", "-o", str(DRIVER), str(obj), f"-L{libdir}", "-lLLVM", f"-Wl,-rpath,{libdir}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return DRIVER


def verify(driver: pathlib.Path, easm_source: str) -> str:
    proc = subprocess.run(
        [str(driver)],
        input=easm_source.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    text = proc.stdout.decode(errors="replace")
    if "RESULT accept" in text:
        return "accept"
    if "RESULT reject" in text:
        return "reject"
    raise RuntimeError(f"unexpected verifier output (rc={proc.returncode}): {text!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=40)
    parser.add_argument("--seed", type=int, default=0xE451A)
    parser.add_argument("--elisac", default=os.path.expanduser("~/.elisac/elisac"))
    parser.add_argument("--llvm-config", default="/opt/homebrew/opt/llvm/bin/llvm-config")
    args = parser.parse_args()
    if not os.path.isfile(args.elisac) or not os.access(args.elisac, os.X_OK):
        print(f"easm_relation_property FAILED: elisac not executable: {args.elisac}", file=sys.stderr)
        return 2
    try:
        driver = ensure_driver(args.elisac, args.llvm_config)
    except Exception as exc:
        print(f"easm_relation_property FAILED: {exc}", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    accepted_sound = 0
    rejected_undef = 0
    for i in range(args.cases):
        # Half the cases force an uninit read so the reject path is always exercised.
        force_undef = i % 2 == 0
        body, inputs = generate_body(rng, force_undef=force_undef)
        undef = concrete_undefined_read(body, inputs)
        src = wrap(body, inputs)
        status = verify(driver, src)
        if undef:
            if status != "reject":
                print(
                    f"case {i}: concrete uninit read but verify_module ACCEPTED\n{src}",
                    file=sys.stderr,
                )
                return 1
            rejected_undef += 1
        else:
            if status != "accept":
                print(
                    f"case {i}: sound body REJECTED by verify_module\n{src}",
                    file=sys.stderr,
                )
                return 1
            accepted_sound += 1

    if accepted_sound == 0 or rejected_undef == 0:
        print(
            f"easm_relation_property FAILED: need both accept and reject paths "
            f"(accept={accepted_sound}, reject={rejected_undef})",
            file=sys.stderr,
        )
        return 1
    print(
        f"easm_relation_property OK: {accepted_sound} sound accepted, "
        f"{rejected_undef} uninit rejected via verify_module (seed={args.seed})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
