"""Admit source-linked proofs for whole-function fulfills protocol diagnostics."""
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
PARSER = ROOT / "src/parser/parser_types_signature.elisa"
PARSER_ROOT = ROOT / "src/parser/parser.elisa"
PASS = ROOT / "src/semantic/check_fulfills_whole_function.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
DISPATCH = ROOT / "src/semantic/semantic_parallel_passes.elisa"
PIPELINE = ROOT / "src/semantic/semantic_api.elisa"
POSITIVE = HERE / "fulfills_whole_function.elisa"
NEGATIVE = HERE / "fulfills_whole_function_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MARKER = 3900000020
SUBJECT_PROTOCOL_MARKER = 3900000026
PASS_ID = 81
PASS_BATCH_START = 80
PASS_BATCH_SIZE = 5

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|#[^\r\n]*|\S', text)
    return "".join(token for token in tokens if not token.startswith("#"))


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^[ \t]*def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():])
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


def direct_child(source: str, parent: str, child_prefix: str) -> bool:
    lines = source.splitlines()
    parents = [index for index, line in enumerate(lines) if line.strip() == parent]
    if len(parents) != 1:
        return False
    parent_index = parents[0]
    parent_indent = len(lines[parent_index]) - len(lines[parent_index].lstrip(" \t"))
    end = parent_index + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and len(line) - len(line.lstrip(" \t")) <= parent_indent:
            break
        end += 1
    children = [index for index in range(parent_index + 1, end)
                if lines[index].strip().startswith(child_prefix)]
    if len(children) != 1:
        return False
    child_indent = len(lines[children[0]]) - len(lines[children[0]].lstrip(" \t"))
    return child_indent == parent_indent + 4


def direct_child_statements(source: str, parent: str) -> list[str]:
    lines = source.splitlines()
    parents = [index for index, line in enumerate(lines) if line.strip() == parent]
    if len(parents) != 1:
        return []
    parent_index = parents[0]
    parent_indent = len(lines[parent_index]) - len(lines[parent_index].lstrip(" \t"))
    statements = []
    for line in lines[parent_index + 1:]:
        if line.strip() and len(line) - len(line.lstrip(" \t")) <= parent_indent:
            break
        code = line.split("#", 1)[0].rstrip()
        if code.strip() and len(code) - len(code.lstrip(" \t")) == parent_indent + 4:
            statements.append(compact(code))
    return statements


def wrap_direct_child(source: str, parent: str, child_prefix: str) -> str:
    lines = source.splitlines()
    parents = [index for index, line in enumerate(lines) if line.strip() == parent]
    if len(parents) != 1:
        return source
    parent_index = parents[0]
    parent_indent = len(lines[parent_index]) - len(lines[parent_index].lstrip(" \t"))
    end = parent_index + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and len(line) - len(line.lstrip(" \t")) <= parent_indent:
            break
        end += 1
    children = [index for index in range(parent_index + 1, end)
                if lines[index].strip().startswith(child_prefix)]
    if len(children) != 1:
        return source
    child_index = children[0]
    child_indent = len(lines[child_index]) - len(lines[child_index].lstrip(" \t"))
    lines.insert(child_index, " " * child_indent + "if false:")
    lines[child_index + 1] = " " * (child_indent + 4) + lines[child_index + 1].lstrip(" \t")
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


parser_text = PARSER.read_text()
pass_text = PASS.read_text()
parser_constant = f"const FULFILLS_WHOLE_FUNCTION_ROW: u32 = {MARKER}"
pass_constant = f"const FULFILLS_WHOLE_FUNCTION_ROW: u32 = {MARKER}"
subject_protocol_constant = f"const FULFILLS_SUBJECT_PROTOCOL_ROW: u32 = {SUBJECT_PROTOCOL_MARKER}"


def source_matches(parser_candidate: str, pass_candidate: str) -> bool:
    if compact(parser_candidate).count(compact(parser_constant)) != 1:
        return False
    if len(re.findall(rf"(?<!\d){MARKER}(?!\d)", parser_candidate)) != 1:
        return False
    if compact(parser_candidate).count(compact(subject_protocol_constant)) != 1:
        return False
    if len(re.findall(rf"(?<!\d){SUBJECT_PROTOCOL_MARKER}(?!\d)", parser_candidate)) != 1:
        return False
    if compact(pass_candidate).count(compact(pass_constant)) != 1:
        return False
    if len(re.findall(rf"(?<!\d){MARKER}(?!\d)", pass_candidate)) != 1:
        return False

    parser_function = function_section(parser_candidate, "parse_signature_clauses")
    parser_compact = compact(parser_function)
    parser_anchors = (
        "fulfills_shape:bool=depth==0andclause_text==\"fulfills\"andparser.peek_at(1)==TokenKind.Identandparser.peek_at(2)==TokenKind.Isandparser.peek_at(3)==TokenKind.Ident",
        'fulfills_protocol:sview=Lexer::text_or_empty(parser.tokens[parser.position+3],parser.source)if fulfills_shape else sview("",0,0)',
        'fulfills_whole_fn:bool=when fulfills_protocol:"NoBoundsChecks"|"Vectorizes"->true_->false',
        'parser.enum_annotations<-parser.enum_annotations.push(Ast::EnumAnnotation{owner:Lexer::text_or_empty(parser.tokens[parser.position+1],parser.source),name:fulfills_protocol,line:FULFILLS_WHOLE_FUNCTION_ROW})if fulfills_whole_fn',
        'parser.enum_annotations<-parser.enum_annotations.push(Ast::EnumAnnotation{owner:Lexer::text_or_empty(parser.tokens[parser.position+1],parser.source),name:fulfills_protocol,line:FULFILLS_SUBJECT_PROTOCOL_ROW})if fulfills_shape',
    )
    positions = [parser_compact.find(compact(anchor)) for anchor in parser_anchors]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        return False
    while_header = "while parser.peek() != TokenKind.Eof |parser, depth|:"
    parser_direct_children = (
        "fulfills_shape:",
        "fulfills_protocol:",
        "fulfills_whole_fn:",
        "parser.enum_annotations <- parser.enum_annotations.push(Ast::EnumAnnotation{owner: Lexer::text_or_empty(parser.tokens[parser.position + 1], parser.source), name: fulfills_protocol, line: FULFILLS_WHOLE_FUNCTION_ROW})",
        "parser.enum_annotations <- parser.enum_annotations.push(Ast::EnumAnnotation{owner: Lexer::text_or_empty(parser.tokens[parser.position + 1], parser.source), name: fulfills_protocol, line: FULFILLS_SUBJECT_PROTOCOL_ROW})",
    )
    if not all(direct_child(parser_function, while_header, child)
               for child in parser_direct_children):
        return False
    parser_statement_sequence = (
        'fulfills_shape: bool = depth == 0 and clause_text == "fulfills" and parser.peek_at(1) == TokenKind.Ident and parser.peek_at(2) == TokenKind.Is and parser.peek_at(3) == TokenKind.Ident',
        'fulfills_protocol: sview = Lexer::text_or_empty(parser.tokens[parser.position + 3], parser.source) if fulfills_shape else sview("", 0, 0)',
        'fulfills_whole_fn: bool = when fulfills_protocol:',
        'parser.enum_annotations <- parser.enum_annotations.push(Ast::EnumAnnotation{owner: Lexer::text_or_empty(parser.tokens[parser.position + 1], parser.source), name: fulfills_protocol, line: FULFILLS_WHOLE_FUNCTION_ROW}) if fulfills_whole_fn',
        'parser.enum_annotations <- parser.enum_annotations.push(Ast::EnumAnnotation{owner: Lexer::text_or_empty(parser.tokens[parser.position + 1], parser.source), name: fulfills_protocol, line: FULFILLS_SUBJECT_PROTOCOL_ROW}) if fulfills_shape',
    )
    direct_statements = direct_child_statements(parser_function, while_header)
    starts = [index for index, statement in enumerate(direct_statements)
              if statement.startswith("fulfills_shape:")]
    if len(starts) != 1 or direct_statements[starts[0]:starts[0] + len(parser_statement_sequence)] != [
        compact(statement) for statement in parser_statement_sequence
    ]:
        return False

    pass_function = function_section(pass_candidate, "check_fulfills_whole_function")
    diagnostic = 'table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.FulfillsWholeFunction, name: annotation.name, line: 0, expected: annotation.owner, actual: ""}) if annotation.line == FULFILLS_WHOLE_FUNCTION_ROW'
    if compact(pass_function).count(compact(diagnostic)) != 1:
        return False
    pass_loop = "for annotation in file.enum_annotations |table| -> table:"
    return direct_child_statements(pass_function, pass_loop) == [compact(diagnostic)]


if not source_matches(parser_text, pass_text):
    raise SystemExit("whole-function fulfills parser/diagnostic rules no longer match the exact source classifier")

mutations = (
    (parser_text.replace('"NoBoundsChecks" | "Vectorizes" -> true', '"NoBoundsChecks" -> true', 1), pass_text),
    (parser_text.replace("if fulfills_whole_fn", "if fulfills_shape", 1), pass_text),
    (parser_text.replace("line: FULFILLS_WHOLE_FUNCTION_ROW", "line: FULFILLS_SUBJECT_PROTOCOL_ROW", 1), pass_text),
    (parser_text, pass_text.replace("expected: annotation.owner", "expected: annotation.name", 1)),
    (parser_text, wrap_direct_child(
        pass_text,
        "for annotation in file.enum_annotations |table| -> table:",
        "table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.FulfillsWholeFunction",
    )),
)
for parser_mutation, pass_mutation in mutations:
    if (parser_mutation, pass_mutation) == (parser_text, pass_text) or source_matches(parser_mutation, pass_mutation):
        raise SystemExit("whole-function fulfills source checker accepted a protocol, shape, marker, payload, or reachability mutation")

if 'include "./check_fulfills_whole_function.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("semantic root no longer includes the whole-function fulfills check")
if 'include "./parser_types_signature.elisa"' not in PARSER_ROOT.read_text():
    raise SystemExit("parser root no longer includes the whole-function fulfills producer")
dispatch_text = DISPATCH.read_text()
if not direct_child(dispatch_text, f"elif pass_id == {PASS_ID}:", "table <- check_fulfills_whole_function(loop_view, table)"):
    raise SystemExit("parallel semantic dispatch no longer invokes the whole-function fulfills check")
if f"par_pass_run(file, &loop_view, flags, table, shared_pool, {PASS_BATCH_START}, {PASS_BATCH_SIZE})" not in PIPELINE.read_text():
    raise SystemExit("semantic pipeline no longer schedules the pass containing the whole-function fulfills check")

expected_positive = {
    "source_protocol_match_is_exact",
    "both_whole_function_protocols_are_classified",
    "other_protocol_names_are_not_classified",
    "only_subject_forms_with_whole_function_protocols_are_marked",
    "malformed_subject_forms_are_not_marked",
    "the_parser_marker_is_reported",
    "other_annotation_rows_are_not_reported",
}
expected_negative = {
    "ordinary_protocol_is_marked",
    "malformed_subject_form_is_marked",
    "non_whole_function_protocol_is_classified",
    "neighboring_marker_row_is_reported",
    "parser_marker_row_is_ignored",
}
for path, expected in ((POSITIVE, expected_positive), (NEGATIVE, expected_negative)):
    found = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if found != expected:
        raise SystemExit(f"{path.name} theorem inventory changed")

protocol_pattern = 'whenprotocol:"NoBoundsChecks"|"Vectorizes"->true_->false'
proof_text = POSITIVE.read_text()
proof_compact = compact(proof_text)
model_functions = {
    "is_whole_function_protocol": """def is_whole_function_protocol(protocol: sview) -> bool:
    ensure result == (
        when protocol:
            "NoBoundsChecks" | "Vectorizes" -> true
            _ -> false
    )
    return when protocol:
        "NoBoundsChecks" | "Vectorizes" -> true
        _ -> false
""",
    "should_mark_subject_fulfills": """def should_mark_subject_fulfills(is_subject_form: bool, protocol: sview) -> bool:
    ensure result == (is_subject_form and is_whole_function_protocol(protocol))
    return is_subject_form and is_whole_function_protocol(protocol)
""",
    "should_report_annotation_row": """def should_report_annotation_row(annotation_row: u32) -> bool:
    ensure result == (annotation_row == FULFILLS_WHOLE_FUNCTION_ROW)
    return annotation_row == FULFILLS_WHOLE_FUNCTION_ROW
""",
}
for name, expected in model_functions.items():
    if compact(function_section(proof_text, name)) != compact(expected):
        raise SystemExit(f"proof model function {name} no longer mirrors the source-gated rule")
if f"ensureresult==({protocol_pattern})" not in compact(function_section(proof_text, "is_whole_function_protocol")) or \
        f"return{protocol_pattern}" not in compact(function_section(proof_text, "is_whole_function_protocol")):
    raise SystemExit("proof model no longer uses the source's exact pattern-matched protocol set")
if not source_matches(parser_text, pass_text):
    raise SystemExit("production source changed during whole-function fulfills admission")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("whole-function fulfills proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"), PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    PARSER, PARSER_ROOT, PASS, SEMANTIC, DISPATCH, PIPELINE, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
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
assert positive == run(POSITIVE)[1], "whole-function fulfills proof report changed across repeats"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert expected_positive | set(model_functions) <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == expected_negative
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest
print(json.dumps({
    "admitted": True,
    "scope": "the NoBoundsChecks/Vectorizes subject-fulfills classifier and its diagnostic row",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
