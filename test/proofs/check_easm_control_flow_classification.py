"""Bind EASM branch and terminator proofs to production predicates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MODEL = ROOT / "src/backend/easm_model.elisa"
POSITIVE = HERE / "easm_control_flow_classification.elisa"
NEGATIVE = HERE / "easm_control_flow_classification_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking Elisa-Proof")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


model_text = MODEL.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
contracts = {
    "easm_is_conditional_jump": (
        'ensure result == (easm_starts(op, "j") and not easm_equal(op, "jmp") and not easm_equal(op, "jmpq"))',
    ),
    "easm_is_terminator": (
        'ensure result == (easm_equal(op, "jmp") or easm_equal(op, "jmpq") or easm_equal(op, "ret") or easm_equal(op, "retq"))',
    ),
}
for name, clauses in contracts.items():
    section = compact(function_section(model_text, name))
    if any(compact(clause) not in section for clause in clauses):
        raise SystemExit(f"production EASM predicate {name} lost its exact classification contract")
if compact('return easm_starts(op, "j") and not easm_equal(op, "jmp") and not easm_equal(op, "jmpq")') not in compact(function_section(model_text, "easm_is_conditional_jump")):
    raise SystemExit("conditional-jump predicate implementation diverged from its contract")
if compact('return easm_equal(op, "jmp") or easm_equal(op, "jmpq") or easm_equal(op, "ret") or easm_equal(op, "retq")') not in compact(function_section(model_text, "easm_is_terminator")):
    raise SystemExit("terminator predicate implementation diverged from its contract")

positive_names = {
    "each_unconditional_transfer_is_a_terminator",
    "conditional_branch_mnemonics_are_classified",
    "ordinary_instruction_is_neither_a_terminator_nor_a_conditional_jump",
    "unconditional_jump_is_not_conditional",
    "conditional_jump_is_not_a_terminator",
    "terminators_are_never_conditional_branches",
}
negative_names = {
    "ordinary_instruction_can_be_a_terminator",
    "conditional_branch_can_be_a_terminator",
    "unconditional_jump_can_be_a_conditional_branch",
    "return_can_be_a_conditional_branch",
    "conditional_branch_can_also_terminate",
    "a_terminator_can_be_a_conditional_branch",
}
positive_claims = {
    "each_unconditional_transfer_is_a_terminator": 'Easm::easm_is_terminator("jmp") and Easm::easm_is_terminator("jmpq") and Easm::easm_is_terminator("ret") and Easm::easm_is_terminator("retq")',
    "conditional_branch_mnemonics_are_classified": 'Easm::easm_is_conditional_jump("je") and Easm::easm_is_conditional_jump("jne") and Easm::easm_is_conditional_jump("jz") and Easm::easm_is_conditional_jump("jnz")',
    "ordinary_instruction_is_neither_a_terminator_nor_a_conditional_jump": 'not Easm::easm_is_terminator("add") and not Easm::easm_is_conditional_jump("add")',
    "unconditional_jump_is_not_conditional": 'not Easm::easm_is_conditional_jump("jmp") and not Easm::easm_is_conditional_jump("jmpq")',
    "conditional_jump_is_not_a_terminator": "not Easm::easm_is_terminator(op)",
    "terminators_are_never_conditional_branches": "not Easm::easm_is_conditional_jump(op)",
}
negative_claims = {
    "ordinary_instruction_can_be_a_terminator": 'Easm::easm_is_terminator("add")',
    "conditional_branch_can_be_a_terminator": 'Easm::easm_is_terminator("je")',
    "unconditional_jump_can_be_a_conditional_branch": 'Easm::easm_is_conditional_jump("jmp")',
    "return_can_be_a_conditional_branch": 'Easm::easm_is_conditional_jump("ret")',
    "conditional_branch_can_also_terminate": "Easm::easm_is_terminator(op)",
    "a_terminator_can_be_a_conditional_branch": "Easm::easm_is_conditional_jump(op)",
}
preconditions = {
    "each_unconditional_transfer_is_a_terminator": "",
    "conditional_branch_mnemonics_are_classified": "",
    "ordinary_instruction_is_neither_a_terminator_nor_a_conditional_jump": "",
    "unconditional_jump_is_not_conditional": "",
    "conditional_jump_is_not_a_terminator": "requires Easm::easm_is_conditional_jump(op)",
    "terminators_are_never_conditional_branches": "requires Easm::easm_is_terminator(op)",
}
negative_preconditions = {
    "ordinary_instruction_can_be_a_terminator": "",
    "conditional_branch_can_be_a_terminator": "",
    "unconditional_jump_can_be_a_conditional_branch": "",
    "return_can_be_a_conditional_branch": "",
    "conditional_branch_can_also_terminate": "requires Easm::easm_is_conditional_jump(op)",
    "a_terminator_can_be_a_conditional_branch": "requires Easm::easm_is_terminator(op)",
}

for source_text, names, label in (
    (positive_text, positive_names, "positive"),
    (negative_text, negative_names, "negative"),
):
    if declarations(source_text) != names:
        raise SystemExit(f"{label} EASM control-flow theorem inventory changed")
    if 'include "../../src/backend/easm_model.elisa"' not in source_text:
        raise SystemExit(f"{label} EASM control-flow proofs no longer include the production model")
for source_text, claims, requirements, label in (
    (positive_text, positive_claims, preconditions, "positive"),
    (negative_text, negative_claims, negative_preconditions, "negative"),
):
    if set(claims) != set(requirements):
        raise SystemExit(f"{label} EASM control-flow claim and precondition inventories differ")
    for name in claims:
        section = compact(function_section(source_text, name))
        if compact("ensure result == true") not in section \
                or compact(claims[name]) not in section \
                or (requirements[name] and compact(requirements[name]) not in section):
            raise SystemExit(f"EASM control-flow theorem {name} lost its claim or precondition")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive": len(positive_names),
                      "false_claim_controls": len(negative_names),
                      "source_closure_files": len(source_closure)}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("EASM control-flow classification proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", MODEL, POSITIVE, NEGATIVE, *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "EASM terminator and conditional branch classes drive the intended CFG boundaries",
    "positive_claims_proved": sorted(positive_names),
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
