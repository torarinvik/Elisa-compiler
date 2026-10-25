"""Bind StringView index postconditions and proof claims to runtime helpers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


from source_guard_compat import expand_return_if_blocks
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
PRELUDE = ROOT / "elisacore_std/elisacore_runtime_prelude.elisa"
RUNTIME_STRINGS = ROOT / "elisacore_std/elisacore_runtime_strings.elisa"
TYPE_INFERENCE = ROOT / "src/semantic/resolve_types_infer.elisa"
FIELD_LOWERING = ROOT / "src/backend/codegen_expr_field_read.elisa"
INDEX_LOWERING = ROOT / "src/backend/codegen_expr_index_read.elisa"
INDEX_EMITTER = ROOT / "src/backend/codegen_expr_index_read_emit.elisa"
INDEX_MODULE_ROOT = ROOT / "src/backend/codegen_expr_index_fields.elisa"
DECIMAL_PARSER = ROOT / "src/backend/easm_checked_decimal.elisa"
POSITIVE = HERE / "sview_index_contract.elisa"
NEGATIVE = HERE / "sview_index_contract_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking Elisa-Proof")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in expand_return_if_blocks(source).splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(
        rf"(?m)^{re.escape(indent)}(?:ghost[ \t]+)?def [A-Za-z_][A-Za-z0-9_]*\(",
        source[match.end():],
    )
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


runtime_text = RUNTIME_STRINGS.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
request_valid = compact(function_section(runtime_text, "string_view_index_request_valid"))
request_condition = (
    "view.len >= 0 and view.len.usize().i64() == view.len and index >= 0 "
    "and index < view.len and index.usize().i64() == index"
)
if compact(f"ensure result == ({request_condition})") not in request_valid \
        or compact(f"return ({request_condition})") not in request_valid:
    raise SystemExit("StringView index predicate lost a length, range, or conversion condition")

index_helper = compact(function_section(runtime_text, "string_view_index"))
required_index_contracts = (
    "ensure not string_view_index_request_valid(view, index) implies result == 0",
    "ensure string_view_index_request_valid(view, index) implies result == view.data[index.usize()].i64()",
    "ensure result >= 0 and result <= 255",
)
if any(compact(clause) not in index_helper for clause in required_index_contracts):
    raise SystemExit("StringView runtime index lost its rejected, selected-byte, or byte-width contract")
index_guards = (
    "return 0 if view.len < 0",
    "view_len: usize = view.len.usize()",
    "0 return if view_len.i64() != view.len",
    "0 return if index < 0 or index >= view.len",
    "index_usize: usize = index.usize()",
    "return 0 if index_usize.i64() != index",
    "return view.data[index_usize].i64()",
)
guard_positions = [index_helper.find(compact(guard)) for guard in index_guards]
if any(position < 0 for position in guard_positions) or guard_positions != sorted(guard_positions):
    raise SystemExit("StringView index no longer validates its domain before loading a byte")

if {"sview_len", "sview_at"} & declarations(runtime_text):
    raise SystemExit("legacy sview length/index wrappers remain in the runtime")

# The ergonomic source syntax used by the checked-decimal parser is an alias
# for the same StringView extent and bounded byte read specified above.
inference_text = compact(TYPE_INFERENCE.read_text())
if compact('"len" | "length" -> true') not in inference_text or \
        compact('return InferType{kind: SemTypeKind.Int, name: "i64"} if object_type.kind == SemTypeKind.String and object_type.name == "sview" and is_sview_size_field') not in inference_text:
    raise SystemExit("sview .len no longer resolves to the signed StringView extent")
field_lowering = compact(function_section(FIELD_LOWERING.read_text(), "emit_expression_field_read"))
if compact('"data" | "len" | "length" -> true') not in field_lowering or \
        compact('return LLVMBuildExtractValue(builder, sview_value, 1, "sview.len")') not in field_lowering:
    raise SystemExit("sview .len no longer reads the signed extent from its runtime pair")
index_lowering = compact(function_section(INDEX_LOWERING.read_text(), "emit_inline_sview_index"))
required_inline_guards = (
    'LLVMBuildICmp(builder, LLVMIntPredicate::SGE, length, zero, "sview.idx.len.ok")',
    'LLVMBuildICmp(builder, LLVMIntPredicate::ULT, index, length, "sview.idx.in")',
    'LLVMBuildAnd(builder, length_ok, index_ok, "sview.idx.ok")',
    'LLVMBuildCondBr(builder, in_range, read_block, join_block)',
    'LLVMBuildGEP2(builder, LLVMInt8TypeInContext(ctx), data, indices_pointer, 1, "sview.idx.ptr")',
    'LLVMBuildZExt(builder, byte, i64_type, "sview.idx.wide")',
)
inline_positions = [index_lowering.find(compact(fragment)) for fragment in required_inline_guards]
if any(position < 0 for position in inline_positions) or inline_positions != sorted(inline_positions):
    raise SystemExit("sview indexing no longer guards the byte load and zero-extends the selected byte")
index_dispatch = compact(function_section(INDEX_EMITTER.read_text(), "emit_expression_index_read"))
required_index_dispatch = (
    "if sview_index_recv_type.kind == TypeKind.SView:",
    "if structs.target.target_pointer_bits == 64:",
    "emit_inline_sview_index(sview_index_recv, sview_index_arg, ctx, builder)",
    "LLVMBuildCall2(builder, runtime.sview_index_type, runtime.sview_index, sview_index_args_pointer, 2, \"sview.index\")",
)
if any(compact(fragment) not in index_dispatch for fragment in required_index_dispatch):
    raise SystemExit("sview [index] no longer dispatches through the checked inline/runtime paths")
index_module_text = INDEX_MODULE_ROOT.read_text()
if index_module_text.count('include "./codegen_expr_index_read.elisa"') != 1 or \
        index_module_text.count('include "./codegen_expr_index_read_emit.elisa"') != 1:
    raise SystemExit("index lowering must include its inline helper and dispatcher exactly once")
decimal_source = DECIMAL_PARSER.read_text()
decimal_parser = compact(function_section(decimal_source, "parse_signed"))
decimal_reference = compact(function_section(decimal_source, "decimal_parse_reference"))
decimal_minus_guard = "iftext.len>0andtext[0]==EasmCheckedDecimal::ASCII_MINUS:"
decimal_reference_minus_branch = (
    "returndecimal_parse_reference_from(text,1,true,0,false)if"
    "text.len>0andtext[0]==EasmCheckedDecimal::ASCII_MINUS"
)
if decimal_minus_guard not in decimal_parser or decimal_reference_minus_branch not in decimal_reference:
    raise SystemExit("checked-decimal implementation and reference no longer use the guarded .len and [0] syntax")

find_byte = compact(function_section(runtime_text, "sview_find_byte"))
required_find_contracts = (
    "ensure (view.len < 0 or view.len.usize().i64() != view.len) implies result == -1",
    "ensure result >= -1",
    "ensure result >= 0 implies result < view.len",
    "ensure result >= 0 implies string_view_index(view, result) == byte.i64()",
    "ensure result >= 0 implies (forall prior in 0..<result: string_view_index(view, prior) != byte.i64())",
    "ensure (view.len >= 0 and view.len.usize().i64() == view.len and result == -1) implies (forall candidate in 0..<view.len: string_view_index(view, candidate) != byte.i64())",
)
if any(compact(clause) not in find_byte for clause in required_find_contracts):
    raise SystemExit("sview_find_byte lost its sentinel, first-match, or absence postcondition")
find_loop_obligations = (
    "decreases view.len - i",
    "invariant 0 <= i and i <= view.len",
    "invariant forall prior in 0..<i: string_view_index(view, prior) != byte.i64()",
)
find_loop_positions = [find_byte.find(compact(obligation)) for obligation in find_loop_obligations]
if any(position < 0 for position in find_loop_positions) or find_loop_positions != sorted(find_loop_positions):
    raise SystemExit("sview_find_byte lost its progress, range, or first-match loop invariant")

positive_names = {
    "an_in_range_view_index_reads_its_backing_byte",
    "every_rejected_view_index_reads_zero",
    "a_found_byte_is_the_first_matching_offset",
    "an_absent_byte_returns_the_missing_sentinel",
    "an_unrepresentable_view_length_returns_the_missing_sentinel",
    "len_field_matches_its_signed_value_on_valid_views",
    "positive_length_guard_makes_the_first_index_valid",
    "guarded_first_byte_syntax_matches_the_safe_helper",
}
negative_names = {
    "invalid_view_index_can_read_a_nonzero_byte",
    "valid_view_index_can_read_a_different_byte",
    "search_can_skip_an_earlier_matching_byte",
    "invalid_view_length_can_return_a_found_offset",
    "a_negative_len_field_matches_its_signed_value",
    "an_out_of_range_index_can_disagree_with_the_safe_helper",
}
positive_claims = {
    "an_in_range_view_index_reads_its_backing_byte": "view[index] == view.data[index]",
    "every_rejected_view_index_reads_zero": "view[index] == 0",
    "a_found_byte_is_the_first_matching_offset": "found < view.len and string_view_index(view, found) == byte.i64() and (forall prior in 0..<found: string_view_index(view, prior) != byte.i64())",
    "an_absent_byte_returns_the_missing_sentinel": "sview_find_byte(view, byte) == -1",
    "an_unrepresentable_view_length_returns_the_missing_sentinel": "sview_find_byte(view, byte) == -1",
    "len_field_matches_its_signed_value_on_valid_views": "view.len == view.len.i64()",
    "positive_length_guard_makes_the_first_index_valid": "string_view_index_request_valid(view, 0)",
    "guarded_first_byte_syntax_matches_the_safe_helper": "view[0] == view[0.usize()].i64()",
}
negative_claims = {
    "invalid_view_index_can_read_a_nonzero_byte": "view[index] != 0",
    "valid_view_index_can_read_a_different_byte": "view[index] != view.data[index]",
    "search_can_skip_an_earlier_matching_byte": "sview_find_byte(view, byte) == later",
    "invalid_view_length_can_return_a_found_offset": "sview_find_byte(view, byte) >= 0",
    "a_negative_len_field_matches_its_signed_value": "view.len == view.len.i64()",
    "an_out_of_range_index_can_disagree_with_the_safe_helper": "view[index] != view[index].i64()",
}
preconditions = {
    "an_in_range_view_index_reads_its_backing_byte":
        "requires string_view_index_request_valid(view, index.i64())",
    "every_rejected_view_index_reads_zero":
        "requires not string_view_index_request_valid(view, index.i64())",
    "a_found_byte_is_the_first_matching_offset":
        "requires view.len >= 0 and view.len.usize().i64() == view.len requires sview_find_byte(view, byte) >= 0",
    "an_absent_byte_returns_the_missing_sentinel":
        "requires view.len >= 0 and view.len.usize().i64() == view.len requires forall candidate in 0..<view.len: string_view_index(view, candidate) != byte.i64()",
    "an_unrepresentable_view_length_returns_the_missing_sentinel":
        "requires view.len < 0 or view.len.usize().i64() != view.len",
    "len_field_matches_its_signed_value_on_valid_views":
        "requires view.len >= 0 and view.len.usize().i64() == view.len",
    "positive_length_guard_makes_the_first_index_valid":
        "requires view.len > 0 and view.len.usize().i64() == view.len",
    "guarded_first_byte_syntax_matches_the_safe_helper":
        "requires view.len > 0 and view.len.usize().i64() == view.len",
}
negative_preconditions = {
    "invalid_view_index_can_read_a_nonzero_byte":
        "requires not string_view_index_request_valid(view, index.i64())",
    "valid_view_index_can_read_a_different_byte":
        "requires string_view_index_request_valid(view, index.i64())",
    "search_can_skip_an_earlier_matching_byte":
        "requires view.len >= 0 and view.len.usize().i64() == view.len requires earlier >= 0 and earlier < later and later < view.len requires string_view_index(view, earlier) == byte.i64() requires string_view_index(view, later) == byte.i64()",
    "invalid_view_length_can_return_a_found_offset":
        "requires view.len < 0 or view.len.usize().i64() != view.len",
    "a_negative_len_field_matches_its_signed_value":
        "requires view.len < 0",
    "an_out_of_range_index_can_disagree_with_the_safe_helper":
        "requires not string_view_index_request_valid(view, index.i64())",
}
for source_text, names, label in (
    (positive_text, positive_names, "positive"),
    (negative_text, negative_names, "negative"),
):
    if declarations(source_text) != names:
        raise SystemExit(f"{label} StringView index theorem inventory changed")
    if 'include "../../elisacore_std/elisacore_runtime_prelude.elisa"' not in source_text \
            or 'include "../../elisacore_std/elisacore_runtime_strings.elisa"' not in source_text:
        raise SystemExit(f"{label} StringView index proofs no longer include the production helper")
for names, claims, requirements, source_text, label in (
    (positive_names, positive_claims, preconditions, positive_text, "positive"),
    (negative_names, negative_claims, negative_preconditions, negative_text, "negative"),
):
    if set(claims) != names or set(requirements) != names:
        raise SystemExit(f"{label} StringView index claims no longer cover their inventory")
    for name in names:
        section = compact(function_section(source_text, name))
        if compact("ensure result == true") not in section \
                or compact(claims[name]) not in section \
                or compact(requirements[name]) not in section:
            raise SystemExit(f"StringView index theorem {name} lost its claim or precondition")

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
    raise SystemExit("StringView index contracts require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", PRELUDE, RUNTIME_STRINGS,
    TYPE_INFERENCE, FIELD_LOWERING, INDEX_LOWERING, INDEX_EMITTER,
    INDEX_MODULE_ROOT, DECIMAL_PARSER,
    POSITIVE, NEGATIVE, *source_closure,
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
    "scope": "StringView runtime index preserves the guarded byte read and returns zero outside the valid logical range",
    "positive_claims_proved": sorted(positive_names),
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
