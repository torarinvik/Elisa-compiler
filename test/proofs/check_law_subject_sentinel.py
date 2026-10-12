"""Admit a source-linked proof of the parser/semantic law-subject sentinel protocol."""
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
PARSER_HEADER = ROOT / "src/parser/parser_law_header.elisa"
SEMANTIC_PASS = ROOT / "src/semantic/check_law_subject.elisa"
SEMANTIC_ROOT = ROOT / "src/semantic/semantic.elisa"
PARALLEL_PASSES = ROOT / "src/semantic/semantic_parallel_passes.elisa"
SEMANTIC_API = ROOT / "src/semantic/semantic_api.elisa"
DIAGNOSTIC_MESSAGE = ROOT / "src/semantic/semantic_api_message_3.elisa"
POSITIVE = HERE / "law_subject_sentinel.elisa"
NEGATIVE = HERE / "law_subject_sentinel_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

LAW_SUBJECT_PASS_ID = 164
LAW_SUBJECT_BATCH_START = 164
LAW_SUBJECT_BATCH_SIZE = 3
LAW_MISSING_SUBJECT_ANNOTATION_ROW = 3900000032

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


def code_signature(source: str, function_name: str):
    code_lines = [line.split("#", 1)[0].rstrip() for line in function_section(source, function_name).splitlines()]
    first = next((line for line in code_lines if line.strip()), "")
    base_indent = len(first) - len(first.lstrip(" \t"))
    return tuple(
        (len(line) - len(line.lstrip(" \t")) - base_indent, compact(line))
        for line in code_lines if line.strip()
    )


parser_source = PARSER.read_text()
semantic_source = SEMANTIC_PASS.read_text()
sentinel_spelling = str(LAW_MISSING_SUBJECT_ANNOTATION_ROW)
constant_declaration = f"const LAW_MISSING_SUBJECT_ANNOTATION_ROW: u32 = {sentinel_spelling}"
parser_markers = (
    "law_has_subject: bool = parser.law_header_has_subject()",
    "match clause_text:",
    "\"forbids\" | \"includes\":",
    "if frame_clause == \"changes\" or frame_clause == \"preserves\":",
    "Ast::EnumAnnotation{owner: law_name_text, name: \"\", line: LAW_MISSING_SUBJECT_ANNOTATION_ROW}) if not law_has_subject",
)

expected_semantic_pass = """def check_law_subject(file: Ast::File&, table: lmut SymbolTable) -> void:
    can Memory.Allocate, Abort.Panic:
        for annotation in file.enum_annotations |table| -> table:
            if annotation.line == LAW_MISSING_SUBJECT_ANNOTATION_ROW and annotation.owner != "":
                table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.LawNeedsSubject, name: annotation.owner, line: 0, expected: "", actual: ""})
"""


def has_named_sentinel(source: str) -> bool:
    return (
        compact(source).count(compact(constant_declaration)) == 1
        and len(re.findall(rf"(?<!\d){sentinel_spelling}(?!\d)", source)) == 1
    )


def parser_source_matches(source: str) -> bool:
    if not has_named_sentinel(source):
        return False
    parser_compact = compact(function_section(source, "law_declaration"))
    parser_positions = [parser_compact.find(compact(fragment)) for fragment in parser_markers]
    return (
        all(position >= 0 for position in parser_positions)
        and parser_positions == sorted(parser_positions)
        and parser_compact.count("LAW_MISSING_SUBJECT_ANNOTATION_ROW") == 1
    )


def semantic_source_matches(source: str) -> bool:
    return (
        has_named_sentinel(source)
        and code_signature(source, "check_law_subject")
        == code_signature(expected_semantic_pass, "check_law_subject")
        and compact(source).count("kind:DiagnosticKind.LawNeedsSubject") == 1
    )


if not parser_source_matches(parser_source):
    raise SystemExit("law parser no longer records the named marker only for a predicate law without a subject")
if "deflaw_header_has_subject(parser:Parser&)->bool" not in compact(PARSER_HEADER.read_text()):
    raise SystemExit("law parser no longer delegates subject-presence classification to its header scanner")

if not semantic_source_matches(semantic_source):
    raise SystemExit("semantic law-subject pass no longer implements its exact sentinel and owner guard")

if 'include "./check_law_subject.elisa"' not in SEMANTIC_ROOT.read_text():
    raise SystemExit("semantic root no longer includes the law-subject pass")
parallel = compact(PARALLEL_PASSES.read_text())
if f"ifpass_id=={LAW_SUBJECT_PASS_ID}:table<-check_law_subject(loop_view,table)" not in parallel:
    raise SystemExit("parallel semantic dispatcher no longer calls the law-subject pass at its assigned id")
pipeline = compact(SEMANTIC_API.read_text())
if f"par_pass_run(file,&loop_view,flags,table,shared_pool,{LAW_SUBJECT_BATCH_START},{LAW_SUBJECT_BATCH_SIZE})" not in pipeline:
    raise SystemExit("semantic pipeline no longer schedules the law-subject pass")
expected_message = 'DiagnosticKind.LawNeedsSubject: buffer.extend(f"law \\"{diagnostic.name}\\" needs a subject: give it at least one value parameter (conventionally `self`)")'
if compact(expected_message) not in compact(DIAGNOSTIC_MESSAGE.read_text()):
    raise SystemExit("LawNeedsSubject diagnostic no longer reports the owning law and required subject")

expected_model = """def should_report_missing_subject(row: u32, owner: sview) -> bool:
    ensure result == (row == LAW_MISSING_SUBJECT_ANNOTATION_ROW and owner != "")
    return row == LAW_MISSING_SUBJECT_ANNOTATION_ROW and owner != ""
"""
proof_text = POSITIVE.read_text()
if code_signature(proof_text, "should_report_missing_subject") != code_signature(expected_model, "should_report_missing_subject"):
    raise SystemExit("proof model no longer captures the exact sentinel/owner rule")
if f"const LAW_MISSING_SUBJECT_ANNOTATION_ROW: u32 = {sentinel_spelling}" not in proof_text:
    raise SystemExit("proof model no longer names the production sentinel")

positive_names = {
    "source_law_subject_rule_is_exact",
    "missing_subject_sentinel_with_owner_is_reported",
    "empty_owner_does_not_trigger_diagnostic",
    "nonmatching_rows_are_ignored",
}
negative_names = {
    "false_valid_subject_marker_is_ignored",
    "false_empty_owner_is_reported",
    "false_other_annotation_row_is_reported",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != expected:
        raise SystemExit(f"{path.name} theorem inventory changed")
if 'include "./law_subject_sentinel.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer exercise the admitted law-subject predicate")

mutations = (
    ("parser missing-subject guard", parser_source, parser_source.replace("if not law_has_subject", "if law_has_subject", 1), parser_source_matches),
    ("parser sentinel value", parser_source, parser_source.replace(constant_declaration, constant_declaration.replace(sentinel_spelling, "3900000031"), 1), parser_source_matches),
    ("semantic owner guard", semantic_source, semantic_source.replace("annotation.owner != \"\"", "annotation.owner == \"\"", 1), semantic_source_matches),
    ("semantic diagnostic kind", semantic_source, semantic_source.replace("DiagnosticKind.LawNeedsSubject", "DiagnosticKind.UnknownEnumAnnotation", 1), semantic_source_matches),
)
for label, original, mutation, validator in mutations:
    if mutation == original:
        raise SystemExit(f"law-subject mutation fixture did not change the {label}")
    if validator(mutation):
        raise SystemExit(f"law-subject source checker accepted the {label} mutation")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("law-subject sentinel proof requires a strict proof build")
stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    PARSER, PARSER_HEADER, SEMANTIC_PASS, SEMANTIC_ROOT, PARALLEL_PASSES,
    SEMANTIC_API, DIAGNOSTIC_MESSAGE, POSITIVE, NEGATIVE,
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
assert positive == run(POSITIVE)[1], "law-subject proof report changed across repeated runs"
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
    "scope": "the parser's missing-law-subject sentinel and the semantic LawNeedsSubject guard it triggers",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
