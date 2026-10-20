"""Admit EASM label-lookup proofs against the production resolver."""
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
POSITIVE = HERE / "easm_label_lookup.elisa"
NEGATIVE = HERE / "easm_label_lookup_rejected.elisa"

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
lookup = compact(function_section(model_text, "easm_label_index"))
label_name_helper = compact(function_section(model_text, "easm_label_name_from_trimmed"))
label_name = compact(function_section(model_text, "easm_label_name"))
required_label_helper_contracts = (
    "ensure result == (easm_trim(text[0:text.len - 1.usize()]) if text.len > 0 and text[text.len - 1.usize()] == 58 else text)",
)
if any(compact(contract) not in label_name_helper for contract in required_label_helper_contracts):
    raise SystemExit("EASM label-name helper lost its exact trimmed-name or terminal-colon contract")
required_label_name_contracts = (
    'ensure result == (easm_label_name_from_trimmed(easm_trim(instruction.text)) if instruction.op == "label" else "")',
)
if any(compact(contract) not in label_name for contract in required_label_name_contracts):
    raise SystemExit("EASM label-name normalization lost its non-label, trim, or terminal-colon contract")
required_label_helper_body = (
    "return easm_trim(text[0:text.len - 1.usize()]) if text.len > 0 and text[text.len - 1.usize()] == 58 else text",
)
helper_positions = [label_name_helper.find(compact(fragment)) for fragment in required_label_helper_body]
if any(position < 0 for position in helper_positions) or helper_positions != sorted(helper_positions):
    raise SystemExit("EASM label-name helper lost its exact terminal-colon implementation")
required_label_name_body = (
    'return easm_label_name_from_trimmed(easm_trim(instruction.text)) if instruction.op == "label" else ""',
)
label_positions = [label_name.find(compact(fragment)) for fragment in required_label_name_body]
if any(position < 0 for position in label_positions) or label_positions != sorted(label_positions):
    raise SystemExit("EASM label-name resolver lost its exact label-only normalization")
required_contracts = (
    "ensure result >= -1",
    "ensure (instructions.count.i64() < 0 or instructions.count.i64().usize() != instructions.count) implies result == -1",
    "ensure target.len == 0 implies result == -1",
    "ensure result >= 0 implies result.usize() < instructions.count",
    "ensure result >= 0 implies result.usize().i64() == result",
    'ensure result >= 0 implies instructions[result.usize()].op == "label" and easm_equal(easm_label_name(instructions[result.usize()]), target)',
    'ensure result >= 0 implies (forall prior in 0..<result.usize(): instructions[prior].op != "label" or not easm_equal(easm_label_name(instructions[prior]), target))',
    'ensure (instructions.count.i64() >= 0 and instructions.count.i64().usize() == instructions.count and result == -1 and target.len > 0) implies (forall candidate in 0..<instructions.count: instructions[candidate].op != "label" or not easm_equal(easm_label_name(instructions[candidate]), target))',
)
if any(compact(contract) not in lookup for contract in required_contracts):
    raise SystemExit("EASM label lookup lost its sentinel, count, first-match, or miss contract")

required_body = (
    "count: usize = instructions.count",
    "count_signed: i64 = count.i64()",
    "return -1 if target.len == 0 or count_signed < 0 or count_signed.usize() != count",
    "assert count_signed >= 0",
    "assert count_signed.usize() == count",
    "assert count_signed == instructions.count.i64()",
    "for index in 0..<count |count, instructions, target|:",
    'invariant forall prior in 0..<index: instructions[prior].op != "label" or not easm_equal(easm_label_name(instructions[prior]), target)',
    'if instructions[index].op == "label" and easm_equal(easm_label_name(instructions[index]), target):',
    "assert index < count",
    "found_index: i64 = index.i64()",
    "assert found_index >= 0",
    "assert found_index.usize() == index",
    "assert found_index.usize() < instructions.count",
    "assert found_index.usize().i64() == found_index",
    'assert forall prior in 0..<index: instructions[prior].op != "label" or not easm_equal(easm_label_name(instructions[prior]), target)',
    "return found_index",
    'assert instructions[index].op != "label" or not easm_equal(easm_label_name(instructions[index]), target)',
    'assert forall prior in 0..<(index + 1): instructions[prior].op != "label" or not easm_equal(easm_label_name(instructions[prior]), target)',
    'assert forall candidate in 0..<count: instructions[candidate].op != "label" or not easm_equal(easm_label_name(instructions[candidate]), target)',
)
positions = [lookup.find(compact(fragment)) for fragment in required_body]
if any(position < 0 for position in positions) or positions != sorted(positions) or not lookup.endswith("return-1"):
    raise SystemExit("EASM label lookup lost its checked count, loop invariant, or first-match implementation")

positive_names = {
    "a_found_label_index_is_in_range",
    "a_found_label_index_roundtrips_to_usize",
    "an_absent_label_returns_the_missing_sentinel",
    "an_unrepresentable_instruction_count_returns_the_missing_sentinel",
    "the_first_matching_label_is_selected",
    "an_empty_instruction_list_has_no_label_index",
    "an_empty_lookup_target_returns_the_missing_sentinel",
    "a_non_label_instruction_has_no_label_name",
    "a_label_without_a_terminal_colon_keeps_its_trimmed_name",
    "a_label_with_a_terminal_colon_drops_exactly_one",
}
negative_names = {
    "a_found_label_index_can_be_out_of_range",
    "an_absent_label_can_be_reported_as_found",
    "an_unrepresentable_instruction_count_can_return_a_label",
    "a_later_duplicate_label_can_be_selected",
    "an_empty_instruction_list_can_have_a_label_index",
    "an_empty_lookup_target_can_find_a_label",
    "a_non_label_instruction_can_have_a_label_name",
    "a_label_without_a_terminal_colon_can_change_its_trimmed_name",
    "a_label_with_a_terminal_colon_can_keep_the_colon",
}
positive_claims = {
    "a_found_label_index_is_in_range": "found < instructions.count.i64()",
    "a_found_label_index_roundtrips_to_usize": "found.usize().i64() == found",
    "an_absent_label_returns_the_missing_sentinel": "Easm::easm_label_index(instructions, target) == -1",
    "an_unrepresentable_instruction_count_returns_the_missing_sentinel": "Easm::easm_label_index(instructions, target) == -1",
    "the_first_matching_label_is_selected": "Easm::easm_label_index(instructions, target) == first.i64()",
    "an_empty_instruction_list_has_no_label_index": "Easm::easm_label_index(instructions, target) == -1",
    "an_empty_lookup_target_returns_the_missing_sentinel": 'Easm::easm_label_index(instructions, "") == -1',
    "a_non_label_instruction_has_no_label_name": "Easm::easm_label_name(instruction).len == 0",
    "a_label_without_a_terminal_colon_keeps_its_trimmed_name": "Easm::easm_label_name(instruction) == Easm::easm_trim(instruction.text)",
    "a_label_with_a_terminal_colon_drops_exactly_one": "Easm::easm_label_name(instruction) == Easm::easm_trim(trimmed[0:trimmed.len - 1.usize()])",
}
negative_claims = {
    "a_found_label_index_can_be_out_of_range": "found >= instructions.count.i64()",
    "an_absent_label_can_be_reported_as_found": "Easm::easm_label_index(instructions, target) >= 0",
    "an_unrepresentable_instruction_count_can_return_a_label": "Easm::easm_label_index(instructions, target) >= 0",
    "a_later_duplicate_label_can_be_selected": "Easm::easm_label_index(instructions, target) == later.i64()",
    "an_empty_instruction_list_can_have_a_label_index": "Easm::easm_label_index(instructions, target) >= 0",
    "an_empty_lookup_target_can_find_a_label": 'Easm::easm_label_index(instructions, "") >= 0',
    "a_non_label_instruction_can_have_a_label_name": "Easm::easm_label_name(instruction).len != 0",
    "a_label_without_a_terminal_colon_can_change_its_trimmed_name": "Easm::easm_label_name(instruction) != Easm::easm_trim(instruction.text)",
    "a_label_with_a_terminal_colon_can_keep_the_colon": "Easm::easm_label_name(instruction) == Easm::easm_trim(instruction.text)",
}
positive_preconditions = {
    "a_found_label_index_is_in_range": "requires Easm::easm_label_index(instructions, target) >= 0",
    "a_found_label_index_roundtrips_to_usize": "requires Easm::easm_label_index(instructions, target) >= 0",
    "an_absent_label_returns_the_missing_sentinel": "requires instructions.count.i64() >= 0 and instructions.count.i64().usize() == instructions.count requires target.len > 0 requires forall candidate in 0..<instructions.count.i64(): Easm::easm_label_name(instructions[candidate.usize()]) != target",
    "an_unrepresentable_instruction_count_returns_the_missing_sentinel": "requires instructions.count.i64() < 0 or instructions.count.i64().usize() != instructions.count",
    "the_first_matching_label_is_selected": 'requires instructions.count.i64() >= 0 and instructions.count.i64().usize() == instructions.count requires target.len > 0 requires first < later and later < instructions.count requires instructions[first].op == "label" and instructions[later].op == "label" requires forall prior in 0..<first: Easm::easm_label_name(instructions[prior]) != target requires Easm::easm_label_name(instructions[first]) == target requires Easm::easm_label_name(instructions[later]) == target',
    "an_empty_instruction_list_has_no_label_index": "",
    "an_empty_lookup_target_returns_the_missing_sentinel": "",
    "a_non_label_instruction_has_no_label_name": 'requires instruction.op != "label"',
    "a_label_without_a_terminal_colon_keeps_its_trimmed_name": 'requires instruction.op == "label" requires Easm::easm_trim(instruction.text).len == 0 or Easm::easm_trim(instruction.text)[Easm::easm_trim(instruction.text).len - 1.usize()] != 58',
    "a_label_with_a_terminal_colon_drops_exactly_one": 'requires instruction.op == "label" requires Easm::easm_trim(instruction.text).len > 0 requires Easm::easm_trim(instruction.text)[Easm::easm_trim(instruction.text).len - 1.usize()] == 58',
}
negative_preconditions = {
    "a_found_label_index_can_be_out_of_range": "requires Easm::easm_label_index(instructions, target) >= 0",
    "an_absent_label_can_be_reported_as_found": "requires instructions.count.i64() >= 0 and instructions.count.i64().usize() == instructions.count requires target.len > 0 requires forall candidate in 0..<instructions.count.i64(): Easm::easm_label_name(instructions[candidate.usize()]) != target",
    "an_unrepresentable_instruction_count_can_return_a_label": "requires instructions.count.i64() < 0 or instructions.count.i64().usize() != instructions.count",
    "a_later_duplicate_label_can_be_selected": 'requires instructions.count.i64() >= 0 and instructions.count.i64().usize() == instructions.count requires target.len > 0 requires first < later and later < instructions.count requires instructions[first].op == "label" and instructions[later].op == "label" requires forall prior in 0..<first: Easm::easm_label_name(instructions[prior]) != target requires Easm::easm_label_name(instructions[first]) == target requires Easm::easm_label_name(instructions[later]) == target',
    "an_empty_instruction_list_can_have_a_label_index": "",
    "an_empty_lookup_target_can_find_a_label": "",
    "a_non_label_instruction_can_have_a_label_name": 'requires instruction.op != "label"',
    "a_label_without_a_terminal_colon_can_change_its_trimmed_name": 'requires instruction.op == "label" requires Easm::easm_trim(instruction.text).len == 0 or Easm::easm_trim(instruction.text)[Easm::easm_trim(instruction.text).len - 1.usize()] != 58',
    "a_label_with_a_terminal_colon_can_keep_the_colon": 'requires instruction.op == "label" requires Easm::easm_trim(instruction.text).len > 0 requires Easm::easm_trim(instruction.text)[Easm::easm_trim(instruction.text).len - 1.usize()] == 58',
}

for source_text, names, label in (
    (positive_text, positive_names, "positive"),
    (negative_text, negative_names, "negative"),
):
    if declarations(source_text) != names:
        raise SystemExit(f"{label} EASM label-lookup theorem inventory changed")
    if 'include "../../src/backend/easm_model.elisa"' not in source_text:
        raise SystemExit(f"{label} EASM label-lookup proofs no longer include the production model")
for source_text, claims, requirements, label in (
    (positive_text, positive_claims, positive_preconditions, "positive"),
    (negative_text, negative_claims, negative_preconditions, "negative"),
):
    if set(claims) != set(requirements):
        raise SystemExit(f"{label} EASM label-lookup claim and precondition inventories differ")
    for name in claims:
        section = compact(function_section(source_text, name))
        if compact("ensure result == true") not in section \
                or compact(claims[name]) not in section \
                or (requirements[name] and compact(requirements[name]) not in section):
            raise SystemExit(f"EASM label-lookup theorem {name} lost its claim or precondition")

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
    raise SystemExit("EASM label-lookup proofs require a strict proof build")

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
    "scope": "EASM label lookup is representable, bounded, first-match, and fail-closed on absent or oversized collections",
    "positive_claims_proved": sorted(positive_names),
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
