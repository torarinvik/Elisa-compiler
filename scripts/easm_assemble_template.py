#!/usr/bin/env python3
"""Assemble one stage1 EASM template through LLVM MC.

This is deliberately a thin host-tool adapter: instruction encoding remains LLVM's job.  It
mirrors stage0/compiler/src/easm/easm_assemble.go by assembling a zero-filled body, flipping one
typed hole to an all-ones immediate at a time, and deriving patch byte ranges from the encoded
diff.  The JSON result is the serialized form of Easm.TemplateImage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ENCODING = re.compile(r"encoding:\s*\[([0-9a-fA-Fx, ]*)\]")
TEMPLATE = re.compile(r"^template\s+def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*:\s*$")
HEADER = re.compile(r"^(?:module|target|export\s+def|fragment|protocol|layout|template\s+def)\b")


def hole_class(type_name: str) -> str:
    return "sel16" if type_name.strip() in {"u16", "i16", "GuestFsSelector", "HostFsSelector", "GuestGsSelector", "HostGsSelector"} else "wide64"


def parse_template(path: Path) -> tuple[list[tuple[str, str]], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    holes: list[tuple[str, str]] = []
    body: list[str] = []
    in_template = False
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = TEMPLATE.match(line)
        if match:
            if in_template:
                raise ValueError("multiple templates are not supported; pass one template file")
            in_template = True
            for item in match.group(2).split(","):
                item = item.strip()
                if not item:
                    continue
                if ":" in item:
                    name, type_name = (part.strip() for part in item.split(":", 1))
                else:
                    name, type_name = item, ""
                holes.append((name, type_name))
            continue
        if in_template and HEADER.match(line):
            break
        if in_template:
            body.append(line)
    if not in_template:
        raise ValueError(f"no template def found in {path}")
    if not body:
        raise ValueError("template has no instructions")
    return holes, body


def substitute(text: str, fills: dict[str, str]) -> str:
    for name, value in fills.items():
        text = text.replace(f"<{name}>", value)
        pattern = re.compile(rf"(^|[^%$\w.]){re.escape(name)}($|[^\w])")
        text = pattern.sub(lambda m: m.group(1) + value + m.group(2), text)
    return text


def encoding(output: bytes) -> bytes:
    result = bytearray()
    for match in ENCODING.finditer(output.decode("utf-8", errors="replace")):
        for token in match.group(1).split(","):
            token = token.strip()
            if token:
                result.append(int(token, 16))
    if not result:
        raise ValueError("llvm-mc produced no encoding records")
    return bytes(result)


def assemble(body: list[str], fills: dict[str, str], triple: str, llvm_mc: str) -> bytes:
    source = "\n".join(substitute(line, fills) for line in body) + "\n"
    proc = subprocess.run(
        [llvm_mc, "--assemble", "--show-encoding", f"--triple={triple}"],
        input=source.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(f"llvm-mc failed ({proc.returncode}):\n{proc.stdout.decode(errors='replace')}")
    return encoding(proc.stdout)


def diff_runs(left: bytes, right: bytes) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    index = 0
    while index < len(left):
        if left[index] == right[index]:
            index += 1
            continue
        start = index
        while index < len(left) and left[index] != right[index]:
            index += 1
        runs.append((start, index - start))
    return runs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--triple", default="x86_64-apple-darwin")
    parser.add_argument("--llvm-mc", default=os.environ.get("LLVM_MC"))
    args = parser.parse_args()
    llvm_mc = args.llvm_mc or shutil.which("llvm-mc")
    if not llvm_mc:
        parser.error("llvm-mc not found; set LLVM_MC or install LLVM")
    holes, body = parse_template(args.source)
    base_fills = {name: "$0x0" for name, _ in holes}
    base = assemble(body, base_fills, args.triple, llvm_mc)
    patches: list[dict[str, int | str]] = []
    for name, type_name in holes:
        fills = dict(base_fills)
        fills[name] = "$0xffff" if hole_class(type_name) == "sel16" else "$0xffffffffffffffff"
        flipped = assemble(body, fills, args.triple, llvm_mc)
        if len(flipped) != len(base):
            raise ValueError(f"hole {name} changes encoding length ({len(flipped)} vs {len(base)})")
        runs = diff_runs(base, flipped)
        if not runs:
            raise ValueError(f"hole {name} is never encoded into a byte slot")
        patches.extend({"hole": name, "offset": offset, "width": width} for offset, width in runs)
    json.dump({"bytes": list(base), "patches": patches}, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
