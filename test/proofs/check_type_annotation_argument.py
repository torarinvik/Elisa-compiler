"""Source-bind the guarded annotation-side-table read to its proof."""
from __future__ import annotations

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
SOURCE = ROOT / "src/semantic/type_annotation_argument.elisa"
CONSUMER = ROOT / "src/semantic/check_unknown_type_annotation.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "type_annotation_argument.elisa"
NEGATIVE = HERE / "type_annotation_argument_rejected.elisa"

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

expected_spec = '''
ghost def first_argument_spec(arguments: darray[sview]&, arg_start: u32, arg_count: u32) -> sview:
    ensure (arg_count == 0 or arg_start.usize() >= arguments.count) implies result == ""
    ensure (arg_count > 0 and arg_start.usize() < arguments.count) implies result == arguments[arg_start.usize()]
    if arg_count == 0:
        return ""
    if arg_start.usize() >= arguments.count:
        return ""
    return arguments[arg_start.usize()]
'''
expected_accessor = '''
def first_argument(arguments: darray[sview]&, arg_start: u32, arg_count: u32) -> sview can[Abort.Panic]:
    ensure result == first_argument_spec(arguments, arg_start, arg_count)
    ensure (arg_count == 0 or arg_start.usize() >= arguments.count) implies result == ""
    ensure (arg_count > 0 and arg_start.usize() < arguments.count) implies result == arguments[arg_start.usize()]
    can Abort.Panic:
        if arg_count == 0:
            assert first_argument_spec(arguments, arg_start, arg_count) == ""
            return ""
        if arg_start.usize() >= arguments.count:
            assert first_argument_spec(arguments, arg_start, arg_count) == ""
            return ""
        assert arg_count > 0
        assert arg_start.usize() < arguments.count
        assert not (arg_count == 0 or arg_start.usize() >= arguments.count)
        assert first_argument_spec(arguments, arg_start, arg_count) == arguments[arg_start.usize()]
        return arguments[arg_start.usize()]
'''
if "moduleSemanticTypeAnnotationArgument:" not in compact(source_text):
    raise SystemExit("annotation argument accessor moved outside its source-linked module")
if compact(function_section(source_text, "first_argument_spec")) != compact(expected_spec):
    raise SystemExit("annotation argument reference model changed")
if compact(function_section(source_text, "first_argument")) != compact(expected_accessor):
    raise SystemExit("production annotation argument read lost its guarded contract")
if consumer_text.count('include "./type_annotation_argument.elisa"') != 1 or \
        "SemanticTypeAnnotationArgument::first_argument(file.annotation_args,annotation.arg_start,annotation.arg_count)" not in compact(consumer_text):
    raise SystemExit("type annotation semantic pass no longer uses the proved guarded accessor")
if semantic_text.count('include "./check_unknown_type_annotation.elisa"') != 1:
    raise SystemExit("semantic root must include the type annotation consumer exactly once")
if 'include "../../src/semantic/type_annotation_argument.elisa"' not in positive_text or \
        'include "./type_annotation_argument.elisa"' not in negative_text:
    raise SystemExit("annotation argument proof files must import the production accessor")

positive_names = {
    "production_accessor_matches_reference",
    "empty_table_returns_empty_argument",
    "zero_argument_count_returns_empty_view",
    "start_at_table_end_returns_empty_view",
    "last_valid_start_returns_last_argument",
    "multiple_arguments_still_select_the_first",
}
negative_names = {
    "false_claim_zero_count_returns_present_argument",
    "false_claim_one_past_end_returns_last_argument",
    "false_claim_multi_argument_slice_selects_last",
}
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("annotation argument proof inventory changed")

positive_cases = {
    "production_accessor_matches_reference": '''
def production_accessor_matches_reference(arguments: darray[sview]&, arg_start: u32, arg_count: u32) -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticTypeAnnotationArgument::first_argument(arguments, arg_start, arg_count) == SemanticTypeAnnotationArgument::first_argument_spec(arguments, arg_start, arg_count)
''',
    "empty_table_returns_empty_argument": '''
def empty_table_returns_empty_argument() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        arguments: darray[sview] = []
        return SemanticTypeAnnotationArgument::first_argument(arguments, 0, 1) == ""
''',
    "zero_argument_count_returns_empty_view": '''
def zero_argument_count_returns_empty_view() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        arguments: darray[sview] = ["present"]
        return SemanticTypeAnnotationArgument::first_argument(arguments, 0, 0) == ""
''',
    "start_at_table_end_returns_empty_view": '''
def start_at_table_end_returns_empty_view() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        arguments: darray[sview] = ["first", "last"]
        return SemanticTypeAnnotationArgument::first_argument(arguments, 2, 1) == ""
''',
    "last_valid_start_returns_last_argument": '''
def last_valid_start_returns_last_argument() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        arguments: darray[sview] = ["first", "last"]
        return SemanticTypeAnnotationArgument::first_argument(arguments, 1, 1) == "last"
''',
    "multiple_arguments_still_select_the_first": '''
def multiple_arguments_still_select_the_first() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        arguments: darray[sview] = ["first", "second", "third"]
        return SemanticTypeAnnotationArgument::first_argument(arguments, 0, 3) == "first"
''',
}
for name, expected in positive_cases.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"positive theorem {name} changed without updating the source-bound gate")

negative_cases = {
    "false_claim_zero_count_returns_present_argument": '''
def false_claim_zero_count_returns_present_argument() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        arguments: darray[sview] = ["present"]
        return SemanticTypeAnnotationArgument::first_argument(arguments, 0, 0) == "present"
''',
    "false_claim_one_past_end_returns_last_argument": '''
def false_claim_one_past_end_returns_last_argument() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        arguments: darray[sview] = ["first", "last"]
        return SemanticTypeAnnotationArgument::first_argument(arguments, 2, 1) == "last"
''',
    "false_claim_multi_argument_slice_selects_last": '''
def false_claim_multi_argument_slice_selects_last() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        arguments: darray[sview] = ["first", "second"]
        return SemanticTypeAnnotationArgument::first_argument(arguments, 0, 2) == "second"
''',
}
for name, expected in negative_cases.items():
    if compact(function_section(negative_text, name)) != compact(expected):
        raise SystemExit(f"false-claim theorem {name} changed without updating the source-bound gate")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("annotation argument proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, CONSUMER, SEMANTIC,
    POSITIVE, NEGATIVE, *source_closure,
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
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "annotation argument proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_after == hashes_before, "proof inputs changed during admission"
