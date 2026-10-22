"""Admit source-linked proofs for the statement-form WhileStmt schema."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "frontend_ir_while_statement_encoding.elisa"
NEGATIVE = HERE / "frontend_ir_while_statement_encoding_rejected.elisa"
ENCODING = ROOT / "src/driver/frontend_ir_while_statement_encoding.elisa"
WRITER = ROOT / "src/driver/frontend_ir_write.elisa"
STMT_WRITER = ROOT / "src/driver/frontend_ir_stmt.elisa"
TYPE_TABLE = ROOT / "src/driver/frontend_ir_type_table_statements.elisa"

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


def while_statement_arm(body: str) -> str:
    lines = body.splitlines()
    starts = [i for i, line in enumerate(lines) if line.lstrip().startswith("Ast::Stmt.While(")]
    if len(starts) != 1:
        raise SystemExit("expected exactly one Ast::Stmt.While arm")
    start = starts[0]
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        current_indent = len(line) - len(line.lstrip())
        if current_indent == indent and (line.lstrip().startswith("Ast::Stmt.") or line.lstrip() == "_:"):
            end = index
            break
    return "\n".join(lines[start:end])


def schema_block(text: str) -> str:
    marker = re.search(r"(?m)^\s*# WhileStmt \(type 276\)\s*$", text)
    if marker is None:
        raise SystemExit("stage0 type table lost WhileStmt type ID 276")
    following = re.search(r"(?m)^\s*# [A-Za-z][A-Za-z0-9]* \(type [0-9]+\)\s*$", text[marker.end():])
    end = marker.end() + following.start() if following else len(text)
    return text[marker.start():end]


NODE_TYPE_ID = 276
NODE_TYPE_CONSTANT = "WHILE_STMT_NODE_TYPE_ID"
EXPECTED_NODE_TYPE_CONSTANT = "EXPECTED_WHILE_STMT_NODE_TYPE_ID"
FIELDS = {
    "Body": (1, "WHILE_BODY_FIELD_ID", "EXPECTED_WHILE_BODY_FIELD_ID", "Body", (5, 4)),
    "Condition": (3, "WHILE_CONDITION_FIELD_ID", "EXPECTED_WHILE_CONDITION_FIELD_ID", "Cond", (4,)),
    "Position": (5, "WHILE_POSITION_FIELD_ID", "EXPECTED_WHILE_POSITION_FIELD_ID", "Position", (7,)),
}

encoding_text = ENCODING.read_text()
writer_text = WRITER.read_text()
stmt_text = STMT_WRITER.read_text()
table_text = TYPE_TABLE.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

for constant_name, expected_value, text in (
    (NODE_TYPE_CONSTANT, NODE_TYPE_ID, encoding_text),
    (EXPECTED_NODE_TYPE_CONSTANT, NODE_TYPE_ID, positive_text),
):
    found = re.search(rf"(?m)^\s*const {constant_name}: u32 = ([0-9]+)\s*$", text)
    if found is None or int(found.group(1)) != expected_value:
        raise SystemExit(f"constant {constant_name} changed from the stage0 schema")

field_enum = re.search(r"(?ms)^[ \t]*const enum WhileStmtField of u8:\s*\n(.*?)(?=^[ \t]*const )", encoding_text)
if field_enum is None:
    raise SystemExit("WhileStmtField enum is missing or has no following constant section")
field_variants = [line.strip() for line in field_enum.group(1).splitlines() if line.strip()]
if field_variants != list(FIELDS):
    raise SystemExit("WhileStmtField constructor inventory changed without proof coverage")

for kind, (field_id, constant_name, expected_constant, field_name, wire_types) in FIELDS.items():
    for name, text in ((constant_name, encoding_text), (expected_constant, positive_text)):
        found = re.search(rf"(?m)^\s*const {name}: u32 = ([0-9]+)\s*$", text)
        if found is None or int(found.group(1)) != field_id:
            raise SystemExit(f"constant {name} changed from the stage0 schema")

block = compact(schema_block(table_text))
if compact('ir_uvarint_out(buffer, 276)\nir_str_out(buffer, "WhileStmt")\nir_uvarint_out(buffer, 6)') not in block:
    raise SystemExit("stage0 WhileStmt tag or field count changed")
for _, (field_id, _, _, field_name, wire_types) in FIELDS.items():
    schema = compact(f'ir_field_desc_out(buffer, {field_id}, "{field_name}")')
    for wire_type in wire_types:
        schema += compact(f"buffer.push({wire_type})")
    if schema not in block:
        raise SystemExit(f"stage0 WhileStmt field {field_name} changed")

field_mapping = compact(function_chunk(encoding_text, "field_id"))
for kind, (_, constant_name, _, _, _) in FIELDS.items():
    if compact(f"WhileStmtField.{kind}:{constant_name}") not in field_mapping:
        raise SystemExit(f"WhileStmt field_id mapping changed for {kind}")
if "returnWHILE_STMT_NODE_TYPE_ID" not in compact(function_chunk(encoding_text, "node_type_id")):
    raise SystemExit("WhileStmt node_type_id mapping changed")

if writer_text.count('include "./frontend_ir_while_statement_encoding.elisa"') != 1:
    raise SystemExit("frontend IR writer must include the WhileStmt encoding module exactly once")
if 'include "./frontend_ir_stmt.elisa"' not in writer_text:
    raise SystemExit("frontend IR writer no longer imports statement writing")

arm = compact(while_statement_arm(function_chunk(stmt_text, "ir_stmt_node")))
expected_arm = compact('''
    Ast::Stmt.While(condition, body, while_pos):
        condition_id: u32 = ir_expr_node(bodies, nodes, refusal, condition, filename)
        body_ids: mutable darray[u32] = []
        for statement_in_body in body |bodies, nodes, refusal, body_ids|:
            body_ids.push(ir_stmt_node(bodies, nodes, refusal, statement_in_body, filename))
        ir_put_node_list(&fields, &live, FrontendIrWhileStatementEncoding::field_id(FrontendIrWhileStatementEncoding::WhileStmtField.Body), body_ids)
        ir_put_node(&fields, &live, FrontendIrWhileStatementEncoding::field_id(FrontendIrWhileStatementEncoding::WhileStmtField.Condition), condition_id)
        ir_put_pos(&fields, &live, FrontendIrWhileStatementEncoding::field_id(FrontendIrWhileStatementEncoding::WhileStmtField.Position), while_pos, filename)
        return ir_emit_node(bodies, nodes, FrontendIrWhileStatementEncoding::node_type_id(), fields, live)
''')
if arm != expected_arm:
    raise SystemExit("WhileStmt writer branch changed from the proved exact schema mapping")

expected_positive = {
    "source_while_statement_node_type_id_is_exact",
    "source_while_statement_field_id_is_exact",
    "while_statement_field_ids_are_distinct",
}
expected_negative = {
    "while_statement_cannot_use_its_stage0_node_tag",
    "while_body_and_condition_cannot_use_distinct_fields",
}


def declarations(text: str) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", text))


if declarations(positive_text) != expected_positive or declarations(negative_text) != expected_negative:
    raise SystemExit("WhileStmt proof theorem inventory changed")
include = 'include "../../src/driver/frontend_ir_while_statement_encoding.elisa"'
if include not in positive_text or include not in negative_text:
    raise SystemExit("WhileStmt proofs must include the production encoding module")
if "FrontendIrWhileStatementEncoding::node_type_id()" not in positive_text or "FrontendIrWhileStatementEncoding::field_id(field)" not in positive_text:
    raise SystemExit("WhileStmt proofs must call the production tag and field mappings")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("WhileStmt encoding proofs require a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
    stage1_provenance, ENCODING, WRITER, STMT_WRITER, TYPE_TABLE,
    HERE / "proof_product_gate.py", Path(__file__), POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE, WRITER, STMT_WRITER]),
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
    "scope": "WhileStmt node tag and body, condition, and position field mapping",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
