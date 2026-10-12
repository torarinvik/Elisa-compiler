"""Admit source-linked proofs for sequence types in the negative-index pass."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
HELPER = ROOT / "src/semantic/negative_index_sequence_type.elisa"
CONSUMER = ROOT / "src/semantic/check_negative_index.elisa"
POSITIVE = HERE / "negative_index_sequence_type.elisa"
NEGATIVE = HERE / "negative_index_sequence_type_rejected.elisa"

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


def require_ordered(body: str, fragments: tuple[str, ...], label: str) -> None:
    compact_body = compact(body)
    positions = [compact_body.find(compact(fragment)) for fragment in fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{label} no longer matches the checked control-flow order")


helper_text = HELPER.read_text()
consumer_text = CONSUMER.read_text()
expected_classifier = (
    'ensure result == (when type_name: "darray" | "view" | "sview" -> true _ -> false)'
)
if compact(expected_classifier) not in compact(function_section(helper_text, "is_sequence_type_name")):
    raise SystemExit("production sequence classifier contract no longer uses the exact closed match")
if compact(expected_classifier) not in compact(function_section(POSITIVE.read_text(), "source_classifier_has_exact_sequence_set")):
    raise SystemExit("proof sequence classifier contract no longer uses the exact closed match")
classifier_body = compact(function_section(helper_text, "is_sequence_type_name"))
if 'returnwhentype_name:"darray"|"view"|"sview"->true_->false' not in classifier_body:
    raise SystemExit("production sequence classifier no longer has the exact closed match")

if 'include "./negative_index_sequence_type.elisa"' not in consumer_text:
    raise SystemExit("negative-index pass no longer imports the proved type classifier")
if 'include "./negative_index_diagnostic.elisa"' not in consumer_text:
    raise SystemExit("negative-index pass no longer imports the proved diagnostic arithmetic")
if "def is_sequence_type_name(" in consumer_text:
    raise SystemExit("negative-index pass has a second, unproved sequence classifier")
walk = compact(function_section(consumer_text, "walk_expression_for_negative_index"))
if 'tracked_type!=""andNegativeIndexSequenceType::is_sequence_type_name(tracked_type)' not in walk:
    raise SystemExit("identifier indexing no longer delegates to the proved sequence classifier")
if "Expr.Array(elements,_):is_sequence<-true" not in walk or "Expr.Index(base,size,_):is_sequence<-true" not in walk:
    raise SystemExit("array literals or fixed arrays stopped receiving structural sequence treatment")
require_ordered(walk, (
    "if is_sequence:",
    "match index:",
    "Expr.IntLit(idx_value, _):",
    "if idx_value < 0:",
    "table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.NegativeIndex, name: object_name, line: line.line, expected: elem_spelling, actual: \"magnitude exceeds u32\" if NegativeIndexDiagnostic::magnitude_exceeds_reported_range(idx_value) else \"\", expected_count: sequence_length, actual_count: NegativeIndexDiagnostic::reported_magnitude(idx_value)})",
), "negative integer-index diagnostic")
require_ordered(walk, (
    "Expr.Unary(unary_op, operand, unary_pos):",
    "if unary_op == TokenKind.Minus:",
    "Expr.IntLit(pos_value, _):",
    "if NegativeIndexDiagnostic::unary_minus_has_negative_index(pos_value):",
    "table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.NegativeIndex, name: object_name, pos: unary_pos, line: line.line, expected: elem_spelling, actual: \"magnitude exceeds u32\" if NegativeIndexDiagnostic::magnitude_exceeds_reported_range(0 - pos_value) else \"\", expected_count: sequence_length, actual_count: NegativeIndexDiagnostic::reported_magnitude(0 - pos_value)})",
), "unary-minus integer-index diagnostic")

expected_positive = {
    "source_classifier_has_exact_sequence_set",
    "all_supported_sequence_names_are_classified_as_sequences",
    "dictionary_keys_remain_outside_sequence_negative_index_check",
    "unrelated_named_types_remain_outside_sequence_negative_index_check",
}
expected_negative = {
    "dictionary_keys_are_sequence_negative_indices",
    "ordinary_integer_values_are_sequences",
}


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


if declarations(POSITIVE) != expected_positive or declarations(NEGATIVE) != expected_negative:
    raise SystemExit("negative-index type proof declaration inventory changed")
for path in (POSITIVE, NEGATIVE):
    if 'include "../../src/semantic/negative_index_sequence_type.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer includes the production classifier")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("negative-index type proof requires a strict proof build")

compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    HELPER,
    CONSUMER,
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE, CONSUMER]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                            text=True, timeout=60)
    report = json.loads(result.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return result.returncode, report


positive_code, positive = run(POSITIVE)
assert positive_code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
verified_names = {
    row["name"] for row in positive["declaration_details"] if row.get("verified")
}
assert expected_positive | {"is_sequence_type_name"} <= verified_names
assert positive == run(POSITIVE)[1], "negative-index type proof report changed across repeated runs"

negative_code, negative = run(NEGATIVE)
assert negative_code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in expected_negative
}
assert all(finding["status"] == "disproved" and finding["counterexample_found"]
           for finding in negative["findings"])
assert "is_sequence_type_name" in {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}
assert require_current_product(BIN, PROVER) == product, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
if hashes_before != hashes_after:
    raise SystemExit("negative-index type proof inputs changed during replay")

print(json.dumps({
    "admitted": True,
    "scope": "closed sequence-name classifier and checked source routing for negative integer indices",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
