"""Admit source-linked laws for frontend-IR IterForStmt encoding."""
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
POSITIVE = HERE / "frontend_ir_for_statement_encoding.elisa"
NEGATIVE = HERE / "frontend_ir_for_statement_encoding_rejected.elisa"
ENCODING = ROOT / "src/driver/frontend_ir_for_statement_encoding.elisa"
WRITER = ROOT / "src/driver/frontend_ir_write.elisa"
STMT_WRITER = ROOT / "src/driver/frontend_ir_stmt.elisa"
TYPE_TABLE = ROOT / "src/driver/frontend_ir_type_table_2.elisa"
PARSER = ROOT / "src/parser/parser_stmt_for.elisa"
STAGE0_ROOT = Path(os.environ.get(
    "ELISA_STAGE0_COMPILER_ROOT",
    ROOT.parent / "elisa-transpiler-worktrees/stage0-latest/compiler",
)).resolve(strict=True)
STAGE0_AST = STAGE0_ROOT / "src/ast/ast_structtestexpr_to_pos.go"
STAGE0_PARSER = STAGE0_ROOT / "src/parser/parser_statements_parseblock_to_parseforstmt.go"
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


def variant_inventory(text: str, enum_name: str) -> list[str]:
    match = re.search(
        rf"(?ms)^[ \t]*const enum {re.escape(enum_name)} of u8:\s*\n(.*?)(?=^[ \t]*const )",
        text,
    )
    if match is None:
        raise SystemExit(f"{enum_name} enum is missing or has no following constant section")
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def schema_block(text: str, comment: str) -> str:
    marker = re.search(rf"(?m)^[ \t]*# {re.escape(comment)}\s*$", text)
    if marker is None:
        raise SystemExit(f"stage0 type table lost {comment}")
    following = re.search(r"(?m)^[ \t]*# [A-Za-z][A-Za-z0-9]* \(type [0-9]+\)\s*$", text[marker.end():])
    end = marker.end() + following.start() if following else len(text)
    return text[marker.start():end]


ENCODING_TEXT = ENCODING.read_text()
WRITER_TEXT = WRITER.read_text()
STMT_TEXT = STMT_WRITER.read_text()
TABLE_TEXT = TYPE_TABLE.read_text()
PARSER_TEXT = PARSER.read_text()
POSITIVE_TEXT = POSITIVE.read_text()
NEGATIVE_TEXT = NEGATIVE.read_text()
STAGE0_AST_TEXT = STAGE0_AST.read_text()
STAGE0_PARSER_TEXT = STAGE0_PARSER.read_text()
STAGE0_SCHEMA_TEXT = STAGE0_SCHEMA.read_text()

CONSTANTS = {
    "ITER_FOR_STMT_NODE_TYPE_ID": (143, "u32"),
    "MOVE_BIND_NAME_PATTERN_NODE_TYPE_ID": (187, "u32"),
    "ITER_FOR_BODY_FIELD_ID": (1, "u32"),
    "ITER_FOR_MODE_FIELD_ID": (3, "u32"),
    "ITER_FOR_MOVED_SOURCE_FIELD_ID": (4, "u32"),
    "ITER_FOR_PATTERN_FIELD_ID": (5, "u32"),
    "ITER_FOR_POSITION_FIELD_ID": (8, "u32"),
    "ITER_FOR_SOURCE_FIELD_ID": (12, "u32"),
    "MOVE_BIND_NAME_PATTERN_NAME_FIELD_ID": (1, "u32"),
    "ITER_BIND_VALUE_MODE_VALUE": (0, "i64"),
    "ITER_BIND_MUTABLE_REFERENCE_MODE_VALUE": (2, "i64"),
    "FOR_LOOP_NAME_BINDER_COUNT": (1, "usize"),
}

for name, (expected, ty) in CONSTANTS.items():
    for description, text, source_name in (
        ("encoding", ENCODING_TEXT, name),
        ("proof", POSITIVE_TEXT, f"EXPECTED_{name}"),
    ):
        found = re.search(rf"(?m)^[ \t]*const {source_name}: {ty} = (-?[0-9]+)\s*$", text)
        if found is None or int(found.group(1)) != expected:
            raise SystemExit(f"{description} constant {source_name} differs from the Stage0 schema/mode")

if variant_inventory(ENCODING_TEXT, "ForBindingMode") != ["Value", "MutableReference", "Unsupported"]:
    raise SystemExit("ForBindingMode constructor inventory changed without proof coverage")
if variant_inventory(ENCODING_TEXT, "ForStatementField") != ["Body", "Mode", "MovedSource", "Pattern", "Position", "Source"]:
    raise SystemExit("ForStatementField constructor inventory changed without proof coverage")

if compact(function_chunk(ENCODING_TEXT, "binding_mode")) != compact('''
    def binding_mode(bind: sview) -> ForBindingMode:
        ensure bind != "" or result == ForBindingMode.Value
        ensure bind != "mutable" or result == ForBindingMode.MutableReference
        ensure (bind == "" or bind == "mutable") or result == ForBindingMode.Unsupported
        if bind == "":
            return ForBindingMode.Value
        if bind == "mutable":
            return ForBindingMode.MutableReference
        return ForBindingMode.Unsupported
'''):
    raise SystemExit("binding_mode no longer implements the exact three-way binding mode map")
if compact(function_chunk(ENCODING_TEXT, "binding_mode_value")) != compact('''
    def binding_mode_value(mode: ForBindingMode) -> i64:
        ensure mode != ForBindingMode.Value or result == ITER_BIND_VALUE_MODE_VALUE
        ensure mode != ForBindingMode.MutableReference or result == ITER_BIND_MUTABLE_REFERENCE_MODE_VALUE
        ensure mode != ForBindingMode.Unsupported or result == ITER_BIND_VALUE_MODE_VALUE
        return match mode:
            ForBindingMode.Value: ITER_BIND_VALUE_MODE_VALUE
            ForBindingMode.MutableReference: ITER_BIND_MUTABLE_REFERENCE_MODE_VALUE
            ForBindingMode.Unsupported: ITER_BIND_VALUE_MODE_VALUE
'''):
    raise SystemExit("binding_mode_value changed from the named Stage0 mode mapping")
if compact(function_chunk(ENCODING_TEXT, "binding_and_source_are_supported")) != compact('''
    def binding_and_source_are_supported(mode: ForBindingMode, moved_source: bool) -> bool:
        ensure result == (mode == ForBindingMode.Value or (mode == ForBindingMode.MutableReference and not moved_source))
        return match mode:
            ForBindingMode.Value: true
            ForBindingMode.MutableReference: not moved_source
            ForBindingMode.Unsupported: false
'''):
    raise SystemExit("supported binding/moved-source policy changed from the proved match")
if compact(function_chunk(ENCODING_TEXT, "is_explicit_move_source")) != compact('''
    def is_explicit_move_source(iterable: Ast::Expr) -> bool:
        return match iterable:
            Ast::Expr.Move(_, _): true
            _: false
'''):
    raise SystemExit("move-source detector changed from the exact Expr.Move constructor match")

field_ids = {
    "Body": (1, "ITER_FOR_BODY_FIELD_ID"),
    "Mode": (3, "ITER_FOR_MODE_FIELD_ID"),
    "MovedSource": (4, "ITER_FOR_MOVED_SOURCE_FIELD_ID"),
    "Pattern": (5, "ITER_FOR_PATTERN_FIELD_ID"),
    "Position": (8, "ITER_FOR_POSITION_FIELD_ID"),
    "Source": (12, "ITER_FOR_SOURCE_FIELD_ID"),
}
field_mapping = compact(function_chunk(ENCODING_TEXT, "field_id"))
for variant, (_, constant) in field_ids.items():
    if compact(f"ForStatementField.{variant}:{constant}") not in field_mapping:
        raise SystemExit(f"ForStatementField mapping changed for {variant}")
if "returnITER_FOR_STMT_NODE_TYPE_ID" not in compact(function_chunk(ENCODING_TEXT, "node_type_id")):
    raise SystemExit("IterForStmt node tag mapping changed")
if "returnMOVE_BIND_NAME_PATTERN_NODE_TYPE_ID" not in compact(function_chunk(ENCODING_TEXT, "pattern_node_type_id")):
    raise SystemExit("MoveBindNamePattern node tag mapping changed")
if "returnMOVE_BIND_NAME_PATTERN_NAME_FIELD_ID" not in compact(function_chunk(ENCODING_TEXT, "pattern_name_field_id")):
    raise SystemExit("MoveBindNamePattern.Name field mapping changed")

for comment, tag, name, count, fields in (
    ("IterForStmt (type 143)", 143, "IterForStmt", 13, {
        "Body": (1, (5, 4)), "Mode": (3, (2,)), "MovedSource": (4, (1,)),
        "Pattern": (5, (4,)), "Position": (8, (7,)), "Source": (12, (4,)),
    }),
    ("MoveBindNamePattern (type 187)", 187, "MoveBindNamePattern", 2, {
        "Name": (1, (3,)), "Position": (2, (7,)),
    }),
):
    block = compact(schema_block(TABLE_TEXT, comment))
    if compact(f'ir_uvarint_out(buffer, {tag}) ir_str_out(buffer, "{name}") ir_uvarint_out(buffer, {count})') not in block:
        raise SystemExit(f"Stage0 {name} tag or field count changed")
    for field_name, (field_id, wire_types) in fields.items():
        schema = compact(f'ir_field_desc_out(buffer, {field_id}, "{field_name}")')
        for wire_type in wire_types:
            schema += compact(f"buffer.push({wire_type})")
        if field_name == "Position":
            schema += compact('ir_str_out(buffer, "")')
        if schema not in block:
            raise SystemExit(f"Stage0 {name}.{field_name} schema changed")

stage0_ast_compact = compact(re.sub(r"//[^\n]*", "", STAGE0_AST_TEXT))
stage0_modes = compact("""
    type IterBindMode int
    const (
        IterBindValue IterBindMode = iota
        IterBindRef
        IterBindMutableRef
    )
""")
if stage0_modes not in stage0_ast_compact:
    raise SystemExit("Stage0 IterBindMode no longer assigns Value=0, Ref=1, MutableRef=2")
stage0_parser_compact = compact(re.sub(r"//[^\n]*", "", STAGE0_PARSER_TEXT))
if "source:=startOrSourcemovedSource:=false" not in stage0_parser_compact:
    raise SystemExit("Stage0 loop parser moved-source initialization changed")
if "ifmoveExpr,ok:=source.(*ast.MoveExpr);ok{" not in stage0_parser_compact or "source=moveExpr.OperandmovedSource=true" not in stage0_parser_compact:
    raise SystemExit("Stage0 parser no longer unwraps a direct move source into MovedSource")
if "T202ParallelForStmt" not in compact(STAGE0_SCHEMA_TEXT):
    raise SystemExit("Stage0's separate ParallelForStmt node was not found")
if compact('bind: mutable sview = "parallel" if parallel else ("mutable" if accepted_mutable else "")') not in compact(PARSER_TEXT):
    raise SystemExit("stage1 for parser's binding-mode cases changed")

if WRITER_TEXT.count('include "./frontend_ir_for_statement_encoding.elisa"') != 1:
    raise SystemExit("frontend IR writer must include the ForStmt encoding module exactly once")
if 'include "./frontend_ir_stmt.elisa"' not in WRITER_TEXT:
    raise SystemExit("frontend IR writer no longer imports statement writing")

for_body = function_chunk(STMT_TEXT, "ir_stmt_node")
lines = for_body.splitlines()
starts = [index for index, line in enumerate(lines) if line.lstrip().startswith("Ast::Stmt.For(")]
if len(starts) != 1:
    raise SystemExit("expected exactly one Ast::Stmt.For arm")
start = starts[0]
indent = len(lines[start]) - len(lines[start].lstrip())
end = next((index for index in range(start + 1, len(lines))
            if len(lines[index]) - len(lines[index].lstrip()) == indent
            and (lines[index].lstrip().startswith("Ast::Stmt.") or lines[index].lstrip() == "_:")), len(lines))
arm = compact("\n".join(lines[start:end]))
expected_arm = compact('''
    Ast::Stmt.For(bind, variables, iterable, body, for_pos):
        bind_mode: FrontendIrForStatementEncoding::ForBindingMode = FrontendIrForStatementEncoding::binding_mode(bind)
        moved_source: bool = FrontendIrForStatementEncoding::is_explicit_move_source(iterable)
        if not FrontendIrForStatementEncoding::binding_and_source_are_supported(bind_mode, moved_source):
            ir_refuse(refusal, "for-loop binding mode or moved source")
            return 0
        if variables.count != FrontendIrForStatementEncoding::FOR_LOOP_NAME_BINDER_COUNT:
            ir_refuse(refusal, "destructuring for-loop")
            return 0
        source_expression: mutable Ast::Expr = iterable
        match iterable:
            Ast::Expr.Move(move_source, _):
                source_expression <- move_source
            _:
                pass
        pattern_fields: mutable darray[u8] = []
        pattern_live: mutable u32 = 0
        ir_put_str(&pattern_fields, &pattern_live, FrontendIrForStatementEncoding::pattern_name_field_id(), variables[0])
        pattern_id: u32 = ir_emit_node(bodies, nodes, FrontendIrForStatementEncoding::pattern_node_type_id(), pattern_fields, pattern_live)
        source_id: u32 = ir_expr_node(bodies, nodes, refusal, source_expression, filename)
        body_ids: mutable darray[u32] = []
        for statement_in_body in body |bodies, nodes, refusal, body_ids|:
            body_ids.push(ir_stmt_node(bodies, nodes, refusal, statement_in_body, filename))
        if bind_mode == FrontendIrForStatementEncoding::ForBindingMode.MutableReference:
            ir_put_int(&fields, &live, FrontendIrForStatementEncoding::field_id(FrontendIrForStatementEncoding::ForStatementField.Mode), FrontendIrForStatementEncoding::binding_mode_value(bind_mode))
        if moved_source:
            ir_put_bool(&fields, &live, FrontendIrForStatementEncoding::field_id(FrontendIrForStatementEncoding::ForStatementField.MovedSource), true)
        ir_put_node_list(&fields, &live, FrontendIrForStatementEncoding::field_id(FrontendIrForStatementEncoding::ForStatementField.Body), body_ids)
        ir_put_node(&fields, &live, FrontendIrForStatementEncoding::field_id(FrontendIrForStatementEncoding::ForStatementField.Pattern), pattern_id)
        ir_put_pos(&fields, &live, FrontendIrForStatementEncoding::field_id(FrontendIrForStatementEncoding::ForStatementField.Position), for_pos, filename)
        ir_put_node(&fields, &live, FrontendIrForStatementEncoding::field_id(FrontendIrForStatementEncoding::ForStatementField.Source), source_id)
        return ir_emit_node(bodies, nodes, FrontendIrForStatementEncoding::node_type_id(), fields, live)
''')
if arm != expected_arm:
    raise SystemExit("ForStmt writer arm changed from the checked binding/move/source mapping")

expected_positive = {
    "for_bind_mode_uses_the_closed_string_match",
    "for_bind_mode_value_matches_stage0_modes",
    "supported_for_binding_and_move_combinations_are_exact",
    "explicit_move_source_is_recognized_by_constructor",
    "for_statement_node_tags_are_exact",
    "for_pattern_name_field_id_is_exact",
    "for_loop_name_binder_count_is_exact",
    "for_statement_field_mapping_is_exact",
    "for_statement_field_ids_are_distinct",
}
expected_negative = {
    "parallel_loop_binding_must_be_serializable",
    "mutable_move_source_must_be_serializable",
}


def declarations(text: str) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", text))


if declarations(POSITIVE_TEXT) != expected_positive or declarations(NEGATIVE_TEXT) != expected_negative:
    raise SystemExit("ForStmt proof theorem inventory changed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("ForStmt proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, WRITER, TYPE_TABLE])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", PARSER, STAGE0_AST, STAGE0_PARSER, STAGE0_SCHEMA,
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
    "scope": "IterForStmt binding-mode and moved-source mapping to Stage0 frontend IR",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
