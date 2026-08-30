#!/usr/bin/env python3
"""Mutation fuzzer for stage1 EASM declaration enforcement (stage0 mirror).

Generates fully-declared functions that use caller-saved scratch registers only,
then drops one required clobber and checks that stage1's shipped verifier
(`Easm::verify_module` via ``test/breadth/easm_verify_stdin.elisa``) accepts the
complete form and rejects the under-declared form.
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
ELISA_CORE = pathlib.Path(
    os.environ.get("ELISA_CORE", ROOT / "../../Go projects/structpy-tree")
)
DEFAULT_ELISAC = os.environ.get(
    "ELISACORE_BIN", str(ELISA_CORE / "compiler" / "bin" / "elisac")
)
SCRATCH_REGS = ["rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11"]
DRIVER = ROOT / "build" / "easm_verify_stdin"


def generate(rng: random.Random) -> tuple[list[str], list[str], list[str]]:
    live: set[str] = set()
    written: set[str] = set()
    uses_flags = False
    requires: set[str] = set()
    body: list[str] = []
    n = 2 + rng.randrange(7)
    for _ in range(n):
        kind = 0 if not live else rng.randrange(5)
        if kind == 0:
            r = SCRATCH_REGS[rng.randrange(len(SCRATCH_REGS))]
            body.append(f"movq ${rng.randrange(1000)}, %{r}")
            live.add(r)
            written.add(r)
        elif kind in (1, 2):
            r = sorted(live)[rng.randrange(len(live))]
            op = ["addq", "subq", "andq", "xorq"][rng.randrange(4)]
            body.append(f"{op} ${rng.randrange(16)}, %{r}")
            written.add(r)
            uses_flags = True
        elif kind == 3:
            r = sorted(live)[rng.randrange(len(live))]
            body.append(f"incq %{r}")
            written.add(r)
            uses_flags = True
        else:
            r = sorted(live)[rng.randrange(len(live))]
            body.append(f"movq %{r}, %{r}")
            written.add(r)
    body.append("ret")
    clobbers = sorted(written)
    if uses_flags:
        clobbers.append("cc")
    return body, clobbers, sorted(requires)


def source(body: list[str], clobbers: list[str], requires: list[str]) -> str:
    # Multi-line contract form matches stage1's .easm parser (single-line
    # `clobbers: rax, cc` is not accepted as a declaration header).
    lines = [
        "module fuzz",
        "target x86_64",
        "",
        "export def fuzz_fn() -> void abi c:",
    ]
    if clobbers:
        lines.append("    clobbers:")
        for c in clobbers:
            lines.append(f"        {c}")
    lines.append("    stack:")
    lines.append("        unchanged")
    lines.append("    control:")
    lines.append("        returns")
    if requires:
        lines.append("    requires:")
        for r in requires:
            lines.append(f"        {r}")
    lines.append("    body:")
    for line in body:
        lines.append(f"        {line}")
    return "\n".join(lines) + "\n"


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


def verify(driver: pathlib.Path, easm_source: str) -> tuple[str, list[str]]:
    """Return (accept|reject, error_codes) from the shipped stage1 verifier."""
    proc = subprocess.run(
        [str(driver)],
        input=easm_source.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    text = proc.stdout.decode(errors="replace")
    codes = [line[5:].strip() for line in text.splitlines() if line.startswith("CODE ")]
    if "RESULT accept" in text:
        return "accept", codes
    if "RESULT reject" in text:
        return "reject", codes
    raise RuntimeError(f"unexpected verifier output (rc={proc.returncode}): {text!r} {proc.stderr.decode(errors='replace')!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=40)
    parser.add_argument("--seed", type=int, default=0xF002)
    parser.add_argument("--elisac", default=os.path.expanduser(DEFAULT_ELISAC))
    parser.add_argument("--llvm-config", default="/opt/homebrew/opt/llvm/bin/llvm-config")
    args = parser.parse_args()
    if not os.path.isfile(args.elisac) or not os.access(args.elisac, os.X_OK):
        print(f"easm_enforcement_fuzz FAILED: elisac not executable: {args.elisac}", file=sys.stderr)
        return 2
    try:
        driver = ensure_driver(args.elisac, args.llvm_config)
    except Exception as exc:
        print(f"easm_enforcement_fuzz FAILED: {exc}", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    accepted_complete = 0
    rejected_drop = 0
    for i in range(args.cases):
        body, clobbers, requires = generate(rng)
        if not clobbers:
            continue
        full = source(body, clobbers, requires)
        status, codes = verify(driver, full)
        if status != "accept":
            print(f"case {i}: complete form REJECTED by verify_module: {codes}\n{full}", file=sys.stderr)
            return 1
        accepted_complete += 1

        # Prefer dropping a GPR clobber (always required for a write); fall back to any.
        victims = [c for c in clobbers if c in SCRATCH_REGS] or list(clobbers)
        victim = victims[rng.randrange(len(victims))]
        reduced = [c for c in clobbers if c != victim]
        dropped = source(body, reduced, requires)
        status, codes = verify(driver, dropped)
        if status != "reject":
            print(
                f"case {i}: under-declared form (dropped {victim}) was ACCEPTED by verify_module\n{dropped}",
                file=sys.stderr,
            )
            return 1
        rejected_drop += 1

    if accepted_complete == 0 or rejected_drop == 0:
        print("easm_enforcement_fuzz FAILED: no cases exercised through verify_module", file=sys.stderr)
        return 1
    print(
        f"easm_enforcement_fuzz OK: {accepted_complete} complete accepted, "
        f"{rejected_drop} drop-mutations rejected via verify_module (seed={args.seed})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
