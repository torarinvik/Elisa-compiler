"""Source-bind exact annotation name policies to the semantic checker."""
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
SOURCE = ROOT / "src/semantic/type_annotation_policy.elisa"
CONSUMER = ROOT / "src/semantic/check_unknown_type_annotation.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "type_annotation_policy.elisa"
NEGATIVE = HERE / "type_annotation_policy_rejected.elisa"

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

expected_functions = {
    "supported_struct_annotation": '''
def supported_struct_annotation(name: sview) -> bool:
    ensure result == (name == "align" or name == "fixed_layout" or name == "c_bind" or name == "abi_layout" or name == "intrusive" or name == "append_only")
    return when name:
        "align" | "fixed_layout" | "c_bind" | "abi_layout" | "intrusive" | "append_only" -> true
        _ -> false
''',
    "supported_enum_annotation": '''
def supported_enum_annotation(name: sview) -> bool:
    ensure result == (name == "packed_profile")
    return when name:
        "packed_profile" -> true
        _ -> false
''',
    "removed_annotation_name": '''
def removed_annotation_name(name: sview) -> bool:
    ensure result == (name == "ignore" or name == "c_abi" or name == "stdcall" or name == "cacheline_aligned" or name == "c_bind_prefix" or name == "borrows_return_field" or name == "borrows_return_rebased" or name == "borrows_return_field_rebased" or name == "packed_abi" or name == "packed_prefix")
    return when name:
        "ignore" | "c_abi" | "stdcall" | "cacheline_aligned" | "c_bind_prefix" | "borrows_return_field" | "borrows_return_rebased" | "borrows_return_field_rebased" | "packed_abi" | "packed_prefix" -> true
        _ -> false
''',
}
if "moduleSemanticTypeAnnotationPolicy:" not in compact(source_text):
    raise SystemExit("annotation name tables moved outside the source-linked policy module")
for name, expected in expected_functions.items():
    if compact(function_section(source_text, name)) != compact(expected):
        raise SystemExit(f"{name} changed without updating its exact finite-set proof")

if consumer_text.count('include "./type_annotation_policy.elisa"') != 1:
    raise SystemExit("type annotation consumer must include the policy module exactly once")
consumer = compact(consumer_text)
for use in (
    "SemanticTypeAnnotationPolicy::supported_struct_annotation(annotation.detail_name)",
    "SemanticTypeAnnotationPolicy::supported_enum_annotation(annotation.detail_name)",
    "SemanticTypeAnnotationPolicy::removed_annotation_name(annotation.detail_name)",
):
    if use not in consumer:
        raise SystemExit(f"annotation consumer no longer uses {use}")
if semantic_text.count('include "./check_unknown_type_annotation.elisa"') != 1:
    raise SystemExit("semantic root must include the type annotation consumer exactly once")
if 'include "../../src/semantic/type_annotation_policy.elisa"' not in positive_text or \
        'include "./type_annotation_policy.elisa"' not in negative_text:
    raise SystemExit("policy proof files must import the production implementation")

positive_names = {
    "all_supported_struct_spellings_are_allowed",
    "unknown_struct_spellings_are_not_allowed",
    "packed_profile_is_enum_only",
    "struct_only_names_are_not_enum_annotations",
    "every_retired_spelling_is_classified_as_removed",
    "live_annotation_names_are_not_classified_as_removed",
}
negative_names = {
    "false_claim_struct_policy_accepts_enum_name",
    "false_claim_enum_policy_accepts_struct_name",
    "false_claim_unknown_name_is_retired",
    "false_claim_c_abi_is_live",
}
if declarations(positive_text) != positive_names:
    raise SystemExit("type annotation policy positive proof inventory changed")
if declarations(negative_text) != negative_names:
    raise SystemExit("type annotation policy false-claim inventory changed")

positive_cases = {
    "all_supported_struct_spellings_are_allowed": '''
def all_supported_struct_spellings_are_allowed() -> bool:
    ensure result == true
    return SemanticTypeAnnotationPolicy::supported_struct_annotation("align")
        and SemanticTypeAnnotationPolicy::supported_struct_annotation("fixed_layout")
        and SemanticTypeAnnotationPolicy::supported_struct_annotation("c_bind")
        and SemanticTypeAnnotationPolicy::supported_struct_annotation("abi_layout")
        and SemanticTypeAnnotationPolicy::supported_struct_annotation("intrusive")
        and SemanticTypeAnnotationPolicy::supported_struct_annotation("append_only")
''',
    "unknown_struct_spellings_are_not_allowed": '''
def unknown_struct_spellings_are_not_allowed() -> bool:
    ensure result == true
    return not SemanticTypeAnnotationPolicy::supported_struct_annotation("packed_profile")
        and not SemanticTypeAnnotationPolicy::supported_struct_annotation("user_annotation")
''',
    "packed_profile_is_enum_only": '''
def packed_profile_is_enum_only() -> bool:
    ensure result == true
    return SemanticTypeAnnotationPolicy::supported_enum_annotation("packed_profile")
        and not SemanticTypeAnnotationPolicy::supported_struct_annotation("packed_profile")
''',
    "struct_only_names_are_not_enum_annotations": '''
def struct_only_names_are_not_enum_annotations() -> bool:
    ensure result == true
    return not SemanticTypeAnnotationPolicy::supported_enum_annotation("align")
        and not SemanticTypeAnnotationPolicy::supported_enum_annotation("fixed_layout")
''',
    "every_retired_spelling_is_classified_as_removed": '''
def every_retired_spelling_is_classified_as_removed() -> bool:
    ensure result == true
    return SemanticTypeAnnotationPolicy::removed_annotation_name("ignore")
        and SemanticTypeAnnotationPolicy::removed_annotation_name("c_abi")
        and SemanticTypeAnnotationPolicy::removed_annotation_name("stdcall")
        and SemanticTypeAnnotationPolicy::removed_annotation_name("cacheline_aligned")
        and SemanticTypeAnnotationPolicy::removed_annotation_name("c_bind_prefix")
        and SemanticTypeAnnotationPolicy::removed_annotation_name("borrows_return_field")
        and SemanticTypeAnnotationPolicy::removed_annotation_name("borrows_return_rebased")
        and SemanticTypeAnnotationPolicy::removed_annotation_name("borrows_return_field_rebased")
        and SemanticTypeAnnotationPolicy::removed_annotation_name("packed_abi")
        and SemanticTypeAnnotationPolicy::removed_annotation_name("packed_prefix")
''',
    "live_annotation_names_are_not_classified_as_removed": '''
def live_annotation_names_are_not_classified_as_removed() -> bool:
    ensure result == true
    return not SemanticTypeAnnotationPolicy::removed_annotation_name("align")
        and not SemanticTypeAnnotationPolicy::removed_annotation_name("packed_profile")
        and not SemanticTypeAnnotationPolicy::removed_annotation_name("user_annotation")
''',
}
for name, expected in positive_cases.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"positive theorem {name} changed without updating the source-bound gate")

negative_cases = {
    "false_claim_struct_policy_accepts_enum_name": '''
def false_claim_struct_policy_accepts_enum_name() -> bool:
    ensure result == true
    return SemanticTypeAnnotationPolicy::supported_struct_annotation("packed_profile")
''',
    "false_claim_enum_policy_accepts_struct_name": '''
def false_claim_enum_policy_accepts_struct_name() -> bool:
    ensure result == true
    return SemanticTypeAnnotationPolicy::supported_enum_annotation("align")
''',
    "false_claim_unknown_name_is_retired": '''
def false_claim_unknown_name_is_retired() -> bool:
    ensure result == true
    return SemanticTypeAnnotationPolicy::removed_annotation_name("user_annotation")
''',
    "false_claim_c_abi_is_live": '''
def false_claim_c_abi_is_live() -> bool:
    ensure result == true
    return not SemanticTypeAnnotationPolicy::removed_annotation_name("c_abi")
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
    raise SystemExit("annotation policy proofs require a strict proof build")

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
assert positive == run(POSITIVE)[1], "annotation policy report changed across identical runs"
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
