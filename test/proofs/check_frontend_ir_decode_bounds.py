"""Admit frontend-IR bounds and narrowing proofs against a strict Elisa-proof product."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
POSITIVE = HERE / "frontend_ir_decode_bounds.elisa"
NEGATIVE = HERE / "frontend_ir_decode_bounds_rejected.elisa"
BUDGET_POSITIVE = HERE / "frontend_ir_schema_budget.elisa"
BUDGET_NEGATIVE = HERE / "frontend_ir_schema_budget_rejected.elisa"
READER = ROOT / "src/driver/frontend_ir.elisa"
BOUNDS = ROOT / "src/driver/frontend_ir_bounds.elisa"
PROBE = ROOT / "test/parity/ir_reader_probe.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_body(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^[ \t]*def {re.escape(name)}\([^\n]*\)[^\n]*:\n(.*?)(?=^[ \t]*def |\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"could not locate production function {name}")
    return match.group(1)


reader = READER.read_text()
varint = compact(function_body(reader, "ir_uvarint"))
varint_checks = [
    "payload:u8=byte&0x7f",
    "falsereturnifnotfrontend_ir_varint_payload_fits(shift.u64(),payload.u64())",
    "result<-result|(payload.u64()<<shift.u64())",
]
varint_positions = [varint.find(fragment) for fragment in varint_checks]
if any(position < 0 for position in varint_positions) or varint_positions != sorted(varint_positions):
    raise SystemExit("uvarint decoding no longer rejects an oversized final 64-bit group before shifting")
varint_shift_checks = [
    "shift:mutableu32=0",
    "if(byte&0x80)==0:",
    "shift<-shift+7",
    "falsereturnifnotfrontend_ir_varint_continued_shift_fits(shift.u64())",
]
varint_shift_positions = [varint.find(fragment) for fragment in varint_shift_checks]
if any(position < 0 for position in varint_shift_positions) or varint_shift_positions != sorted(varint_shift_positions):
    raise SystemExit("continued varint groups no longer advance the shift before enforcing its 63-bit cap")
varint_cursor_checks = [
    "whileposition<data.count|",
    "byte:u8=data[position]",
    "position<-position+1",
]
varint_cursor_positions = [varint.find(fragment) for fragment in varint_cursor_checks]
if any(position < 0 for position in varint_cursor_positions) or varint_cursor_positions != sorted(varint_cursor_positions):
    raise SystemExit("uvarint byte loads and cursor advancement are no longer guarded by the input length")

span = compact(function_body(reader, "ir_span"))
span_checks = [
    "falsereturnifnotir_uvarint(data,offset,&length,&next)",
    "falsereturnifnext>data.count",
    "span_length:usize=length.usize()",
    "falsereturnifspan_length.u64()!=length",
    "falsereturnifnotfrontend_ir_span_length_fits((data.count-next).u64(),span_length.u64())",
    "out_next<-next+span_length",
]
span_positions = [span.find(fragment) for fragment in span_checks]
if any(position < 0 for position in span_positions) or span_positions != sorted(span_positions):
    raise SystemExit("IR span decoding no longer checks conversion and remaining length before endpoint addition")
if 'include "./frontend_ir_bounds.elisa"' not in reader:
    raise SystemExit("frontend IR reader no longer imports the verified bounds helpers")
helper = BOUNDS.read_text()
helper_compact = compact(helper)
helper_contracts = (
    "ensure result == (length <= remaining)",
    "ensure result == (value <= FRONTEND_IR_U32_MAX)",
    "ensure result == (count <= input_bytes)",
    "ensure result == (root > 0 and root <= node_count)",
    "ensure result == (version == FRONTEND_IR_SUPPORTED_VERSION)",
    "ensure result == (shift != 63 or payload <= 1)",
    "ensure result == (shift <= 63)",
    "ensure result == (offset < total)",
    "ensure result implies offset + 1 <= total",
    "ensure result == (depth > 0)",
    "ensure result implies depth - 1 < depth",
)
if any(compact(contract) not in helper_compact for contract in helper_contracts):
    raise SystemExit("frontend IR bound helper lost a production-linked postcondition")

reader_compact = compact(reader)
if "constFRONTEND_IR_U32_MAX:u64=4294967295" not in helper_compact:
    raise SystemExit("frontend IR helper lost the explicit u32 identifier bound")
if "constFRONTEND_IR_SUPPORTED_VERSION:u64=2" not in helper_compact:
    raise SystemExit("frontend IR helper lost the supported wire version")
if len(re.findall(r"\.u32\(\)", reader)) != 6 or len(re.findall(r"\.usize\(\)", reader)) != 7:
    raise SystemExit("frontend IR reader added or removed a narrowing cast; review its range proof")
for function_name, guard, narrowing in (
    ("ir_read_type_fields", "notfrontend_ir_u32_value_fits(field_id)", "field_id.u32()"),
    ("ir_read_one_type", "notfrontend_ir_u32_value_fits(type_id)", "type_id.u32()"),
    ("ir_read_node_fields", "notfrontend_ir_u32_value_fits(field_id)", "field_id.u32()"),
    ("ir_read_node_body", "notfrontend_ir_u32_value_fits(type_id)", "type_id.u32()"),
):
    body = compact(function_body(reader, function_name))
    if body.find(guard) < 0 or body.find(narrowing) < body.find(guard):
        raise SystemExit(f"{function_name} no longer checks u32 identifier range before narrowing")
for function_name in ("ir_read_type_table", "ir_read_node_table"):
    body = compact(function_body(reader, function_name))
    guard = "notfrontend_ir_count_fits_input(count,data.count.u64())"
    if body.find(guard) < 0 or body.find("count.usize()") < body.find(guard):
        raise SystemExit(f"{function_name} no longer bounds its usize loop count by input length")
for function_name in ("ir_read_one_type", "ir_read_node_body"):
    body = compact(function_body(reader, function_name))
    guard = "notfrontend_ir_count_fits_input(field_count,data.count.u64())"
    if body.find(guard) < 0 or body.find("field_count.usize()") < body.find(guard):
        raise SystemExit(f"{function_name} no longer bounds its usize field count by input length")
root_reader = compact(function_body(reader, "ir_read_root"))
root_checks = (
    "notfrontend_ir_u32_value_fits(root)",
    "notfrontend_ir_root_is_valid(root,bundle.nodes.count.u64())",
    "bundle.root<-root.u32()",
)
root_positions = [root_reader.find(fragment) for fragment in root_checks]
if any(position < 0 for position in root_positions) or root_positions != sorted(root_positions):
    raise SystemExit("root references are no longer range checked before bounds validation and u32 narrowing")
bundle_parser = compact(function_body(reader, "ir_bundle_parse"))
version_guard = "ifnotfrontend_ir_version_is_supported(version)"
if bundle_parser.find(version_guard) < 0 or bundle_parser.find("bundle.version<-version.u32()") < bundle_parser.find(version_guard):
    raise SystemExit("bundle version is narrowed before the exact supported-version check")

node_table = compact(function_body(reader, "ir_read_node_table"))
if "ir_span(data,position,&body_start,&body_length,&position)" not in node_table:
    raise SystemExit("node bodies no longer obtain their bounds through the checked span decoder")
if "ir_read_node_body(data,body_start,body_start+body_length,bundle)" not in node_table:
    raise SystemExit("node body endpoint no longer consumes the checked start/length pair")
schema = compact(function_body(reader, "ir_skip_value_schema"))
schema_tag_checks = (
    "decreasesremaining_depth",
    "falsereturnifnotfrontend_ir_schema_budget_step_fits(remaining_depth.u64())",
    "falsereturnifnotfrontend_ir_cursor_step_fits(data.count.u64(),offset.u64())",
    "kind:u8=data[offset]",
    "next:mutableusize=offset+1",
    "ifkind==5:",
    "ifkind==6:",
    "ifkind==7:",
    "out_kind<-kind",
    "out_next<-next",
    "returntrue",
)
schema_tag_positions = [schema.find(fragment) for fragment in schema_tag_checks]
if any(position < 0 for position in schema_tag_positions) or schema_tag_positions != sorted(schema_tag_positions):
    raise SystemExit("schema skipping no longer bounds recursion and checks the tag before advancing")
type_fields = compact(function_body(reader, "ir_read_type_fields"))
if "ir_skip_value_schema(data,position,&kind,&position,data.count)" not in type_fields:
    raise SystemExit("schema recursion no longer starts with an input-sized depth budget")
recursive_call = "falsereturnifnotir_skip_value_schema(data,next,&inner,&next,remaining_depth-1)"
list_branch = schema.find("ifkind==5:")
map_branch = schema.find("ifkind==6:")
inline_branch = schema.find("ifkind==7:")
list_child = schema.find(recursive_call, list_branch)
map_first_child = schema.find(recursive_call, map_branch)
map_second_child = schema.find(recursive_call, map_first_child + len(recursive_call))
inline_span = schema.find("falsereturnifnotir_span(data,next,&name_start,&name_length,&next)", inline_branch)
if not (list_branch < list_child < map_branch < map_first_child < map_second_child < inline_branch < inline_span):
    raise SystemExit("schema list/map children or inline-struct span no longer use checked recursive cursor updates")
if schema.count(recursive_call) != 3:
    raise SystemExit("schema skipper no longer has exactly one list child and two map child decodes")
if 'include "../../src/driver/frontend_ir.elisa"' not in PROBE.read_text():
    raise SystemExit("the interoperability probe no longer exercises the production IR reader")
if 'include "../../src/driver/frontend_ir_bounds.elisa"' not in POSITIVE.read_text():
    raise SystemExit("the proof file no longer verifies the production bound helpers")
expected_positive = {
    "bounded_sum_fits_data",
    "span_length_beyond_remaining_fails",
    "span_start_beyond_data_fails",
    "last_varint_group_accepts_only_one_payload_bit",
    "high_last_group_payload_is_rejected",
    "a_continued_tenth_varint_byte_is_rejected",
    "u32_identifier_in_range_satisfies_guard",
    "oversized_u32_identifier_fails_the_guard",
    "table_count_within_input_bytes_is_admissible",
    "table_count_larger_than_input_bytes_is_rejected",
    "nonzero_root_within_node_table_is_admissible",
    "zero_root_is_rejected",
    "root_after_node_table_is_rejected",
    "root_larger_than_u32_is_rejected",
    "supported_ir_version_is_admitted",
    "unsupported_ir_version_is_rejected",
    "guarded_cursor_step_stays_in_input",
    "guarded_cursor_step_strictly_reduces_remaining_input",
    "list_child_tag_is_rejected_when_only_one_byte_remains",
    "map_child_is_rejected_when_only_two_bytes_remain",
    "continued_tenth_varint_group_exceeds_shift_limit",
    "continuation_before_tenth_group_stays_within_shift_limit",
    "frontend_ir_span_length_fits",
    "frontend_ir_u32_value_fits",
    "frontend_ir_count_fits_input",
    "frontend_ir_root_is_valid",
    "frontend_ir_version_is_supported",
    "frontend_ir_varint_payload_fits",
    "frontend_ir_varint_continued_shift_fits",
    "frontend_ir_cursor_step_fits",
    "frontend_ir_schema_budget_step_fits",
}
expected_negative = {
    "oversized_span_is_admitted",
    "high_tenth_byte_payload_is_admitted",
    "continued_tenth_byte_is_admitted",
    "oversized_u32_identifier_is_accepted",
    "oversized_table_count_is_accepted",
    "zero_root_is_accepted",
    "root_after_node_table_is_accepted",
    "unsupported_ir_version_is_admitted",
    "schema_tag_cursor_can_advance_past_input",
    "truncated_list_with_no_child_is_admitted",
    "truncated_map_with_one_child_tag_is_admitted",
    "continued_tenth_varint_group_stays_within_shift_limit",
    "continuation_before_tenth_group_can_exceed_shift_limit",
}
positive_declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", POSITIVE.read_text()))
negative_declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", NEGATIVE.read_text()))
helper_names = {
    "frontend_ir_span_length_fits",
    "frontend_ir_u32_value_fits",
    "frontend_ir_count_fits_input",
    "frontend_ir_root_is_valid",
    "frontend_ir_version_is_supported",
    "frontend_ir_varint_payload_fits",
    "frontend_ir_varint_continued_shift_fits",
    "frontend_ir_cursor_step_fits",
    "frontend_ir_schema_budget_step_fits",
}
budget_positive_declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", BUDGET_POSITIVE.read_text()))
budget_negative_declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", BUDGET_NEGATIVE.read_text()))
if budget_positive_declarations != {
    "positive_schema_budget_has_a_smaller_recursive_budget",
    "zero_schema_budget_is_rejected",
}:
    raise SystemExit("schema recursion budget proof declaration inventory changed")
if budget_negative_declarations != {"zero_schema_budget_is_admitted"}:
    raise SystemExit("schema recursion budget counterexample inventory changed")
if positive_declarations != expected_positive - helper_names or negative_declarations != expected_negative:
    raise SystemExit("frontend-IR bounds proof declaration inventory changed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("frontend-IR bounds proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    READER,
    BOUNDS,
    PROBE,
    BUDGET_POSITIVE,
    BUDGET_NEGATIVE,
]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE, BUDGET_POSITIVE, BUDGET_NEGATIVE]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"] == 64
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert verified == expected_positive

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] == 26 and negative["summary"]["proven"] == 13
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in expected_negative
}
assert not expected_negative & {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}

code, budget_positive = run(BUDGET_POSITIVE)
assert code == 0 and budget_positive["status"] == budget_positive["verification_state"] == "proved"
assert budget_positive["summary"]["proven"] == budget_positive["summary"]["obligations"] == 24
assert not budget_positive["findings"]
budget_verified = {
    row["name"] for row in budget_positive["declaration_details"] if row.get("verified")
}
assert budget_verified == helper_names | budget_positive_declarations

code, budget_negative = run(BUDGET_NEGATIVE)
assert code == 1 and budget_negative["status"] == "failed"
assert budget_negative["summary"]["obligations"] == 22 and budget_negative["summary"]["proven"] == 10
assert {(finding["kind"], finding["name"]) for finding in budget_negative["findings"]} == {
    ("ensure-unproven", "zero_schema_budget_is_admitted")
}
assert not {"zero_schema_budget_is_admitted"} & {
    row["name"] for row in budget_negative["declaration_details"] if row.get("verified")
}

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "production-linked span, varint, tag cursor, schema recursion budget, ID narrowing, count, root, and version predicates; arithmetic models for schema recursion progress",
    "positive_obligations": positive["summary"]["proven"],
    "schema_budget_positive_obligations": budget_positive["summary"]["proven"],
    "schema_budget_false_claims_rejected": ["zero_schema_budget_is_admitted"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
