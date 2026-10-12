"""Admit source-linked laws for frontend-IR ReturnStmt encoding."""
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
POSITIVE = HERE / "frontend_ir_return_statement_encoding.elisa"
NEGATIVE = HERE / "frontend_ir_return_statement_encoding_rejected.elisa"
ENCODING = ROOT / "src/driver/frontend_ir_return_statement_encoding.elisa"
WRITER = ROOT / "src/driver/frontend_ir_write.elisa"
STMT_WRITER = ROOT / "src/driver/frontend_ir_stmt.elisa"
TYPE_TABLE = ROOT / "src/driver/frontend_ir_type_table_2.elisa"
AST_NODES = ROOT / "src/parser/ast_nodes.elisa"
STAGE0_ROOT = Path(os.environ.get(
    "ELISA_STAGE0_COMPILER_ROOT",
    ROOT.parent / "elisa-transpiler-worktrees/stage0-latest/compiler",
)).resolve(strict=True)
STAGE0_AST = STAGE0_ROOT / "src/ast/ast_structtestexpr_to_pos.go"
STAGE0_PARSER = STAGE0_ROOT / "src/parser/parser_statements_parsematchvaluepatternexpr_to_guardconditionintroducesbindings.go"
STAGE0_SCHEMA = STAGE0_ROOT / "src/frontendir/schema_registry.txt"

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


def schema_block(text: str, comment: str) -> str:
    marker = re.search(rf"(?m)^[ \t]*# {re.escape(comment)}\s*$", text)
    if marker is None:
        raise SystemExit(f"Stage0 type table lost {comment}")
    following = re.search(r"(?m)^[ \t]*# [A-Za-z][A-Za-z0-9]* \(type [0-9]+\)\s*$", text[marker.end():])
    end = marker.end() + following.start() if following else len(text)
    return text[marker.start():end]


ENCODING_TEXT = ENCODING.read_text()
WRITER_TEXT = WRITER.read_text()
STMT_TEXT = STMT_WRITER.read_text()
TABLE_TEXT = TYPE_TABLE.read_text()
AST_NODES_TEXT = AST_NODES.read_text()
POSITIVE_TEXT = POSITIVE.read_text()
NEGATIVE_TEXT = NEGATIVE.read_text()
STAGE0_AST_TEXT = STAGE0_AST.read_text()
STAGE0_PARSER_TEXT = STAGE0_PARSER.read_text()
STAGE0_SCHEMA_TEXT = STAGE0_SCHEMA.read_text()

CONSTANTS = {
    "RETURN_STMT_NODE_TYPE_ID": (228, "u32"),
    "RETURN_POSITION_FIELD_ID": (1, "u32"),
    "RETURN_VALUE_FIELD_ID": (2, "u32"),
    "RETURN_NO_VALUE_NODE_ID": (0, "u32"),
}
for name, (expected, ty) in CONSTANTS.items():
    for description, text, source_name in (
        ("encoding", ENCODING_TEXT, name),
        ("proof", POSITIVE_TEXT, f"EXPECTED_{name}"),
    ):
        found = re.search(rf"(?m)^[ \t]*const {source_name}: {ty} = ([0-9]+)\s*$", text)
        if found is None or int(found.group(1)) != expected:
            raise SystemExit(f"{description} constant {source_name} changed from the Stage0 schema")

field_enum = re.search(
    r"(?ms)^[ \t]*const enum ReturnStatementField of u8:\s*\n(.*?)(?=^[ \t]*const )",
    ENCODING_TEXT,
)
if field_enum is None:
    raise SystemExit("ReturnStatementField enum is missing or has no following constant section")
if [line.strip() for line in field_enum.group(1).splitlines() if line.strip()] != ["Position", "Value"]:
    raise SystemExit("ReturnStatementField constructor inventory changed without proof coverage")

field_mapping = compact(function_chunk(ENCODING_TEXT, "field_id"))
for variant, constant in (("Position", "RETURN_POSITION_FIELD_ID"), ("Value", "RETURN_VALUE_FIELD_ID")):
    if compact(f"ReturnStatementField.{variant}:{constant}") not in field_mapping:
        raise SystemExit(f"ReturnStatementField mapping changed for {variant}")
if "returnRETURN_STMT_NODE_TYPE_ID" not in compact(function_chunk(ENCODING_TEXT, "node_type_id")):
    raise SystemExit("ReturnStmt node tag mapping changed")
if "returnRETURN_NO_VALUE_NODE_ID" not in compact(function_chunk(ENCODING_TEXT, "no_value_node_id")):
    raise SystemExit("bare return no-value sentinel mapping changed")

block = compact(schema_block(TABLE_TEXT, "ReturnStmt (type 228)"))
if compact('ir_uvarint_out(buffer, 228) ir_str_out(buffer, "ReturnStmt") ir_uvarint_out(buffer, 2)') not in block:
    raise SystemExit("Stage0 ReturnStmt tag or field count changed")
for field_id, name, wire_types in ((1, "Position", (7,)), (2, "Value", (4,))):
    schema = compact(f'ir_field_desc_out(buffer, {field_id}, "{name}")')
    for wire_type in wire_types:
        schema += compact(f"buffer.push({wire_type})")
    if name == "Position":
        schema += compact('ir_str_out(buffer, "")')
    if schema not in block:
        raise SystemExit(f"Stage0 ReturnStmt.{name} schema changed")

if "Return(value:Expr?,pos:Pos)" not in compact(AST_NODES_TEXT):
    raise SystemExit("stage1 AST no longer models ReturnStmt's value as optional")
stage0_ast_compact = compact(re.sub(r"//[^\n]*", "", STAGE0_AST_TEXT))
if "typeReturnStmtstruct{Positionlexer.PosValueExpr}" not in stage0_ast_compact:
    raise SystemExit("Stage0 ReturnStmt AST shape changed")
if "T228ReturnStmtFReturnStmt1PositionFReturnStmt2Value" not in compact(STAGE0_SCHEMA_TEXT):
    raise SystemExit("Stage0 schema registry changed ReturnStmt field names/order")
if "return&ast.ReturnStmt{Position:pos}" not in compact(re.sub(r"//[^\n]*", "", STAGE0_PARSER_TEXT)):
    raise SystemExit("Stage0 bare-return parser no longer constructs a nil Value")

if WRITER_TEXT.count('include "./frontend_ir_return_statement_encoding.elisa"') != 1:
    raise SystemExit("frontend IR writer must include the ReturnStmt encoding module exactly once")
if 'include "./frontend_ir_stmt.elisa"' not in WRITER_TEXT:
    raise SystemExit("frontend IR writer no longer imports statement writing")

stmt_chunk = function_chunk(STMT_TEXT, "ir_stmt_node")
lines = stmt_chunk.splitlines()
starts = [index for index, line in enumerate(lines) if line.lstrip().startswith("Ast::Stmt.Return(")]
if len(starts) != 1:
    raise SystemExit("expected exactly one Ast::Stmt.Return arm")
start = starts[0]
indent = len(lines[start]) - len(lines[start].lstrip())
end = next((index for index in range(start + 1, len(lines))
            if len(lines[index]) - len(lines[index].lstrip()) == indent
            and (lines[index].lstrip().startswith("Ast::Stmt.") or lines[index].lstrip() == "_:")), len(lines))
arm = compact("\n".join(lines[start:end]))
expected_arm = compact('''
    Ast::Stmt.Return(value, return_pos):
        value_id: mutable u32 = FrontendIrReturnStatementEncoding::no_value_node_id()
        if value is return_value:
            value_id <- ir_expr_node(bodies, nodes, refusal, return_value, filename)
        ir_put_pos(&fields, &live, FrontendIrReturnStatementEncoding::field_id(FrontendIrReturnStatementEncoding::ReturnStatementField.Position), return_pos, filename)
        ir_put_node(&fields, &live, FrontendIrReturnStatementEncoding::field_id(FrontendIrReturnStatementEncoding::ReturnStatementField.Value), value_id)
        return ir_emit_node(bodies, nodes, FrontendIrReturnStatementEncoding::node_type_id(), fields, live)
''')
if arm != expected_arm:
    raise SystemExit("ReturnStmt writer arm changed from the checked optional-value mapping")
if "returnifnode_id==0" not in compact(function_chunk(WRITER_TEXT, "ir_put_node")):
    raise SystemExit("IR node writer no longer omits the zero/null node sentinel")

expected_positive = {
    "return_statement_node_type_id_is_exact",
    "absent_return_value_uses_no_node_sentinel",
    "return_statement_field_mapping_is_exact",
    "return_statement_field_ids_are_distinct",
}
expected_negative = {
    "return_statement_tag_cannot_equal_the_proved_tag",
    "return_value_field_cannot_equal_the_proved_field",
}


def declarations(text: str) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", text))


if declarations(POSITIVE_TEXT) != expected_positive or declarations(NEGATIVE_TEXT) != expected_negative:
    raise SystemExit("ReturnStmt proof theorem inventory changed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("ReturnStmt proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, WRITER, TYPE_TABLE])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", AST_NODES, STAGE0_AST, STAGE0_PARSER, STAGE0_SCHEMA,
    *source_closure,
]
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
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert expected_positive <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == expected_negative
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "ReturnStmt frontend-IR schema, optional Value mapping, and null-node omission",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
