"""Admit source-linked proofs for the frontend IR ExprStmt encoding."""
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
POSITIVE = HERE / "frontend_ir_expression_statement_encoding.elisa"
NEGATIVE = HERE / "frontend_ir_expression_statement_encoding_rejected.elisa"
ENCODING = ROOT / "src/driver/frontend_ir_expression_statement_encoding.elisa"
WRITER = ROOT / "src/driver/frontend_ir_write.elisa"
STMT_WRITER = ROOT / "src/driver/frontend_ir_stmt.elisa"
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


def schema_block(text: str) -> str:
    marker = re.search(r"(?m)^\s*# ExprStmt \(type 60\)\s*$", text)
    if marker is None:
        raise SystemExit("stage0 type table lost ExprStmt type 60")
    following = re.search(r"(?m)^\s*# [A-Za-z][A-Za-z0-9]* \(type [0-9]+\)\s*$", text[marker.end():])
    end = marker.end() + following.start() if following else len(text)
    return text[marker.start():end]


def statement_arm(body: str) -> str:
    lines = body.splitlines()
    starts = [i for i, line in enumerate(lines) if line.lstrip().startswith("Ast::Stmt.Expr(")]
    if len(starts) != 1:
        raise SystemExit("expected exactly one Ast::Stmt.Expr arm")
    start = starts[0]
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = next((i for i in range(start + 1, len(lines))
                if len(lines[i]) - len(lines[i].lstrip()) == indent
                and (lines[i].lstrip().startswith("Ast::Stmt.") or lines[i].lstrip() == "_:")), len(lines))
    return "\n".join(lines[start:end])


encoding_text = ENCODING.read_text()
writer_text = WRITER.read_text()
stmt_text = STMT_WRITER.read_text()
table_text = TYPE_TABLE.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

enum_match = re.search(
    r"(?ms)^[ \t]*const enum ExpressionStatementField of u8:\s*\n(.*?)(?=^[ \t]*const )",
    encoding_text,
)
if enum_match is None:
    raise SystemExit("ExpressionStatementField enum is missing or has no following declaration")
variants = [line.strip() for line in enum_match.group(1).splitlines() if line.strip()]
if variants != ["Expr", "Position"]:
    raise SystemExit("ExprStmt field constructor inventory changed without proof coverage")

for name, expected in (
    ("EXPR_STMT_NODE_TYPE_ID", 60),
    ("EXPR_STMT_EXPR_FIELD_ID", 1),
    ("EXPR_STMT_POSITION_FIELD_ID", 2),
    ("EXPR_STMT_FIELD_COUNT", 2),
):
    if name == "EXPR_STMT_FIELD_COUNT":
        proof = re.search(rf"(?m)^const EXPECTED_{name}: u32 = ([0-9]+)\s*$", positive_text)
        if proof is None or int(proof.group(1)) != expected:
            raise SystemExit(f"independent proof constant EXPECTED_{name} changed")
        continue
    production = re.search(rf"(?m)^\s*const {name}: u32 = ([0-9]+)\s*$", encoding_text)
    proof = re.search(rf"(?m)^const EXPECTED_{name}: u32 = ([0-9]+)\s*$", positive_text)
    if production is None or int(production.group(1)) != expected:
        raise SystemExit(f"production constant {name} no longer matches stage0")
    if proof is None or int(proof.group(1)) != expected:
        raise SystemExit(f"independent proof constant EXPECTED_{name} changed")

block = compact(schema_block(table_text))
if compact('ir_uvarint_out(buffer, 60)\nir_str_out(buffer, "ExprStmt")\nir_uvarint_out(buffer, 2)') not in block:
    raise SystemExit("stage0 ExprStmt node tag or field count changed")
for field, field_id, wire_type in (("Expr", 1, 4), ("Position", 2, 7)):
    schema = compact(f'ir_field_desc_out(buffer, {field_id}, "{field}")\nbuffer.push({wire_type})')
    if field == "Position":
        schema += compact('ir_str_out(buffer, "")')
    if schema not in block:
        raise SystemExit(f"stage0 ExprStmt.{field} schema changed")

if compact(function_chunk(encoding_text, "node_type_id")) != compact("""
    def node_type_id() -> u32:
        ensure result == EXPR_STMT_NODE_TYPE_ID
        return EXPR_STMT_NODE_TYPE_ID
"""):
    raise SystemExit("ExprStmt node tag mapping changed from the proved function")
field_mapping = compact(function_chunk(encoding_text, "field_id"))
expected_field_mapping = compact("""
    def field_id(field: ExpressionStatementField) -> u32:
        ensure field != ExpressionStatementField.Expr or result == EXPR_STMT_EXPR_FIELD_ID
        ensure field != ExpressionStatementField.Position or result == EXPR_STMT_POSITION_FIELD_ID
        return match field:
            ExpressionStatementField.Expr: EXPR_STMT_EXPR_FIELD_ID
            ExpressionStatementField.Position: EXPR_STMT_POSITION_FIELD_ID
""")
if field_mapping != expected_field_mapping:
    raise SystemExit("ExprStmt field contracts or exhaustive field mapping changed")

if writer_text.count('include "./frontend_ir_expression_statement_encoding.elisa"') != 1:
    raise SystemExit("frontend IR writer must include ExprStmt encoding exactly once")
if 'include "./frontend_ir_stmt.elisa"' not in writer_text:
    raise SystemExit("frontend IR writer no longer imports statement serialization")
arm = compact(statement_arm(function_chunk(stmt_text, "ir_stmt_node")))
expected_arm = compact("""
    Ast::Stmt.Expr(expression, expr_pos):
        expression_id: u32 = ir_expr_node(bodies, nodes, refusal, expression, filename)
        ir_put_node(&fields, &live, FrontendIrExpressionStatementEncoding::field_id(FrontendIrExpressionStatementEncoding::ExpressionStatementField.Expr), expression_id)
        ir_put_pos(&fields, &live, FrontendIrExpressionStatementEncoding::field_id(FrontendIrExpressionStatementEncoding::ExpressionStatementField.Position), expr_pos, filename)
        return ir_emit_node(bodies, nodes, FrontendIrExpressionStatementEncoding::node_type_id(), fields, live)
""")
if arm != expected_arm:
    raise SystemExit("ExprStmt writer arm changed from the exact proved child/position encoding")


def declarations(text: str) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", text))


expected_positive = {
    "expression_statement_node_type_id_is_exact",
    "expression_statement_field_mapping_is_exact",
    "expression_statement_field_ids_are_distinct",
    "expression_statement_field_ids_fit_wire_field_count",
}
expected_negative = {
    "expression_statement_tag_cannot_equal_the_proved_tag",
    "expression_field_cannot_equal_the_proved_field",
    "expression_statement_position_field_is_out_of_bounds",
}
if declarations(positive_text) != expected_positive or declarations(negative_text) != expected_negative:
    raise SystemExit("ExprStmt proof theorem inventory changed")
if 'include "../../src/driver/frontend_ir_expression_statement_encoding.elisa"' not in positive_text:
    raise SystemExit("positive proof must include the production ExprStmt encoding module")
if 'include "./frontend_ir_expression_statement_encoding.elisa"' not in negative_text:
    raise SystemExit("rejected proof must include the production ExprStmt encoding module")
if ("FrontendIrExpressionStatementEncoding::node_type_id()" not in positive_text
        or "FrontendIrExpressionStatementEncoding::field_id(" not in positive_text):
    raise SystemExit("proof laws must call the production node and field mappings")

proof_shapes = {
    "expression_statement_node_type_id_is_exact": """
        def expression_statement_node_type_id_is_exact() -> u32:
            ensure result == EXPECTED_EXPR_STMT_NODE_TYPE_ID
            return FrontendIrExpressionStatementEncoding::node_type_id()
    """,
    "expression_statement_field_mapping_is_exact": """
        def expression_statement_field_mapping_is_exact(field: FrontendIrExpressionStatementEncoding::ExpressionStatementField) -> u32:
            ensure field != FrontendIrExpressionStatementEncoding::ExpressionStatementField.Expr or result == EXPECTED_EXPR_STMT_EXPR_FIELD_ID
            ensure field != FrontendIrExpressionStatementEncoding::ExpressionStatementField.Position or result == EXPECTED_EXPR_STMT_POSITION_FIELD_ID
            return FrontendIrExpressionStatementEncoding::field_id(field)
    """,
    "expression_statement_field_ids_are_distinct": """
        def expression_statement_field_ids_are_distinct() -> bool:
            ensure result == true
            return (
                FrontendIrExpressionStatementEncoding::field_id(FrontendIrExpressionStatementEncoding::ExpressionStatementField.Expr)
                != FrontendIrExpressionStatementEncoding::field_id(FrontendIrExpressionStatementEncoding::ExpressionStatementField.Position)
            )
    """,
    "expression_statement_field_ids_fit_wire_field_count": """
        def expression_statement_field_ids_fit_wire_field_count() -> bool:
            ensure result == true
            return (
                FrontendIrExpressionStatementEncoding::field_id(FrontendIrExpressionStatementEncoding::ExpressionStatementField.Expr) > 0
                and FrontendIrExpressionStatementEncoding::field_id(FrontendIrExpressionStatementEncoding::ExpressionStatementField.Expr) <= EXPECTED_EXPR_STMT_FIELD_COUNT
                and FrontendIrExpressionStatementEncoding::field_id(FrontendIrExpressionStatementEncoding::ExpressionStatementField.Position) > 0
                and FrontendIrExpressionStatementEncoding::field_id(FrontendIrExpressionStatementEncoding::ExpressionStatementField.Position) <= EXPECTED_EXPR_STMT_FIELD_COUNT
            )
    """,
}
negative_shapes = {
    "expression_statement_tag_cannot_equal_the_proved_tag": """
        def expression_statement_tag_cannot_equal_the_proved_tag() -> bool:
            ensure result == true
            return FrontendIrExpressionStatementEncoding::node_type_id() != EXPECTED_EXPR_STMT_NODE_TYPE_ID
    """,
    "expression_field_cannot_equal_the_proved_field": """
        def expression_field_cannot_equal_the_proved_field() -> bool:
            ensure result == true
            return FrontendIrExpressionStatementEncoding::field_id(
                FrontendIrExpressionStatementEncoding::ExpressionStatementField.Expr
            ) != EXPECTED_EXPR_STMT_EXPR_FIELD_ID
    """,
    "expression_statement_position_field_is_out_of_bounds": """
        def expression_statement_position_field_is_out_of_bounds() -> bool:
            ensure result == true
            return FrontendIrExpressionStatementEncoding::field_id(
                FrontendIrExpressionStatementEncoding::ExpressionStatementField.Position
            ) > EXPECTED_EXPR_STMT_FIELD_COUNT
    """,
}
for name, expected in proof_shapes.items():
    if compact(function_chunk(positive_text, name)) != compact(expected):
        raise SystemExit(f"positive proof {name} changed from its source-linked theorem")
for name, expected in negative_shapes.items():
    if compact(function_chunk(negative_text, name)) != compact(expected):
        raise SystemExit(f"rejected proof {name} changed from its false claim")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("ExprStmt proof requires a strict proof build")

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
    "scope": "source-pinned ExprStmt tag, fields, and writer child/position route",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
