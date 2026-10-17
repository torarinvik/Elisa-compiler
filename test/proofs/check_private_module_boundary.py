"""Bind private-module visibility proofs to the production semantic helper."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


from source_guard_compat import expand_return_if_blocks
ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
SOURCE = ROOT / "src/semantic/private_module_boundary.elisa"
CONSUMER = ROOT / "src/semantic/check_private_member_access.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "private_module_boundary.elisa"
NEGATIVE = HERE / "private_module_boundary_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking the proof product")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in expand_return_if_blocks(source).splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


source_text = SOURCE.read_text()
consumer_text = CONSUMER.read_text()
semantic_text = SEMANTIC.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_prefix = '''
def prefix_matches(text: sview, prefix: sview) -> bool:
    ensure result == (
        text.len >= prefix.len and
        (forall index in 0..<text.len:
            index >= prefix.len or text[index] == prefix[index]
        )
    )
    false return if text.len < prefix.len
    while index < prefix.len |index: usize = 0, text, prefix|:
        decreases prefix.len - index
        invariant index <= prefix.len and prefix.len <= text.len
        invariant forall checked in 0..<index: text[checked] == prefix[checked]
        false return if text[index] != prefix[index]
        index <- index + 1.usize()
    assert forall checked in 0..<prefix.len:
        text[checked] == prefix[checked]
    return true
'''
expected_within = '''
def within_module(current_module: sview, owner: sview) -> bool can[Abort.Panic]:
    ensure result == (
        current_module == owner or (
            owner.len > 0 and
            current_module.len > owner.len and
            current_module.len - owner.len > MODULE_SEPARATOR_LENGTH and
            prefix_matches(current_module, owner) and
            current_module[owner.len] == ASCII_COLON and
            current_module[owner.len + 1.usize()] == ASCII_COLON
        )
    )
    can Abort.Panic:
        true return if current_module == owner
        false return if owner.len == 0 or current_module.len <= owner.len
        false return if current_module.len - owner.len <= MODULE_SEPARATOR_LENGTH
        false return if not prefix_matches(current_module, owner)
        return current_module[owner.len] == ASCII_COLON and
            current_module[owner.len + 1.usize()] == ASCII_COLON
'''
if "moduleSemanticPrivateModuleBoundary:" not in compact(source_text) or \
        "constASCII_COLON:u8=58" not in compact(source_text) or \
        "constMODULE_SEPARATOR_LENGTH:usize=2" not in compact(source_text):
    raise SystemExit("private-module boundary helper or its exact delimiter constants are missing")
if compact(function_section(source_text, "prefix_matches")) != compact(expected_prefix):
    raise SystemExit("prefix matcher changed without updating its source-bound proof")
if compact(function_section(source_text, "within_module")) != compact(expected_within):
    raise SystemExit("module-boundary predicate changed without updating its source-bound proof")
if consumer_text.count('include "./private_module_boundary.elisa"') != 1:
    raise SystemExit("private-member checker must include the proved module-boundary helper exactly once")
if semantic_text.count('include "./check_private_member_access.elisa"') != 1:
    raise SystemExit("semantic root must include the private-member checker exactly once")
if "pma_prefix_matches" in consumer_text:
    raise SystemExit("duplicate private path-prefix logic must remain removed from the semantic checker")
consumer = compact(function_section(consumer_text, "pma_within_module"))
if consumer != compact('''
def pma_within_module(current_module: sview, owner: sview) -> bool:
    can Abort.Panic:
        return SemanticPrivateModuleBoundary::within_module(current_module, owner)
'''):
    raise SystemExit("production private-member boundary wrapper no longer delegates to the proved helper")
if "pma_within_module(current_module,owner)" not in compact(function_section(consumer_text, "pma_unqualified_owner")) or \
        "pma_within_module(current_module,owner)" not in compact(function_section(consumer_text, "pma_report_scope_member")):
    raise SystemExit("qualified and unqualified private-member checks must share the proved boundary predicate")

if 'include "../../src/semantic/private_module_boundary.elisa"' not in positive_text or \
        'include "./private_module_boundary.elisa"' not in negative_text:
    raise SystemExit("boundary proof fixtures must include the production helper")
positive_names = {
    "prefix_classifier_matches_its_bytewise_spec",
    "module_containment_classifier_matches_exact_separator_spec",
    "owner_and_descendant_are_inside_private_boundary",
    "similar_prefix_and_parent_are_outside_private_boundary",
    "empty_owner_only_contains_the_identical_empty_path",
}
negative_names = {
    "false_claim_similar_textual_prefix_is_a_child",
    "false_claim_parent_module_is_inside_child_boundary",
    "false_claim_separator_without_child_is_a_descendant",
}
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("private-module boundary proof inventory changed")

expected_positive_claims = {
    "prefix_classifier_matches_its_bytewise_spec": "SemanticPrivateModuleBoundary::prefix_matches(text,prefix)==(text.len>=prefix.lenand(forallindexin0..<text.len:index>=prefix.lenortext[index]==prefix[index]))",
    "module_containment_classifier_matches_exact_separator_spec": "SemanticPrivateModuleBoundary::within_module(current_module,owner)==(current_module==owneror(owner.len>0andcurrent_module.len>owner.lenandcurrent_module.len-owner.len>SemanticPrivateModuleBoundary::MODULE_SEPARATOR_LENGTHandSemanticPrivateModuleBoundary::prefix_matches(current_module,owner)andcurrent_module[owner.len]==SemanticPrivateModuleBoundary::ASCII_COLONandcurrent_module[owner.len+1.usize()]==SemanticPrivateModuleBoundary::ASCII_COLON))",
    "owner_and_descendant_are_inside_private_boundary": 'SemanticPrivateModuleBoundary::within_module("A::Paint","A::Paint")andSemanticPrivateModuleBoundary::within_module("A::Paint::Brush","A::Paint")andSemanticPrivateModuleBoundary::within_module("A::Paint::Brush::Wet","A::Paint")',
    "similar_prefix_and_parent_are_outside_private_boundary": 'notSemanticPrivateModuleBoundary::within_module("A::Painter::Brush","A::Paint")andnotSemanticPrivateModuleBoundary::within_module("A","A::Paint")andnotSemanticPrivateModuleBoundary::within_module("A::Paint::","A::Paint")',
    "empty_owner_only_contains_the_identical_empty_path": 'SemanticPrivateModuleBoundary::within_module("","")andnotSemanticPrivateModuleBoundary::within_module("A","")',
}
expected_negative_claims = {
    "false_claim_similar_textual_prefix_is_a_child": 'SemanticPrivateModuleBoundary::within_module("A::Painter","A::Paint")',
    "false_claim_parent_module_is_inside_child_boundary": 'SemanticPrivateModuleBoundary::within_module("A","A::Paint")',
    "false_claim_separator_without_child_is_a_descendant": 'SemanticPrivateModuleBoundary::within_module("A::Paint::","A::Paint")',
}
for name, claim in expected_positive_claims.items():
    section = compact(function_section(positive_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"positive proof {name} no longer establishes its source-bound claim")
for name, claim in expected_negative_claims.items():
    section = compact(function_section(negative_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"false-claim control {name} no longer asserts the rejected claim")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive": len(positive_names),
                      "false_claim_controls": len(negative_names)}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("private-module boundary proofs require a strict proof build")

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
assert positive == run(POSITIVE)[1], "private-module boundary proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_after == hashes_before, "private-module boundary proof inputs changed during admission"
