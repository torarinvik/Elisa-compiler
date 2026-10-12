"""Admit source-linked proofs for frontend IR scalar literal payload encodings."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "frontend_ir_expression_literals.elisa"
NEGATIVE = HERE / "frontend_ir_expression_literals_rejected.elisa"
ENCODING = ROOT / "src/driver/frontend_ir_expression_literal_encoding.elisa"
WRITER = ROOT / "src/driver/frontend_ir_write.elisa"
EXPR_WRITER = ROOT / "src/driver/frontend_ir_expr.elisa"
TYPE_TABLE = ROOT / "src/driver/frontend_ir_type_table_2.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    without_comments = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    return re.sub(r"\s+", "", without_comments)


def function_chunk(text: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}\s*\(", text)
    if not match:
        raise SystemExit(f"missing function {name}")
    following = re.search(r"(?m)^[ \t]*def ", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


def literal_arm(expression_body: str, variant: str) -> str:
    lines = expression_body.splitlines()
    starts = [index for index, line in enumerate(lines) if line.lstrip().startswith(f"Ast::Expr.{variant}(")]
    if len(starts) != 1:
        raise SystemExit(f"expected one Ast::Expr.{variant} arm in the writer")
    start = starts[0]
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        current_indent = len(line) - len(line.lstrip())
        if current_indent == indent and (line.lstrip().startswith("Ast::Expr.") or line.lstrip() == "_:"):
            end = index
            break
    return "\n".join(lines[start:end])


STRING_WIRE_SCHEMA_TAG = "3"
BOOL_WIRE_SCHEMA_TAG = "1"
SCHEMA_INT_LIT_NODE_TYPE_ID = 139
SCHEMA_FLOAT_LIT_NODE_TYPE_ID = 67
SCHEMA_STRING_LIT_NODE_TYPE_ID = 253
SCHEMA_CHAR_LIT_NODE_TYPE_ID = 28
SCHEMA_BOOL_LIT_NODE_TYPE_ID = 18
SCHEMA_INT_LIT_VALUE_FIELD_ID = 4
SCHEMA_FLOAT_LIT_VALUE_FIELD_ID = 3
SCHEMA_STRING_LIT_VALUE_FIELD_ID = 2
SCHEMA_CHAR_LIT_VALUE_FIELD_ID = 2
SCHEMA_BOOL_LIT_VALUE_FIELD_ID = 2
KINDS = {
    "IntLit": (SCHEMA_INT_LIT_NODE_TYPE_ID, SCHEMA_INT_LIT_VALUE_FIELD_ID, STRING_WIRE_SCHEMA_TAG, "ir_put_str", "bytes_view_range(digits, 0, digits.count)"),
    "FloatLit": (SCHEMA_FLOAT_LIT_NODE_TYPE_ID, SCHEMA_FLOAT_LIT_VALUE_FIELD_ID, STRING_WIRE_SCHEMA_TAG, "ir_put_str", "text"),
    "StringLit": (SCHEMA_STRING_LIT_NODE_TYPE_ID, SCHEMA_STRING_LIT_VALUE_FIELD_ID, STRING_WIRE_SCHEMA_TAG, "ir_put_str", "text"),
    "CharLit": (SCHEMA_CHAR_LIT_NODE_TYPE_ID, SCHEMA_CHAR_LIT_VALUE_FIELD_ID, STRING_WIRE_SCHEMA_TAG, "ir_put_str", "text"),
    "BoolLit": (SCHEMA_BOOL_LIT_NODE_TYPE_ID, SCHEMA_BOOL_LIT_VALUE_FIELD_ID, BOOL_WIRE_SCHEMA_TAG, "ir_put_bool", "value"),
}
tag_names = {
    "IntLit": "INT_LIT_NODE_TYPE_ID",
    "FloatLit": "FLOAT_LIT_NODE_TYPE_ID",
    "StringLit": "STRING_LIT_NODE_TYPE_ID",
    "CharLit": "CHAR_LIT_NODE_TYPE_ID",
    "BoolLit": "BOOL_LIT_NODE_TYPE_ID",
}
field_names = {
    "IntLit": "INT_LIT_VALUE_FIELD_ID",
    "FloatLit": "FLOAT_LIT_VALUE_FIELD_ID",
    "StringLit": "STRING_LIT_VALUE_FIELD_ID",
    "CharLit": "CHAR_LIT_VALUE_FIELD_ID",
    "BoolLit": "BOOL_LIT_VALUE_FIELD_ID",
}
wire_names = {
    STRING_WIRE_SCHEMA_TAG: ("STRING_VALUE_WIRE_TYPE_ID", "EXPECTED_STRING_VALUE_WIRE_TYPE_ID"),
    BOOL_WIRE_SCHEMA_TAG: ("BOOL_VALUE_WIRE_TYPE_ID", "EXPECTED_BOOL_VALUE_WIRE_TYPE_ID"),
}

encoding_text = ENCODING.read_text()
writer_text = WRITER.read_text()
expr_text = EXPR_WRITER.read_text()
table_text = TYPE_TABLE.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

for variant, (node_id, field_id, wire_type, _, _) in KINDS.items():
    for suffix, name, expected in (
        ("NODE_TYPE_ID", tag_names[variant], node_id),
        ("VALUE_FIELD_ID", field_names[variant], field_id),
    ):
        declaration = re.search(rf"(?m)^\s*const {name}: u32 = ([0-9]+)\s*$", encoding_text)
        proof_declaration = re.search(rf"(?m)^const EXPECTED_{name}: u32 = ([0-9]+)\s*$", positive_text)
        if declaration is None or int(declaration.group(1)) != expected:
            raise SystemExit(f"production constant {name} no longer matches the stage0 schema")
        if proof_declaration is None or int(proof_declaration.group(1)) != expected:
            raise SystemExit(f"independent proof constant EXPECTED_{name} changed")

    type_marker = re.search(rf"(?m)^\s*# {variant} \(type {node_id}\)\s*$", table_text)
    if type_marker is None:
        raise SystemExit(f"stage0 type table lost {variant} type ID {node_id}")
    following = re.search(r"(?m)^\s*# [A-Za-z][A-Za-z0-9]* \(type [0-9]+\)\s*$", table_text[type_marker.end():])
    block = table_text[type_marker.start():type_marker.end() + following.start()] if following else table_text[type_marker.start():]
    node_name = compact(f'ir_uvarint_out(buffer, {node_id})\n                ir_str_out(buffer, "{variant}")')
    value_schema = compact(f'ir_field_desc_out(buffer, {field_id}, "Value")\n                buffer.push({wire_type})')
    if node_name not in compact(block) or value_schema not in compact(block):
        raise SystemExit(f"stage0 {variant} node or Value field schema changed")

wire_mapping = compact(function_chunk(encoding_text, "value_wire_type_id"))
for variant, (_, _, wire_type, _, _) in KINDS.items():
    production_wire_name, proof_wire_name = wire_names[wire_type]
    arm = compact(f"ScalarLiteralKind.{variant}: {production_wire_name}")
    if arm not in wire_mapping:
        raise SystemExit(f"source value wire type mapping changed for {variant}")
    production_declaration = re.search(rf"(?m)^\s*const {production_wire_name}: u8 = ([0-9]+)\s*$", encoding_text)
    proof_declaration = re.search(rf"(?m)^const {proof_wire_name}: u8 = ([0-9]+)\s*$", positive_text)
    if production_declaration is None or production_declaration.group(1) != wire_type:
        raise SystemExit(f"production wire type constant {production_wire_name} no longer matches stage0")
    if proof_declaration is None or proof_declaration.group(1) != wire_type:
        raise SystemExit(f"independent proof wire type constant {proof_wire_name} changed")

if writer_text.count('include "./frontend_ir_expression_literal_encoding.elisa"') != 1:
    raise SystemExit("frontend IR writer must include the literal encoding module exactly once")
if expr_text.count('include "./frontend_ir_expr.elisa"') != 0:
    # The expression writer is included by frontend_ir_write; the check is intentionally
    # on the assembly file below so this module cannot become its own dependency root.
    raise SystemExit("expression writer unexpectedly includes itself")
if 'include "./frontend_ir_expr.elisa"' not in writer_text:
    raise SystemExit("frontend IR writer no longer imports the expression writer")

expression_body = function_chunk(expr_text, "ir_expr_node")
for variant, (_, _, wire_type, put_function, value_expression) in KINDS.items():
    expected_put_function = "ir_put_bool" if wire_type == BOOL_WIRE_SCHEMA_TAG else "ir_put_str"
    if put_function != expected_put_function:
        raise SystemExit(f"{variant} writer payload encoder disagrees with its proved wire type")
    arm = compact(literal_arm(expression_body, variant))
    field_constant = f"FrontendIrExpressionLiteralEncoding::{field_names[variant]}"
    tag_constant = f"FrontendIrExpressionLiteralEncoding::{tag_names[variant]}"
    put_call = compact(f"{put_function}(&fields, &live, {field_constant}, {value_expression})")
    emit_call = compact(f"return ir_emit_node(bodies, nodes, {tag_constant}, fields, live)")
    if put_call not in arm or emit_call not in arm:
        raise SystemExit(f"Ast::Expr.{variant} no longer uses its proved payload field and node type IDs")
    if re.search(r"ir_put_(?:str|bool)\(&fields,&live,[0-9]+,", arm) or re.search(r"ir_emit_node\(bodies,nodes,[0-9]+,", arm):
        raise SystemExit(f"Ast::Expr.{variant} reintroduced a numeric field or node ID")

integer_arm = compact(literal_arm(expression_body, "IntLit"))
ordered_integer_path = (
    "Bytes::push_int(&digits, literal_value)",
    "if digits.count == 0:",
    'ir_refuse(refusal, "integer literal outside the IR writer\'s decimal domain")',
    "ir_put_str(&fields, &live, FrontendIrExpressionLiteralEncoding::INT_LIT_VALUE_FIELD_ID, bytes_view_range(digits, 0, digits.count))",
)
positions = [integer_arm.find(compact(fragment)) for fragment in ordered_integer_path]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("integer literal serialization must refuse an empty decimal encoding before slicing it")

expected_positive = {
    "source_literal_node_type_id_is_exact",
    "source_literal_value_field_id_is_exact",
    "source_literal_value_wire_type_id_is_exact",
    "scalar_literal_node_type_ids_are_distinct",
    "shared_payload_slot_is_distinguished_by_literal_node_type",
    "scalar_literal_payload_wire_types_are_exact",
}
expected_negative = {
    "boolean_literal_cannot_use_the_integer_node_type",
    "integer_literal_cannot_use_the_boolean_payload_field",
    "shared_payload_slot_does_not_identify_the_literal_node",
    "string_literal_cannot_use_boolean_payload_wire_type",
}


def declarations(text: str) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", text))


if declarations(positive_text) != expected_positive or declarations(negative_text) != expected_negative:
    raise SystemExit("frontend IR literal proof theorem inventory changed")
for proof_text_current in (positive_text, negative_text):
    if 'include "../../src/driver/frontend_ir_expression_literal_encoding.elisa"' not in proof_text_current:
        raise SystemExit("positive and rejected proofs must include the production literal encoding module")
if (
    "FrontendIrExpressionLiteralEncoding::node_type_id(kind)" not in positive_text
    or "FrontendIrExpressionLiteralEncoding::value_field_id(kind)" not in positive_text
    or "FrontendIrExpressionLiteralEncoding::value_wire_type_id(kind)" not in positive_text
):
    raise SystemExit("universal proofs must call production node, field, and wire type mappings")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("frontend IR literal proofs require a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
    stage1_provenance, ENCODING, WRITER, EXPR_WRITER, TYPE_TABLE,
    HERE / "proof_product_gate.py", Path(__file__), POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE, WRITER, EXPR_WRITER]),
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=90)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert expected_positive <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in expected_negative
}

assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "source-pinned frontend IR scalar literal node and payload field IDs",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
