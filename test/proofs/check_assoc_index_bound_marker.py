"""Source-bind generic-bound marker lookup in the associated-index checker."""
from __future__ import annotations

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
SOURCE = ROOT / "src/semantic/assoc_index_bound_marker.elisa"
CONSUMER = ROOT / "src/semantic/check_assoc_index_bounds.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "assoc_index_bound_marker.elisa"
NEGATIVE = HERE / "assoc_index_bound_marker_rejected.elisa"
POSITIVE_NAMES = {
    "production_scan_matches_recursive_marker_specification",
    "exact_encoded_function_line_is_found",
    "ordinary_generic_parameter_line_is_not_a_bound_marker",
    "empty_side_table_has_no_marker",
    "duplicate_marker_rows_preserve_presence",
}
NEGATIVE_NAMES = {"ordinary_parameter_line_is_a_bound_marker"}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost )?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost )?def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*(?:ghost )?def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


source_text = SOURCE.read_text()
consumer_text = CONSUMER.read_text()
semantic_text = SEMANTIC.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_model = '''
ghost def contains_from(lines: darray[u32]&, target_line: u32, index: usize) -> bool:
    requires index <= lines.count
    decreases lines.count - index
    return false if index == lines.count
    return true if lines[index] == target_line
    return contains_from(lines, target_line, index + 1)
'''
expected_scan = '''
def contains(lines: darray[u32]&, target_line: u32) -> bool:
    ensure result == contains_from(lines, target_line, 0)
    for index in 0..<lines.count |index|:
        invariant index <= lines.count
        invariant contains_from(lines, target_line, index) == contains_from(lines, target_line, 0)
        return true if lines[index] == target_line
    return false
'''
if compact(function_section(source_text, "contains_from")) != compact(expected_model):
    raise SystemExit("recursive bound-marker model changed without updating its proof")
if compact(function_section(source_text, "contains")) != compact(expected_scan):
    raise SystemExit("production bound-marker scan no longer refines its recursive model")
if consumer_text.count('include "./assoc_index_bound_marker.elisa"') != 1:
    raise SystemExit("associated-index checker must include the isolated bound-marker scan exactly once")
expected_consumer = '''
def aib_function_has_bound(file: Ast::File&, func_line: u32) -> bool:
    ensure result == SemanticAssocIndexBoundMarker::contains(file.generic_param_lines, func_line + 2147483648)
    return SemanticAssocIndexBoundMarker::contains(file.generic_param_lines, func_line + 2147483648)
'''
if compact(function_section(consumer_text, "aib_function_has_bound")) != compact(expected_consumer):
    raise SystemExit("semantic bound detection must use the proved lookup on the encoded function line")
if consumer_text.count("aib_function_has_bound(file, line.line)") != 1:
    raise SystemExit("declaration analysis must activate from exactly one bound-marker lookup")
if semantic_text.count('include "./check_assoc_index_bounds.elisa"') != 1:
    raise SystemExit("semantic root must include the associated-index checker exactly once")
if 'include "../../src/semantic/assoc_index_bound_marker.elisa"' not in positive_text or \
        'include "./assoc_index_bound_marker.elisa"' not in negative_text:
    raise SystemExit("proof candidates must import the production bound-marker implementation")
if declarations(positive_text) != POSITIVE_NAMES or declarations(negative_text) != NEGATIVE_NAMES:
    raise SystemExit("bound-marker proof declaration inventory changed")

expected_positive = {
    "production_scan_matches_recursive_marker_specification": '''
def production_scan_matches_recursive_marker_specification(lines: darray[u32]&, target_line: u32) -> bool:
    ensure result == true
    return SemanticAssocIndexBoundMarker::contains(lines, target_line) == SemanticAssocIndexBoundMarker::contains_from(lines, target_line, 0)
''',
    "exact_encoded_function_line_is_found": '''
def exact_encoded_function_line_is_found() -> bool:
    ensure result == true
    lines: darray[u32] = [7, 2147483655, 11]
    return SemanticAssocIndexBoundMarker::contains(lines, 2147483655)
''',
    "ordinary_generic_parameter_line_is_not_a_bound_marker": '''
def ordinary_generic_parameter_line_is_not_a_bound_marker() -> bool:
    ensure result == true
    lines: darray[u32] = [7, 11]
    return not SemanticAssocIndexBoundMarker::contains(lines, 2147483655)
''',
    "empty_side_table_has_no_marker": '''
def empty_side_table_has_no_marker() -> bool:
    ensure result == true
    lines: darray[u32] = []
    return not SemanticAssocIndexBoundMarker::contains(lines, 2147483655)
''',
    "duplicate_marker_rows_preserve_presence": '''
def duplicate_marker_rows_preserve_presence() -> bool:
    ensure result == true
    lines: darray[u32] = [2147483655, 2147483655]
    return SemanticAssocIndexBoundMarker::contains(lines, 2147483655)
''',
}
for name, expected in expected_positive.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"positive theorem {name} changed without updating its source-bound proof gate")

expected_negative = '''
def ordinary_parameter_line_is_a_bound_marker() -> bool:
    ensure result == true
    lines: darray[u32] = [7, 11]
    return SemanticAssocIndexBoundMarker::contains(lines, 7 + 2147483648)
'''
if compact(function_section(negative_text, "ordinary_parameter_line_is_a_bound_marker")) != compact(expected_negative):
    raise SystemExit("rejected control must conflate an ordinary source line with a bound-marker row")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("bound-marker proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    SOURCE,
    CONSUMER,
    SEMANTIC,
    POSITIVE,
    NEGATIVE,
    *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
verified_positive = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert POSITIVE_NAMES | {"contains", "contains_from"} <= verified_positive

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in NEGATIVE_NAMES
}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "exact high-bit generic-bound marker lookup",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
