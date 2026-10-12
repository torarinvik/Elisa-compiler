"""Admit source-linked proofs of enum declarations refining struct types."""
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
PARSER = ROOT / "src/parser/parser_types_aggregate.elisa"
PARSER_ROOT = ROOT / "src/parser/parser.elisa"
PASS = ROOT / "src/semantic/check_enum_refine_parent.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
DISPATCH = ROOT / "src/semantic/semantic_parallel_passes.elisa"
PIPELINE = ROOT / "src/semantic/semantic_api.elisa"
POSITIVE = HERE / "enum_refine_parent.elisa"
NEGATIVE = HERE / "enum_refine_parent_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MARKER = 3900000008
PASS_ID = 166
PASS_BATCH_START = 164
PASS_BATCH_SIZE = 3

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


parser_text = PARSER.read_text()
pass_text = PASS.read_text()
parser_constant = f"const ENUM_REFINE_PARENT_ROW: u32 = {MARKER}"
pass_constant = f"const ENUM_REFINE_PARENT_ROW: u32 = {MARKER}"


def source_matches(parser_candidate: str, pass_candidate: str) -> bool:
    for candidate, declaration in ((parser_candidate, parser_constant), (pass_candidate, pass_constant)):
        if compact(candidate).count(compact(declaration)) != 1:
            return False
        if len(re.findall(rf"(?<!\d){MARKER}(?!\d)", candidate)) != 1:
            return False

    parser_function = function_section(parser_candidate, "enum_declaration")
    parser_compact = compact(parser_function)
    parser_sequence = (
        "enum_parent: sview = parser.header_enum_parent()",
        'parser <- parser.reject_dotted_header_parent() if enum_parent != ""',
        'parser.enum_annotations <- parser.enum_annotations.push(Ast::EnumAnnotation{owner: name_text, name: enum_parent, line: ENUM_REFINE_PARENT_ROW, module: parser.current_module}) if enum_parent != ""',
        "parser <- parser.skip_declaration_header_clauses(true)",
    )
    positions = [parser_compact.find(compact(statement)) for statement in parser_sequence]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        return False
    parser_statements = direct_child_statements(
        parser_function,
        "def enum_declaration(parser: lmut Parser, is_const: bool) -> Ast::Decl?:",
    )
    starts = [index for index, statement in enumerate(parser_statements)
              if statement.startswith("enum_parent:")]
    if len(starts) != 1 or parser_statements[starts[0]:starts[0] + len(parser_sequence)] != [
        compact(statement) for statement in parser_sequence
    ]:
        return False

    pass_function = function_section(pass_candidate, "check_enum_refine_parent")
    expected_pass = f"""def check_enum_refine_parent(file: Ast::File&, table: lmut SymbolTable) -> void:
    can Memory.Allocate, Abort.Panic:
        for annotation in file.enum_annotations |table| -> table:
            if annotation.line == ENUM_REFINE_PARENT_ROW and annotation.name != "" and annotation.owner != "":
                if find_symbol(table, annotation.name) is parent_symbol:
                    table.diagnostics <- table.diagnostics.push(Diagnostic{{kind: DiagnosticKind.EnumRefinesNonEnum, name: annotation.owner, line: 0, expected: "", actual: annotation.name}}) if parent_symbol.kind == SymbolKind.Struct
"""
    return compact(pass_function) == compact(expected_pass)


if not source_matches(parser_text, pass_text):
    raise SystemExit("enum-refines-struct parser and diagnostic rules no longer match the exact source predicate")

mutations = (
    (parser_text.replace("line: ENUM_REFINE_PARENT_ROW", "line: 0", 1), pass_text),
    (parser_text.replace('if enum_parent != ""', "if true", 1), pass_text),
    (parser_text, pass_text.replace("parent_symbol.kind == SymbolKind.Struct", "parent_symbol.kind == SymbolKind.Enum", 1)),
    (parser_text, pass_text.replace("annotation.name != \"\"", 'annotation.name == ""', 1)),
    (parser_text, pass_text.replace("expected: \"\"", "expected: annotation.name", 1)),
)
for parser_mutation, pass_mutation in mutations:
    if (parser_mutation, pass_mutation) == (parser_text, pass_text) or source_matches(parser_mutation, pass_mutation):
        raise SystemExit("enum-refinement source checker accepted a marker, guard, type-kind, or payload mutation")

if 'include "./parser_types_aggregate.elisa"' not in PARSER_ROOT.read_text():
    raise SystemExit("parser root no longer includes the enum-parent annotation producer")
if 'include "./check_enum_refine_parent.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("semantic root no longer includes the enum-refinement check")
dispatch_text = DISPATCH.read_text()
if not direct_child(dispatch_text, f"elif pass_id == {PASS_ID}:", "table <- check_enum_refine_parent(loop_view, table)"):
    raise SystemExit("parallel semantic dispatcher no longer invokes the enum-refinement check")
if f"par_pass_run(file, &loop_view, flags, table, shared_pool, {PASS_BATCH_START}, {PASS_BATCH_SIZE})" not in PIPELINE.read_text():
    raise SystemExit("semantic pipeline no longer schedules the enum-refinement pass batch")

expected_positive = {
    "source_rule_is_exact",
    "a_resolved_struct_parent_is_rejected",
    "an_enum_parent_is_allowed",
    "an_unknown_parent_is_left_to_unknown_type_checking",
    "empty_names_are_ignored",
    "unrelated_annotation_rows_are_ignored",
}
expected_negative = {
    "ordinary_annotation_row_is_reported",
    "empty_parent_name_is_reported",
    "empty_enum_name_is_reported",
    "unresolved_parent_is_rejected_as_a_struct",
    "enum_parent_is_rejected_as_a_struct",
}
for path, expected in ((POSITIVE, expected_positive), (NEGATIVE, expected_negative)):
    found = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if found != expected:
        raise SystemExit(f"{path.name} theorem inventory changed")

proof_text = POSITIVE.read_text()
model_function = function_section(proof_text, "should_report")
expected_model = """def should_report(annotation_row: u32, enum_name: sview, parent_name: sview, parent_found: bool, parent_is_struct: bool) -> bool:
    ensure result == (annotation_row == ENUM_REFINE_PARENT_ROW and enum_name != "" and parent_name != "" and parent_found and parent_is_struct)
    return annotation_row == ENUM_REFINE_PARENT_ROW and enum_name != "" and parent_name != "" and parent_found and parent_is_struct
"""
if compact(model_function) != compact(expected_model):
    raise SystemExit("proof model no longer mirrors the source-gated enum-refinement predicate")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("enum-refinement proof requires a strict proof build")

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
assert positive == run(POSITIVE)[1], "enum-refinement proof report changed across repeats"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert expected_positive | {"should_report"} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == expected_negative
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest
print(json.dumps({
    "admitted": True,
    "scope": "enum parent markers resolve to struct declarations",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
