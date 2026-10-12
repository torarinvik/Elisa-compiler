"""Admit a source-linked proof of the law subject-type diagnostic predicate."""
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
PARSER = ROOT / "src/parser/parser_decl_law.elisa"
SOURCE = ROOT / "src/semantic/check_law_subject_type.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
PARALLEL_PASSES = ROOT / "src/semantic/semantic_parallel_passes.elisa"
SEMANTIC_API = ROOT / "src/semantic/semantic_api.elisa"
POSITIVE = HERE / "law_subject_type_mismatch.elisa"
NEGATIVE = HERE / "law_subject_type_mismatch_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MARKER_ROW = 3900000033
PASS_ID = 177
BATCH_START = 167
BATCH_SIZE = 16

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


def direct_child(source: str, parent: str, child: str) -> bool:
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
                if lines[index].strip() == child or lines[index].strip().startswith(child)]
    if len(children) != 1:
        return False
    child_indent = len(lines[children[0]]) - len(lines[children[0]].lstrip(" \t"))
    return child_indent == parent_indent + 4


def wrap_indented_block(source: str, marker: str) -> str:
    """Place the line beginning at marker under an extra conditional."""
    lines = source.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip().startswith(marker)]
    if len(starts) != 1:
        return source
    start = starts[0]
    indent = len(lines[start]) - len(lines[start].lstrip(" \t"))
    lines.insert(start, " " * indent + "if false:")
    lines[start + 1] = " " * (indent + 4) + lines[start + 1].lstrip(" \t")
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


parser_source = PARSER.read_text()
source_text = SOURCE.read_text()
parser_declaration = f"const LAW_SUBJECT_TYPE_MARKER_ROW: u32 = {MARKER_ROW}"


def source_matches(candidate: str) -> bool:
    if compact(candidate).count(compact(parser_declaration)) != 1:
        return False
    if len(re.findall(rf"(?<!\d){MARKER_ROW}(?!\d)", candidate)) != 1:
        return False
    expression = function_section(candidate, "lst_check_expression")
    path = (
        "Expr.Binary(left, operator, right, line):",
        "if operator == TokenKind.Is:",
        "match right:",
        "Expr.Ident(law_name, _):",
        "value_type: sview = parallel_lookup_first(names, types, ident_name_of(left))",
        "subject_type: sview = lst_subject_type_of_law(annotations, law_name)",
        'table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.LawSubjectTypeMismatch, name: law_name, line: line.line, expected: subject_type, actual: value_type}) if value_type != "" and subject_type != "" and value_type != subject_type',
        "table <- lst_check_expression(left, names, types, annotations, table)",
        "table <- lst_check_expression(right, names, types, annotations, table)",
    )
    normalized = compact(expression)
    positions = [normalized.find(compact(fragment)) for fragment in path]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        return False
    if normalized.count("DiagnosticKind.LawSubjectTypeMismatch") != 1:
        return False
    return (
        direct_child(expression, "Expr.Binary(left, operator, right, line):", "if operator == TokenKind.Is:")
        and direct_child(expression, "if operator == TokenKind.Is:", "match right:")
        and direct_child(expression, "match right:", "Expr.Ident(law_name, _):")
        and direct_child(expression, "Expr.Ident(law_name, _):", "value_type: sview = parallel_lookup_first(names, types, ident_name_of(left))")
        and direct_child(expression, "Expr.Ident(law_name, _):", "subject_type: sview = lst_subject_type_of_law(annotations, law_name)")
        and direct_child(expression, "Expr.Ident(law_name, _):", "table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.LawSubjectTypeMismatch")
        and direct_child(expression, "Expr.Binary(left, operator, right, line):", "table <- lst_check_expression(left, names, types, annotations, table)")
        and direct_child(expression, "Expr.Binary(left, operator, right, line):", "table <- lst_check_expression(right, names, types, annotations, table)")
    )


if not source_matches(source_text):
    raise SystemExit("law subject-type diagnostic no longer matches the exact nonempty, distinct-type rule")
if compact(source_text).count(compact(parser_declaration)) != 1:
    raise SystemExit("semantic pass must name the law subject-type marker row")
if compact(function_section(source_text, "lst_subject_type_of_law")).count("line==LAW_SUBJECT_TYPE_MARKER_ROW") != 1:
    raise SystemExit("subject-type lookup no longer selects the named parser marker row")
if compact(function_section(source_text, "check_law_subject_type")).count("row.line==LAW_SUBJECT_TYPE_MARKER_ROW") != 1:
    raise SystemExit("pass no longer filters the named subject-type marker rows")

parser_law = compact(function_section(parser_source, "law_declaration"))
if parser_law.count("line:LAW_SUBJECT_TYPE_MARKER_ROW") != 1:
    raise SystemExit("parser no longer emits exactly one named subject-type marker")
if 'include "./check_law_subject_type.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("semantic root no longer includes the subject-type pass")
parallel = compact(PARALLEL_PASSES.read_text())
if f"pass_id=={PASS_ID}:table<-check_law_subject_type(loop_view,table)" not in parallel:
    raise SystemExit("parallel semantic dispatcher no longer calls the subject-type pass")
pipeline = compact(SEMANTIC_API.read_text())
if f"par_pass_run(file,&loop_view,flags,table,shared_pool,{BATCH_START},{BATCH_SIZE})" not in pipeline:
    raise SystemExit("semantic pipeline no longer schedules the subject-type pass")

expected_rule = "ensure result == (value_type != \"\" and subject_type != \"\" and value_type != subject_type) return value_type != \"\" and subject_type != \"\" and value_type != subject_type"
positive_names = {
    "source_mismatch_rule_is_exact",
    "distinct_nonempty_types_are_reported",
    "equal_types_are_ignored",
    "missing_value_type_is_ignored",
    "missing_subject_type_is_ignored",
}
negative_names = {
    "false_equal_subject_types_are_reported",
    "false_missing_value_type_is_reported",
    "false_missing_subject_type_is_reported",
    "false_distinct_types_are_ignored",
}
for path, names in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != names:
        raise SystemExit(f"{path.name} theorem inventory changed")
if 'include "./law_subject_type_mismatch.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("false subject-type controls no longer exercise the admitted predicate")
if compact(function_section(POSITIVE.read_text(), "should_report")) != compact(
    "def should_report(value_type: sview, subject_type: sview) -> bool:\n"
    "    ensure result == (value_type != \"\" and subject_type != \"\" and value_type != subject_type)\n"
    "    return value_type != \"\" and subject_type != \"\" and value_type != subject_type\n"
):
    raise SystemExit("proof model no longer mirrors the production mismatch predicate")
if compact(expected_rule) not in compact(POSITIVE.read_text()):
    raise SystemExit("positive proof no longer states the source-linked mismatch predicate")

mutations = (
    source_text.replace('value_type != "" and subject_type != "" and value_type != subject_type', 'value_type == "" and subject_type != "" and value_type != subject_type', 1),
    source_text.replace("DiagnosticKind.LawSubjectTypeMismatch", "DiagnosticKind.UnknownEnumAnnotation", 1),
    source_text.replace("expected: subject_type, actual: value_type", "expected: value_type, actual: subject_type", 1),
    wrap_indented_block(source_text, "table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.LawSubjectTypeMismatch"),
)
for mutation in mutations:
    if mutation == source_text or source_matches(mutation):
        raise SystemExit("subject-type source checker failed to reject a guard, payload, or reachability mutation")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("law subject-type proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", PARSER, SOURCE, SEMANTIC,
    PARALLEL_PASSES, SEMANTIC_API, POSITIVE, NEGATIVE,
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
assert positive["summary"]["declarations"] == positive["summary"]["proven"] == len(positive_names)
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "subject-type proof report changed across repeated runs"
assert positive_names == {row["name"] for row in positive["declaration_details"] if row.get("verified")}

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] in {"failed", "disproved"}
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "the local LawSubjectTypeMismatch predicate after actual and law subject types are resolved",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
