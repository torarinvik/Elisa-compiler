"""Admit proofs for safe, source-linked negative-index diagnostic magnitudes."""
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
HELPER = ROOT / "src/semantic/negative_index_diagnostic.elisa"
CONSUMER = ROOT / "src/semantic/check_negative_index.elisa"
DIAGNOSTIC_TYPES = ROOT / "src/semantic/semantic_types.elisa"
RENDERER = ROOT / "src/semantic/semantic_api_message_2.elisa"
POSITIVE = HERE / "negative_index_diagnostic.elisa"
NEGATIVE = HERE / "negative_index_diagnostic_rejected.elisa"

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
        raise SystemExit(f"{label} no longer matches its checked control-flow order")


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


helper_text = HELPER.read_text()
count_fn = compact(function_section(helper_text, "reported_magnitude"))
for fragment in (
    "const MAX_REPORTED_MAGNITUDE:i64=4294967295",
    "requires index<0",
    "ensure result.i64()==(MAX_REPORTED_MAGNITUDE if index<(0-MAX_REPORTED_MAGNITUDE) else (0-index))",
    "if index<(0-MAX_REPORTED_MAGNITUDE):return MAX_REPORTED_MAGNITUDE.u32()",
    "return (0-index).u32()",
):
    if compact(fragment) not in compact(helper_text):
        raise SystemExit("negative-index magnitude helper no longer states or implements the checked saturation law")
unary_fn = compact(function_section(helper_text, "unary_minus_has_negative_index"))
if compact("ensure result == (magnitude > 0) return magnitude > 0") not in unary_fn:
    raise SystemExit("unary-minus literal classification no longer excludes zero")
saturated_fn = compact(function_section(helper_text, "magnitude_exceeds_reported_range"))
if ("requiresindex<0" not in saturated_fn or
        "ensureresult==(index<(0-MAX_REPORTED_MAGNITUDE))" not in saturated_fn or
        "returnindex<(0-MAX_REPORTED_MAGNITUDE)" not in saturated_fn):
    raise SystemExit("saturation marker no longer matches the exact representable-magnitude boundary")

consumer_text = CONSUMER.read_text()
if 'include "./negative_index_diagnostic.elisa"' not in consumer_text:
    raise SystemExit("negative-index pass no longer imports the proved diagnostic helper")
walk = function_section(consumer_text, "walk_expression_for_negative_index")
require_ordered(walk, (
    "if idx_value<0:",
    'actual:"magnitude exceeds u32" if NegativeIndexDiagnostic::magnitude_exceeds_reported_range(idx_value) else ""',
    "actual_count:NegativeIndexDiagnostic::reported_magnitude(idx_value)",
), "direct negative literal diagnostic")
require_ordered(walk, (
    "if unary_op==TokenKind.Minus:",
    "Expr.IntLit(pos_value,_):",
    "if NegativeIndexDiagnostic::unary_minus_has_negative_index(pos_value):",
    'actual:"magnitude exceeds u32" if NegativeIndexDiagnostic::magnitude_exceeds_reported_range(0-pos_value) else ""',
    "actual_count:NegativeIndexDiagnostic::reported_magnitude(0-pos_value)",
), "unary-minus literal diagnostic")
if "actual_count:u32=0" not in compact(DIAGNOSTIC_TYPES.read_text()):
    raise SystemExit("NegativeIndex diagnostic payload is no longer bounded by the proved u32 representation")
renderer = function_section(RENDERER.read_text(), "diagnostic_message_part2")
require_ordered(renderer, (
    'DiagnosticKind.NegativeIndex:',
    'if diagnostic.actual == "magnitude exceeds u32":',
    'push_str(buffer, "constant negative index magnitude exceeds ")',
    'push_int(buffer, 4294967295)',
    'else:',
    'push_str(buffer, "constant index -")',
    'push_int(buffer, diagnostic.actual_count.i64())',
    'buffer.extend(f" out of bounds for {diagnostic.expected}[")',
), "negative-index renderer")

positive_names = {
    "unary_minus_zero_is_not_a_negative_index",
    "unary_minus_positive_literal_is_a_negative_index",
    "every_representable_negative_magnitude_is_exact",
    "every_unrepresentable_negative_magnitude_saturates",
    "exact_u32_max_magnitude_is_not_marked_as_saturated",
    "unrepresentable_magnitude_is_marked_for_the_renderer",
    "u32_max_negative_index_is_reported_exactly",
    "one_beyond_u32_negative_index_saturates",
    "i64_min_negative_index_saturates_without_negation",
    "i64_min_negative_index_is_marked_for_the_renderer",
}
negative_names = {
    "unary_minus_zero_is_reported_as_negative",
    "magnitude_above_u32_is_never_saturated",
    "one_magnitude_is_always_marked_as_saturated",
}


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "../../src/semantic/negative_index_diagnostic.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer proves the production diagnostic helper")

positive_shapes = {
    "unary_minus_zero_is_not_a_negative_index": "ensure result == true return not NegativeIndexDiagnostic::unary_minus_has_negative_index(0)",
    "unary_minus_positive_literal_is_a_negative_index": "requires value > 0 ensure result == true return NegativeIndexDiagnostic::unary_minus_has_negative_index(value)",
    "every_representable_negative_magnitude_is_exact": "requires index < 0 and index >= (0 - 4294967295) ensure result == true return NegativeIndexDiagnostic::reported_magnitude(index).i64() == (0 - index)",
    "every_unrepresentable_negative_magnitude_saturates": "requires index < (0 - 4294967295) ensure result == true return NegativeIndexDiagnostic::reported_magnitude(index).i64() == 4294967295",
    "exact_u32_max_magnitude_is_not_marked_as_saturated": "ensure result == true return not NegativeIndexDiagnostic::magnitude_exceeds_reported_range(0 - 4294967295)",
    "unrepresentable_magnitude_is_marked_for_the_renderer": "requires index < (0 - 4294967295) ensure result == true return NegativeIndexDiagnostic::magnitude_exceeds_reported_range(index)",
    "u32_max_negative_index_is_reported_exactly": "ensure result == true return NegativeIndexDiagnostic::reported_magnitude(0 - 4294967295).i64() == 4294967295",
    "one_beyond_u32_negative_index_saturates": "ensure result == true return NegativeIndexDiagnostic::reported_magnitude(0 - 4294967296).i64() == 4294967295",
    "i64_min_negative_index_saturates_without_negation": "ensure result == true return NegativeIndexDiagnostic::reported_magnitude(0 - 9223372036854775807 - 1).i64() == 4294967295",
    "i64_min_negative_index_is_marked_for_the_renderer": "ensure result == true return NegativeIndexDiagnostic::magnitude_exceeds_reported_range(0 - 9223372036854775807 - 1)",
}
negative_shapes = {
    "unary_minus_zero_is_reported_as_negative": "ensure result == true return NegativeIndexDiagnostic::unary_minus_has_negative_index(0)",
    "magnitude_above_u32_is_never_saturated": "ensure result == true return NegativeIndexDiagnostic::reported_magnitude(0 - 4294967296).i64() == 4294967296",
    "one_magnitude_is_always_marked_as_saturated": "ensure result == true return NegativeIndexDiagnostic::magnitude_exceeds_reported_range(0 - 1)",
}
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    source_text = path.read_text()
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(source_text, name)):
            raise SystemExit(f"{name} no longer expresses the admitted diagnostic law")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("negative-index diagnostic proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", HELPER, CONSUMER,
    DIAGNOSTIC_TYPES, RENDERER, POSITIVE, NEGATIVE,
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


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
verified = {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert positive_names | {"reported_magnitude", "unary_minus_has_negative_index"} <= verified
assert positive == run(POSITIVE)[1], "negative-index diagnostic proof report changed across repeated runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert all(finding["status"] == "disproved" and finding["counterexample_found"]
           for finding in negative["findings"])
assert {"reported_magnitude", "magnitude_exceeds_reported_range", "unary_minus_has_negative_index"} <= {
    item["name"] for item in negative["declaration_details"] if item.get("verified")
}
assert product == require_current_product(BIN, PROVER)
if hashes_before != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}:
    raise SystemExit("negative-index diagnostic proof inputs changed during replay")

print(json.dumps({
    "admitted": True,
    "scope": "negative-index zero classification, u32-safe magnitude reporting, and diagnostic display",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
