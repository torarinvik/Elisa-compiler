"""Source-bind and replay declaration-name position lookup proofs."""
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
LOOKUP = ROOT / "src/semantic/declaration_name_position_lookup.elisa"
SYMBOLS = ROOT / "src/semantic/symbols.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "declaration_name_position_lookup.elisa"
NEGATIVE = HERE / "declaration_name_position_lookup_rejected.elisa"
POSITIVE_NAMES = {
    "declaration_name_lookup_matches_the_reference_model",
    "duplicate_exact_name_annotations_keep_the_first_position",
    "synthetic_declaration_uses_the_first_same_line_name",
    "nonzero_offset_does_not_fall_back_to_a_same_line_name",
    "unrelated_annotations_are_skipped",
}
NEGATIVE_NAMES = {"duplicate_exact_name_annotations_choose_the_last_position"}

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


def declarations(text: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*(?:ghost )?def ([A-Za-z_][A-Za-z0-9_]*)\(", text))


lookup_text = LOOKUP.read_text()
symbols_text = SYMBOLS.read_text()
semantic_text = SEMANTIC.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_reference = '''
ghost def declaration_name_position_from(annotations: darray[Ast::EnumAnnotation]&, name: sview, declaration_offset: u32, declaration_line: u32, index: usize) -> Ast::Pos:
    requires index <= annotations.count
    decreases annotations.count - index
    return Ast::Pos{line: 0, column: 0, offset: 0, end_line: 0, end_column: 0, end_offset: 0} if index == annotations.count
    annotation: Ast::EnumAnnotation = annotations[index]
    eligible: bool = annotation.owner == "__lsp_decl_name" and annotation.name == name and annotation.line == declaration_line and (annotation.offset == declaration_offset or declaration_offset == 0)
    return annotation.pos if eligible
    return declaration_name_position_from(annotations, name, declaration_offset, declaration_line, index + 1)
'''
if compact(function_section(lookup_text, "declaration_name_position_from")) != compact(expected_reference):
    raise SystemExit("recursive first-eligible-name reference model changed without updating its proof")

expected_lookup = '''
def declaration_name_position(annotations: darray[Ast::EnumAnnotation]&, name: sview, declaration_offset: u32, declaration_line: u32) -> Ast::Pos:
    ensure Ast::pos_equal(result, declaration_name_position_from(annotations, name, declaration_offset, declaration_line, 0))
    can Abort.Panic:
        for index in 0..<annotations.count |index|:
            invariant index <= annotations.count
            invariant Ast::pos_equal(declaration_name_position_from(annotations, name, declaration_offset, declaration_line, index), declaration_name_position_from(annotations, name, declaration_offset, declaration_line, 0))
            annotation: Ast::EnumAnnotation = annotations[index]
            eligible: bool = annotation.owner == "__lsp_decl_name" and annotation.name == name and annotation.line == declaration_line and (annotation.offset == declaration_offset or declaration_offset == 0)
            return annotation.pos if eligible
        return Ast::Pos{line: 0, column: 0, offset: 0, end_line: 0, end_column: 0, end_offset: 0}
'''
if compact(function_section(lookup_text, "declaration_name_position")) != compact(expected_lookup):
    raise SystemExit("production name-position scan no longer refines the recursive first-match model")

policy_include = 'include "./declaration_name_position_lookup.elisa"'
if symbols_text.count(policy_include) != 1 or symbols_text.index(policy_include) > symbols_text.index("declaration_name_position("):
    raise SystemExit("symbol collection must include the contracted lookup before its call sites")
if "def declaration_name_position(" in symbols_text:
    raise SystemExit("symbol collection must use the isolated, source-bound lookup implementation")
if semantic_text.count('include "./symbols.elisa"') != 1:
    raise SystemExit("semantic facade must include symbol collection exactly once")
symbol_call_count = len(re.findall(r"(?<!def )declaration_name_position\(decl_name_annotations,", symbols_text))
if symbol_call_count != 8:
    raise SystemExit(f"expected eight declaration-position consumers, found {symbol_call_count}")

if 'include "../../src/parser/parser_tokens.elisa"' not in positive_text or \
        'include "../../src/semantic/declaration_name_position_lookup.elisa"' not in positive_text or \
        'include "./declaration_name_position_lookup.elisa"' not in negative_text:
    raise SystemExit("positive and rejected proofs must import the exact production lookup implementation")
if declarations(positive_text) != POSITIVE_NAMES or declarations(negative_text) != NEGATIVE_NAMES:
    raise SystemExit("declaration-name position proof inventory changed")

positive_shapes = {
    "declaration_name_lookup_matches_the_reference_model": '''
def declaration_name_lookup_matches_the_reference_model(annotations: darray[Ast::EnumAnnotation]&, name: sview, declaration_offset: u32, declaration_line: u32) -> bool:
    ensure result == true
    can Abort.Panic:
        actual: Ast::Pos = declaration_name_position(annotations, name, declaration_offset, declaration_line)
        expected: Ast::Pos = declaration_name_position_from(annotations, name, declaration_offset, declaration_line, 0)
        return Ast::pos_equal(actual, expected)
''',
    "duplicate_exact_name_annotations_keep_the_first_position": '''
def duplicate_exact_name_annotations_keep_the_first_position() -> bool:
    ensure result == true
    annotations: darray[Ast::EnumAnnotation] = [
        Ast::EnumAnnotation{owner: "__lsp_decl_name", name: "Target", line: 7, offset: 40, pos: Ast::Pos{line: 7, column: 3, offset: 40, end_line: 7, end_column: 9, end_offset: 46}},
        Ast::EnumAnnotation{owner: "__lsp_decl_name", name: "Target", line: 7, offset: 40, pos: Ast::Pos{line: 7, column: 14, offset: 51, end_line: 7, end_column: 20, end_offset: 57}}
    ]
    can Abort.Panic:
        actual: Ast::Pos = declaration_name_position(annotations, "Target", 40, 7)
        return Ast::pos_equal(actual, Ast::Pos{line: 7, column: 3, offset: 40, end_line: 7, end_column: 9, end_offset: 46})
''',
    "synthetic_declaration_uses_the_first_same_line_name": '''
def synthetic_declaration_uses_the_first_same_line_name() -> bool:
    ensure result == true
    annotations: darray[Ast::EnumAnnotation] = [
        Ast::EnumAnnotation{owner: "__lsp_decl_name", name: "Target", line: 8, offset: 73, pos: Ast::Pos{line: 8, column: 4, offset: 73, end_line: 8, end_column: 10, end_offset: 79}},
        Ast::EnumAnnotation{owner: "__lsp_decl_name", name: "Target", line: 8, offset: 80, pos: Ast::Pos{line: 8, column: 11, offset: 80, end_line: 8, end_column: 17, end_offset: 86}}
    ]
    can Abort.Panic:
        actual: Ast::Pos = declaration_name_position(annotations, "Target", 0, 8)
        return Ast::pos_equal(actual, Ast::Pos{line: 8, column: 4, offset: 73, end_line: 8, end_column: 10, end_offset: 79})
''',
    "nonzero_offset_does_not_fall_back_to_a_same_line_name": '''
def nonzero_offset_does_not_fall_back_to_a_same_line_name() -> bool:
    ensure result == true
    annotations: darray[Ast::EnumAnnotation] = [
        Ast::EnumAnnotation{owner: "__lsp_decl_name", name: "Target", line: 9, offset: 73, pos: Ast::Pos{line: 9, column: 4, offset: 73, end_line: 9, end_column: 10, end_offset: 79}}
    ]
    can Abort.Panic:
        actual: Ast::Pos = declaration_name_position(annotations, "Target", 99, 9)
        return Ast::pos_equal(actual, Ast::Pos{line: 0, column: 0, offset: 0, end_line: 0, end_column: 0, end_offset: 0})
''',
    "unrelated_annotations_are_skipped": '''
def unrelated_annotations_are_skipped() -> bool:
    ensure result == true
    expected: Ast::Pos = Ast::Pos{line: 10, column: 6, offset: 91, end_line: 10, end_column: 12, end_offset: 97}
    annotations: darray[Ast::EnumAnnotation] = [
        Ast::EnumAnnotation{owner: "__other", name: "Target", line: 10, offset: 91, pos: Ast::Pos{line: 10, column: 1, offset: 86, end_line: 10, end_column: 7, end_offset: 92}},
        Ast::EnumAnnotation{owner: "__lsp_decl_name", name: "Other", line: 10, offset: 91, pos: Ast::Pos{line: 10, column: 2, offset: 87, end_line: 10, end_column: 7, end_offset: 92}},
        Ast::EnumAnnotation{owner: "__lsp_decl_name", name: "Target", line: 11, offset: 91, pos: Ast::Pos{line: 11, column: 2, offset: 87, end_line: 11, end_column: 8, end_offset: 93}},
        Ast::EnumAnnotation{owner: "__lsp_decl_name", name: "Target", line: 10, offset: 91, pos: expected}
    ]
    can Abort.Panic:
        actual: Ast::Pos = declaration_name_position(annotations, "Target", 91, 10)
        return Ast::pos_equal(actual, expected)
''',
}
for name, expected in positive_shapes.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"positive theorem {name} changed without updating its source-bound proof gate")
if "offset == declaration_offset or declaration_offset == 0" not in lookup_text:
    raise SystemExit("production lookup must preserve exact and synthetic-offset matching modes")

expected_negative = '''
def duplicate_exact_name_annotations_choose_the_last_position() -> bool:
    ensure result == true
    annotations: darray[Ast::EnumAnnotation] = [
        Ast::EnumAnnotation{owner: "__lsp_decl_name", name: "Target", line: 7, offset: 40, pos: Ast::Pos{line: 7, column: 3, offset: 40, end_line: 7, end_column: 9, end_offset: 46}},
        Ast::EnumAnnotation{owner: "__lsp_decl_name", name: "Target", line: 7, offset: 40, pos: Ast::Pos{line: 7, column: 14, offset: 51, end_line: 7, end_column: 20, end_offset: 57}}
    ]
    can Abort.Panic:
        actual: Ast::Pos = declaration_name_position(annotations, "Target", 40, 7)
        return Ast::pos_equal(actual, Ast::Pos{line: 7, column: 14, offset: 51, end_line: 7, end_column: 20, end_offset: 57})
'''
if compact(function_section(negative_text, "duplicate_exact_name_annotations_choose_the_last_position")) != compact(expected_negative):
    raise SystemExit("rejected control must claim the last position for duplicate exact matches")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("declaration-name position proof requires a strict proof build")

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
    LOOKUP,
    SYMBOLS,
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
assert POSITIVE_NAMES <= verified_positive
assert {"declaration_name_position", "declaration_name_position_from"} <= verified_positive

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in NEGATIVE_NAMES
}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "first eligible exact-offset or synthetic line-only declaration-name position",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
