#!/usr/bin/env python3
"""Discover .easm files and hand a framed project to the self-hosted stage1 driver."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=pathlib.Path)
    parser.add_argument("--driver", required=True, type=pathlib.Path)
    parser.add_argument("--mode", choices=("report", "assembly", "artifact"), default="report")
    parser.add_argument("--llvm-mc", default=None)
    parser.add_argument("--lockstep-symbolic", action="store_true")
    parser.add_argument("--lockstep-oracle", action="store_true")
    parser.add_argument("--preserve-parametric", action="store_true")
    args = parser.parse_args()
    args.lockstep_symbolic |= os.environ.get("ELISA_EASM_LOCKSTEP_SYMBOLIC") == "1"
    args.lockstep_oracle |= os.environ.get("ELISA_EASM_LOCKSTEP_ORACLE") == "1"
    args.preserve_parametric |= os.environ.get("ELISA_EASM_PRESERVE_PARAMETRIC") == "1"
    paths = sorted(p for p in args.root.rglob("*.easm") if p.is_file())
    payload = bytearray((args.mode + "\n").encode())
    for path in paths:
        body = path.read_bytes()
        name = path.as_posix().encode()
        payload.extend(b"@file " + str(len(body)).encode() + b" " + name + b"\n")
        payload.extend(body)
    if args.mode != "artifact":
        completed = subprocess.run([str(args.driver)], input=payload, stdout=subprocess.PIPE)
        sys.stdout.buffer.write(completed.stdout)
        return completed.returncode

    report_payload = bytearray(payload)
    report_payload[0 : len(b"artifact\n")] = b"report\n"
    report = subprocess.run([str(args.driver)], input=report_payload, stdout=subprocess.PIPE, check=False)
    if report.returncode:
        return report.returncode
    assembly_payload = bytearray(payload)
    assembly_payload[0 : len(b"artifact\n")] = b"assembly\n"
    assembly = subprocess.run([str(args.driver)], input=assembly_payload, stdout=subprocess.PIPE, check=False)
    if assembly.returncode:
        return assembly.returncode
    templates = []
    lockstep = []
    oracle = []
    preservation = []
    assembler = args.llvm_mc
    for path in paths:
        if b"template def " not in path.read_bytes():
            continue
        command = [sys.executable, str(pathlib.Path(__file__).with_name("easm_assemble_template.py")), str(path)]
        if assembler:
            command.extend(["--llvm-mc", assembler])
        image = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if image.returncode:
            sys.stderr.buffer.write(image.stderr)
            return image.returncode
        templates.append({"path": path.as_posix(), "image": json.loads(image.stdout)})
    if args.lockstep_symbolic:
        checker = pathlib.Path(__file__).with_name("easm_lockstep_symbolic.py")
        for path in paths:
            checked = subprocess.run([sys.executable, str(checker), str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if checked.returncode not in (0, 1):
                sys.stderr.buffer.write(checked.stderr)
                return checked.returncode
            lockstep.extend(json.loads(checked.stdout).get("results", []))
        if any(item.get("status") == "diverged" for item in lockstep):
            return 1
    if args.lockstep_oracle:
        checker = pathlib.Path(__file__).with_name("easm_lockstep_oracle.py")
        for path in paths:
            checked = subprocess.run([sys.executable, str(checker), str(path), "--llvm-mc", args.llvm_mc] if args.llvm_mc else [sys.executable, str(checker), str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if checked.returncode not in (0, 1):
                sys.stderr.buffer.write(checked.stderr)
                return checked.returncode
            oracle.extend(json.loads(checked.stdout).get("results", []))
        if any(item.get("status") == "diverged" for item in oracle):
            return 1
    if args.preserve_parametric:
        checker = pathlib.Path(__file__).with_name("easm_preserve_parametric.py")
        for path in paths:
            checked = subprocess.run([sys.executable, str(checker), str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if checked.returncode not in (0, 1):
                sys.stderr.buffer.write(checked.stderr)
                return checked.returncode
            preservation.extend(json.loads(checked.stdout).get("results", []))
        if any(item.get("status") == "diverged" for item in preservation):
            return 1
    json.dump({"report": report.stdout.decode(), "assembly": assembly.stdout.decode(), "templates": templates, "lockstep": lockstep, "oracle": oracle, "preservation": preservation}, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
