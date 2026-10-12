"""Admit overflow-safe bounds checks for generic-call parameter slices."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
SOURCE = ROOT / "src/backend/codegen_generic_call.elisa"
POSITIVE = HERE / "backend_generic_call_slice_bounds.elisa"
NEGATIVE = HERE / "backend_generic_call_slice_bounds_rejected.elisa"
POSITIVE_NAMES = {
    "subtraction_guard_bounds_each_slice_index",
    "one_past_slice_length_is_rejected",
    "empty_slice_at_pool_end_has_no_valid_offset",
    "row_round_trip_preserves_a_bounded_signed_index",
    "mismatched_row_round_trip_is_rejected",
    "generic_slot_round_trip_preserves_selected_entry",
}
NEGATIVE_NAMES = {
    "false_claim_one_past_offset_is_inside_the_slice",
    "false_claim_narrowed_row_still_identifies_the_original",
    "false_claim_narrowed_generic_slot_keeps_its_name",
}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


matcher = compact(function_section(SOURCE.read_text(), "generic_call_function_row_matches"))
slice_steps = (
    "expected_start:usize=structs.function_types.fn_pool_param_start[fn_slot]",
    "row_start:usize=fns.param_start[row_index]",
    "falsereturnifexpected_start>structs.function_types.fn_pool_params.count",
    "falsereturnifparam_count>structs.function_types.fn_pool_params.count-expected_start",
    "falsereturnifrow_start>fns.param_types.count",
    "falsereturnifparam_count>fns.param_types.count-row_start",
    "forparam_offsetin0..<param_count|expected_start,row_start,structs,fns|:",
    "fns.param_types[row_start+param_offset]",
    "structs.function_types.fn_pool_params[expected_start+param_offset]",
)
slice_positions = [matcher.find(step) for step in slice_steps]
if any(position < 0 for position in slice_positions) or slice_positions != sorted(slice_positions):
    raise SystemExit("generic-call parameter reads must follow subtraction-based slice guards")
if matcher.count("fns.param_types[row_start+param_offset]") != 1 or \
        matcher.count("structs.function_types.fn_pool_params[expected_start+param_offset]") != 1:
    raise SystemExit("generic-call matcher parameter reads changed without updating the bounds proof")
if "expected_start+param_count>" in matcher or "row_start+param_count>" in matcher:
    raise SystemExit("generic-call matcher reintroduced overflow-prone end-index additions")

row_steps = (
    "falsereturnifrow<0",
    "row_index:usize=row.usize()",
    "falsereturnifrow_index.i64()!=row",
    "falsereturnifrow_index>=fns.handles.count",
    "row_start:usize=fns.param_start[row_index]",
)
row_positions = [matcher.find(step) for step in row_steps]
if any(position < 0 for position in row_positions) or row_positions != sorted(row_positions):
    raise SystemExit("signed function-row conversion must round-trip before usize-indexed reads")
if matcher.count("row.usize()") != 1:
    raise SystemExit("generic-call row conversion must be captured once and reused after its round-trip guard")

caller = compact(function_section(SOURCE.read_text(), "emit_generic_call"))
caller_steps = (
    "generic_call_function_row_matches(fn_value_row,wanted,fns,structs)",
    "fn_value_row_index:usize=fn_value_row.usize()",
    "nullreturniffn_value_row_index.i64()!=fn_value_row",
    "argument_values.push(fns.handles[fn_value_row_index])",
)
caller_positions = [caller.find(step) for step in caller_steps]
if any(position < 0 for position in caller_positions) or caller_positions != sorted(caller_positions):
    raise SystemExit("generic-call handle lookup must repeat the row round-trip guard at its use site")
if "fns.handles[fn_value_row.usize()]" in caller:
    raise SystemExit("generic-call handle lookup must use the checked usize row")

slot_helper = compact(function_section(SOURCE.read_text(), "emit_generic_call_at_slot"))
slot_helper_steps = (
    "nullreturnifslot<0",
    "slot_index:usize=slot.usize()",
    "nullreturnifslot_index.i64()!=slot",
    "nullreturnifslot_index>=generics.names.count",
    "nullreturnifgenerics.names[slot_index]!=base",
    "nullreturnifslot_index>=generics.owners.count",
    "emit_generic_call(base,type_args,arguments,argument_names,local_scope,fns,structs,generics,runtime,m,ctx,builder,slot_index.i64())",
)
slot_helper_positions = [slot_helper.find(step) for step in slot_helper_steps]
if any(position < 0 for position in slot_helper_positions) or slot_helper_positions != sorted(slot_helper_positions):
    raise SystemExit("explicit generic slots must round-trip and match the selected name before forwarding")
if slot_helper.count("slot.usize()") != 1:
    raise SystemExit("explicit generic slot conversion must be captured once")

generic_call = compact(function_section(SOURCE.read_text(), "emit_generic_call"))
generic_call_steps = (
    "call_generic_slot:i64=slot_hintifslot_hint>=0elsegeneric_index_of(generics,base)",
    "nullreturnifcall_generic_slot<0",
    "call_generic_slot_index:usize=call_generic_slot.usize()",
    "nullreturnifcall_generic_slot_index.i64()!=call_generic_slot",
    "nullreturnifcall_generic_slot_index>=generics.is_error.count",
    "nullreturnifgenerics.is_error[call_generic_slot_index]",
    "instantiate_generic_at(call_generic_slot_index,type_args,generics,structs,m,ctx)",
)
generic_call_positions = [generic_call.find(step) for step in generic_call_steps]
if any(position < 0 for position in generic_call_positions) or generic_call_positions != sorted(generic_call_positions):
    raise SystemExit("generic instantiation must validate the signed slot before its table reads")
if generic_call.count("call_generic_slot.usize()") != 1:
    raise SystemExit("generic instantiation must reuse its checked usize slot after the initial conversion")

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("generic-call slice proof inventory changed")
if 'include "./backend_generic_call_slice_bounds.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative control no longer includes the admitted slice bounds proof")

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("generic-call slice proof requires a strict proof build")
stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    SOURCE,
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(POSITIVE_NAMES)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_NAMES) + len(NEGATIVE_NAMES)
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "generic-call function parameter reads remain within both parallel parameter slices",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
