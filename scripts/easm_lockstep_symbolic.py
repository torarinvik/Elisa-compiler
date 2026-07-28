#!/usr/bin/env python3
"""Prove the modelable stage0 EASM lockstep subset with Z3.

Models:
  * straight-line 64-bit GPR/ALU (original subset)
  * flag-producing cmp/test plus locally-structured conditional diamonds (je/jne/…)
  * ambient machine-state pseudos (`state direction=…`) that must match at ret
  * bounded counted loops of the form ``decq %r / jcc label`` with constant trip count

Anything outside the subset returns ``skip`` rather than being treated as equivalent.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

REG_ALIASES = {
    "eax": "rax", "ebx": "rbx", "ecx": "rcx", "edx": "rdx", "esi": "rsi", "edi": "rdi", "ebp": "rbp",
    "r8d": "r8", "r9d": "r9", "r10d": "r10", "r11d": "r11", "r12d": "r12", "r13d": "r13", "r14d": "r14", "r15d": "r15",
}
REGS = {"rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp", "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"}
HEADER = re.compile(r"^export\s+def\s+([A-Za-z_][A-Za-z0-9_]*)\b")
COND_JUMPS = {
    "je": "eq", "jz": "eq", "jne": "ne", "jnz": "ne",
    "jb": "ult", "jnae": "ult", "jae": "uge", "jnb": "uge",
    "jbe": "ule", "jna": "ule", "ja": "ugt", "jnbe": "ugt",
    "jl": "slt", "jnge": "slt", "jge": "sge", "jnl": "sge",
    "jle": "sle", "jng": "sle", "jg": "sgt", "jnle": "sgt",
}
MAX_UNROLL = 64


def reg(operand: str) -> str | None:
    operand = operand.strip().lower()
    if not operand.startswith("%"):
        return None
    name = REG_ALIASES.get(operand[1:], operand[1:])
    return name if name in REGS else None


def immediate(operand: str) -> int | None:
    operand = operand.strip().lower()
    if not operand.startswith("$"):
        return None
    try:
        return int(operand[1:], 0)
    except ValueError:
        return None


def is_32bit_register(operand: str) -> bool:
    name = operand.strip().lower().lstrip("%")
    return name in {"eax", "ebx", "ecx", "edx", "esi", "edi", "ebp"} or bool(re.fullmatch(r"r(?:[89]|1[0-5])d", name))


def lea_displacement(operand: str) -> tuple[str, int] | None:
    match = re.fullmatch(r"\s*(-?(?:0x[0-9a-f]+|[0-9]+))?\(%([a-z][a-z0-9]*)\)\s*", operand.lower())
    if not match:
        return None
    displacement = int(match.group(1) or "0", 0)
    base = reg("%" + match.group(2))
    return (base, displacement) if base is not None else None


def split_operands(text: str) -> list[str]:
    return [part.strip() for part in text.split(",")]


def bv(value: int) -> str:
    return f"(_ bv{value & ((1 << 64) - 1)} 64)"


class State:
    def __init__(self) -> None:
        self.terms: dict[str, str] = {}
        self.inputs: set[str] = set()
        self.flags: tuple[str, str] | None = None  # (left, right) bitvectors for last cmp/test
        self.ambient: dict[str, str] = {}  # e.g. direction -> "0"/"1"

    def clone(self) -> "State":
        other = State()
        other.terms = dict(self.terms)
        other.inputs = set(self.inputs)
        other.flags = self.flags
        other.ambient = dict(self.ambient)
        return other

    def read(self, operand: str) -> str | None:
        name = reg(operand)
        if name is not None:
            if name not in self.terms:
                self.terms[name] = f"in_{name}"
                self.inputs.add(name)
            return self.terms[name]
        value = immediate(operand)
        return bv(value) if value is not None else None

    def write(self, operand: str, term: str) -> bool:
        name = reg(operand)
        if name is None:
            return False
        self.terms[name] = term
        return True

    def merge_ite(self, cond: str, taken: "State", fallthrough: "State") -> None:
        keys = set(taken.terms) | set(fallthrough.terms) | set(self.terms)
        for key in keys:
            left = taken.terms.get(key, fallthrough.terms.get(key, self.terms.get(key, f"in_{key}")))
            right = fallthrough.terms.get(key, taken.terms.get(key, self.terms.get(key, f"in_{key}")))
            if left == right:
                self.terms[key] = left
            else:
                self.terms[key] = f"(ite {cond} {left} {right})"
            if key.startswith("in_"):
                self.inputs.add(key[3:])
        for side in (taken, fallthrough):
            self.inputs |= side.inputs
        # Ambient must agree; otherwise leave join ambient empty (caller skips).
        if taken.ambient == fallthrough.ambient:
            self.ambient = dict(taken.ambient)
        else:
            self.ambient = {"__conflict__": "1"}
        self.flags = None


def parse_lines(body: list[str]) -> list[tuple[str, list[str], str | None]]:
    """Return list of (op, operands, label_or_None). Labels are ( 'label', [], name )."""
    out: list[tuple[str, list[str], str | None]] = []
    for raw in body:
        text = raw.split("#", 1)[0].strip()
        if not text:
            continue
        if text.endswith(":") and not text.startswith("."):
            out.append(("label", [], text[:-1]))
            continue
        pieces = text.split(None, 1)
        op = pieces[0].lower()
        operands = split_operands(pieces[1]) if len(pieces) == 2 else []
        out.append((op, operands, None))
    return out


def apply_op(state: State, op: str, operands: list[str]) -> str | None:
    """Apply one instruction. Returns error reason or None on success."""
    if op in {"ret", "retq"}:
        return None
    if op == "state" or op.startswith("state"):
        # Ambient pseudo: `state direction=fwd|bwd` / `state direction=0|1`
        text = " ".join(operands) if operands else ""
        if "direction" in text:
            if "bwd" in text or "1" in text.split("=")[-1]:
                state.ambient["direction"] = "1"
            else:
                state.ambient["direction"] = "0"
            return None
        return "unsupported ambient state form"
    if op in {"movq"}:
        if len(operands) != 2:
            return f"malformed {op}"
        source = state.read(operands[0])
        if source is None or not state.write(operands[1], source):
            return f"{op} has an unsupported operand"
        return None
    if op in {"movl"}:
        if len(operands) != 2 or not is_32bit_register(operands[1]):
            return "movl destination is not a 32-bit register"
        source = state.read(operands[0])
        if source is None or not state.write(operands[1], f"(concat (_ bv0 32) ((_ extract 31 0) {source}))"):
            return "movl source is not modelable"
        return None
    if op in {"addq", "subq", "andq", "orq", "xorq"}:
        if len(operands) != 2:
            return f"malformed {op}"
        source = state.read(operands[0])
        destination = state.read(operands[1])
        if source is None or destination is None:
            return f"{op} has an unsupported operand"
        fn = {"addq": "bvadd", "subq": "bvsub", "andq": "bvand", "orq": "bvor", "xorq": "bvxor"}[op]
        state.write(operands[1], f"({fn} {destination} {source})")
        return None
    if op in {"incq", "decq", "notq", "negq"}:
        if len(operands) != 1:
            return f"malformed {op}"
        old = state.read(operands[0])
        if old is None:
            return f"{op} destination is not modelable"
        if op == "incq":
            term = f"(bvadd {old} {bv(1)})"
        elif op == "decq":
            term = f"(bvsub {old} {bv(1)})"
        else:
            term = f"({'bvnot' if op == 'notq' else 'bvneg'} {old})"
        if not state.write(operands[0], term):
            return f"{op} destination is not a register"
        if op in {"incq", "decq"}:
            state.flags = (term, bv(0))
        return None
    if op in {"shlq", "salq", "shrq", "sarq"}:
        if len(operands) != 2:
            return f"malformed {op}"
        count = immediate(operands[0])
        old = state.read(operands[1])
        if count is None or old is None:
            return f"{op} requires an immediate and GPR destination"
        fn = {"shlq": "bvshl", "salq": "bvshl", "shrq": "bvlshr", "sarq": "bvashr"}[op]
        if not state.write(operands[1], f"({fn} {old} {bv(count)})"):
            return f"{op} destination is not a register"
        return None
    if op in {"xchgq", "xchg"}:
        if len(operands) != 2 or reg(operands[0]) is None or reg(operands[1]) is None:
            return "xchg operands are not registers"
        left, right = state.read(operands[0]), state.read(operands[1])
        if left is None or right is None or not state.write(operands[0], right) or not state.write(operands[1], left):
            return "xchg operands are not modelable"
        return None
    if op in {"leaq", "lea"}:
        if len(operands) != 2:
            return "malformed lea"
        address = lea_displacement(operands[0])
        if address is None:
            return "lea addressing form is not modelable"
        base, displacement = address
        old = state.read("%" + base)
        if old is None or not state.write(operands[1], f"(bvadd {old} {bv(displacement)})"):
            return "lea operands are not modelable"
        return None
    if op in {"cmpq", "cmp", "testq", "test"}:
        if len(operands) != 2:
            return f"malformed {op}"
        left = state.read(operands[1])  # AT&T order: cmp src, dst compares dst ? src
        right = state.read(operands[0])
        if op.startswith("test"):
            left = state.read(operands[0])
            right = state.read(operands[1])
            if left is None or right is None:
                return "test operands not modelable"
            state.flags = (f"(bvand {left} {right})", bv(0))
            return None
        if left is None or right is None:
            return "cmp operands not modelable"
        state.flags = (left, right)
        return None
    if op in {"jmp", "jmpq"}:
        return "unconditional jump outside modeled diamond/loop form"
    if op in COND_JUMPS:
        return "orphan conditional jump"
    return f"unsupported instruction {op}"


def flag_cond(pred: str, left: str, right: str) -> str:
    table = {
        "eq": f"(= {left} {right})",
        "ne": f"(not (= {left} {right}))",
        "ult": f"(bvult {left} {right})",
        "uge": f"(bvuge {left} {right})",
        "ule": f"(bvule {left} {right})",
        "ugt": f"(bvugt {left} {right})",
        "slt": f"(bvslt {left} {right})",
        "sge": f"(bvsge {left} {right})",
        "sle": f"(bvsle {left} {right})",
        "sgt": f"(bvsgt {left} {right})",
    }
    return table[pred]


def encode(body: list[str]) -> tuple[State | None, str | None]:
    ops = parse_lines(body)
    labels: dict[str, int] = {}
    for index, (op, _operands, label) in enumerate(ops):
        if op == "label" and label is not None:
            if label in labels:
                return None, "duplicate label"
            labels[label] = index

    state = State()
    index = 0
    while index < len(ops):
        op, operands, label = ops[index]
        if op == "label":
            index += 1
            continue
        if op in COND_JUMPS:
            if state.flags is None:
                return None, "conditional jump without live flags"
            target = operands[0].lstrip(".") if operands else ""
            if target not in labels:
                return None, "unknown jump target"
            target_index = labels[target]
            pred = COND_JUMPS[op]
            left, right = state.flags
            cond = flag_cond(pred, left, right)

            # Backward jump: counted loop form `decq %r` setting flags + jcc back.
            if target_index < index:
                # The back-edge is taken after a dec that just updated a counter. Accept either
                # a pure constant term or `(bvsub (_ bvN 64) (_ bv1 64))` (post-dec remainder).
                def remaining_trips(term: str) -> int | None:
                    match = re.fullmatch(r"\(_ bv(\d+) 64\)", term)
                    if match:
                        return int(match.group(1))
                    match = re.fullmatch(r"\(bvsub \(_ bv(\d+) 64\) \(_ bv1 64\)\)", term)
                    if match:
                        return int(match.group(1)) - 1
                    return None

                trip = None
                for reg_name, term in state.terms.items():
                    count = remaining_trips(term)
                    if count is not None and 0 <= count <= MAX_UNROLL:
                        if trip is None or reg_name == "rcx":
                            trip = (reg_name, count)
                if trip is None:
                    return None, "loop trip count not a small constant"
                counter, count = trip
                if count == 0:
                    index += 1
                    continue
                # Current state already applied the first body iteration through the dec.
                # Re-run the loop body `count` more times for the remaining trips.
                loop_body = ops[target_index:index]  # label..dec exclusive of jcc
                for _ in range(count):
                    for loop_op, loop_operands, _loop_label in loop_body:
                        if loop_op == "label":
                            continue
                        if loop_op in COND_JUMPS:
                            continue
                        reason = apply_op(state, loop_op, loop_operands)
                        if reason:
                            return None, f"loop body: {reason}"
                index += 1
                continue

            # Forward diamond: execute taken path to target, fallthrough to target, merge.
            taken = state.clone()
            fall = state.clone()
            # Fallthrough executes until target.
            cursor = index + 1
            while cursor < target_index:
                fop, foperands, _ = ops[cursor]
                if fop == "label":
                    cursor += 1
                    continue
                if fop in COND_JUMPS or fop in {"jmp", "jmpq"}:
                    return None, "nested control flow in diamond"
                reason = apply_op(fall, fop, foperands)
                if reason:
                    return None, reason
                cursor += 1
            # Taken path skips fallthrough region (empty body for simple je skip).
            if fall.ambient.get("__conflict__") or taken.ambient.get("__conflict__"):
                return None, "ambient state conflict on branch"
            state.merge_ite(cond, taken, fall)
            if state.ambient.get("__conflict__"):
                return None, "ambient state diverges across branch"
            index = target_index
            continue

        if op in {"jmp", "jmpq"}:
            target = operands[0].lstrip(".") if operands else ""
            if target not in labels:
                return None, "unknown jmp target"
            target_index = labels[target]
            if target_index <= index:
                return None, "backward jmp not a counted loop form"
            index = target_index
            continue

        reason = apply_op(state, op, operands)
        if reason:
            return None, reason
        index += 1
    return state, None


def pairs(source: str) -> list[dict[str, object]]:
    lines = source.splitlines()
    found: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    section: str | None = None
    for raw in lines:
        text = raw.split("#", 1)[0].strip()
        match = HEADER.match(text)
        if match:
            if current and current.get("reference") and current.get("target"):
                found.append(current)
            current = {"name": match.group(1), "outputs": [], "reference": [], "target": [], "ambient_check": True}
            section = None
            continue
        if current is None:
            continue
        if text.startswith("outputs:"):
            section = "outputs"
            current["outputs"] = [part.strip().split("=")[-1].strip().lstrip("%") for part in text[len("outputs:"):].split(",") if "=" in part]
            continue
        if text == "reference:":
            section = "reference"
            continue
        if text.startswith("target ") and " lockstep " in text:
            section = "target"
            continue
        if section == "outputs" and "=" in text:
            current["outputs"].extend(part.strip().split("=")[-1].strip().lstrip("%") for part in text.split(","))
            continue
        if text.endswith(":") and not text.startswith(("reference", "target")):
            # Label inside a body — keep section, append as instruction text.
            if section in {"reference", "target"}:
                current[section].append(text)
            else:
                section = None
            continue
        if section in {"reference", "target"} and text:
            current[section].append(text)
    if current and current.get("reference") and current.get("target"):
        found.append(current)
    return found


def prove(pair: dict[str, object], z3: str) -> dict[str, object]:
    reference, ref_reason = encode(pair["reference"])
    target, target_reason = encode(pair["target"])
    if reference is None or target is None:
        return {"name": pair["name"], "status": "skip", "reason": ref_reason or target_reason}
    if reference.ambient != target.ambient:
        return {"name": pair["name"], "status": "diverged", "reason": "ambient machine state differs"}
    outputs = pair["outputs"] or ["rax"]
    terms: list[tuple[str, str]] = []
    inputs = sorted(reference.inputs | target.inputs)
    for output in outputs:
        if output not in reference.terms:
            reference.terms[output] = f"in_{output}"
            inputs.append(output)
        if output not in target.terms:
            target.terms[output] = f"in_{output}"
            if output not in inputs:
                inputs.append(output)
        terms.append((reference.terms[output], target.terms[output]))
    query = ["(set-logic QF_BV)"]
    query.extend(f"(declare-fun in_{name} () (_ BitVec 64))" for name in sorted(set(inputs)))
    query.append("(assert (or " + " ".join(f"(distinct {left} {right})" for left, right in terms) + ")))")
    query.append("(check-sat)")
    proc = subprocess.run([z3, "-in"], input=("\n".join(query) + "\n").encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    result = proc.stdout.decode().strip().splitlines()[-1] if proc.stdout.strip() else "unknown"
    if result == "unsat":
        return {"name": pair["name"], "status": "proved"}
    if result == "sat":
        return {"name": pair["name"], "status": "diverged"}
    return {"name": pair["name"], "status": "skip", "reason": proc.stderr.decode().strip() or result}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=pathlib.Path)
    parser.add_argument("--z3", default=shutil.which("z3"))
    args = parser.parse_args()
    if not args.z3:
        print(json.dumps({"status": "skip", "reason": "z3 not found"}))
        return 0
    results = [prove(pair, args.z3) for pair in pairs(args.source.read_text(encoding="utf-8"))]
    json.dump({"results": results}, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 1 if any(item["status"] == "diverged" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
