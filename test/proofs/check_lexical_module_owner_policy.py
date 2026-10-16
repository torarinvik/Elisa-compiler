"""Bind lexical owner proofs to all semantic visibility consumers."""
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
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/semantic/lexical_module_owner_policy.elisa"
CONSUMER = ROOT / "src/semantic/check_named_type_mismatch.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
BINDING_RESOLVER = ROOT / "src/semantic/resolve_binding_capabilities.elisa"
STATIC_STRING = ROOT / "src/semantic/check_static_string_binding.elisa"
POSITIVE = HERE / "lexical_module_owner_policy.elisa"
NEGATIVE = HERE / "lexical_module_owner_policy_rejected.elisa"

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


policy_text = POLICY.read_text()
consumer_text = CONSUMER.read_text()
semantic_text = SEMANTIC.read_text()
binding_text = BINDING_RESOLVER.read_text()
static_string_text = STATIC_STRING.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_policy = '''
def is_lexical(owner: sview, current: sview) -> bool:
    ensure result == (
        owner == "" or owner == current or (
            current.len >= 2 and
            owner.len <= current.len - 2 and
            current[owner.len] == 58 and
            current[owner.len + 1.usize()] == 58 and
            (forall index in 0..<owner.len:
                owner[index] == current[index]
            )
        )
    )
    can Abort.Panic:
        return (
            owner == "" or owner == current or (
                current.len >= 2 and
                owner.len <= current.len - 2 and
                current[owner.len] == 58 and
                current[owner.len + 1.usize()] == 58 and
                (forall index in 0..<owner.len:
                    owner[index] == current[index]
                )
            )
        )
'''
if "moduleSemanticLexicalModuleOwnerPolicy:" not in compact(policy_text):
    raise SystemExit("lexical module-owner policy module is missing")
if compact(function_section(policy_text, "is_lexical")) != compact(expected_policy):
    raise SystemExit("lexical owner predicate changed without updating its specification proof")
if consumer_text.count('include "./lexical_module_owner_policy.elisa"') != 1:
    raise SystemExit("semantic owner predicate must include the proved policy exactly once")
expected_wrapper = '''
def named_type_owner_is_lexical(owner: sview, current: sview) -> bool:
    can Abort.Panic:
        return SemanticLexicalModuleOwnerPolicy::is_lexical(owner, current)
'''
if compact(function_section(consumer_text, "named_type_owner_is_lexical")) != compact(expected_wrapper):
    raise SystemExit("semantic owner predicate no longer delegates to its proved policy")
if semantic_text.count('include "./check_named_type_mismatch.elisa"') != 1:
    raise SystemExit("semantic root must include the lexical visibility consumer exactly once")

for function_name, source in (
    ("binding_module_alias_row", binding_text),
    ("binding_nominal_declaration", binding_text),
    ("named_struct_target", consumer_text),
):
    if "named_type_owner_is_lexical(" not in compact(function_section(source, function_name)):
        raise SystemExit(f"{function_name} must retain the proved lexical visibility predicate")
if "named_type_owner_is_lexical(" not in static_string_text:
    raise SystemExit("static string alias resolution must retain the proved lexical visibility predicate")

positive_names = {
    "implementation_matches_the_lexical_prefix_contract",
    "empty_owner_is_visible_in_every_scope",
    "exact_and_nested_module_owners_are_visible",
    "only_a_two_colon_boundary_extends_a_module_owner",
    "short_current_namespaces_are_rejected_without_indexing_past_them",
}
negative_names = {
    "lookalike_prefix_is_a_lexical_ancestor",
    "one_colon_is_a_module_boundary",
    "empty_owner_is_not_lexically_visible",
}
if 'include "../../src/semantic/lexical_module_owner_policy.elisa"' not in positive_text or \
        'include "./lexical_module_owner_policy.elisa"' not in negative_text:
    raise SystemExit("lexical owner proof fixtures must import the production policy")
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("lexical owner proof declaration inventory changed")
for name in positive_names | negative_names:
    source = positive_text if name in positive_names else negative_text
    signature = compact(function_section(source, name).splitlines()[0])
    if "can[Abort.Panic]" not in signature:
        raise SystemExit(f"lexical owner theorem {name} must declare the policy's panic effect")

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
    raise SystemExit("lexical module-owner proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", POLICY, CONSUMER, SEMANTIC,
    BINDING_RESOLVER, STATIC_STRING, POSITIVE, NEGATIVE, *source_closure,
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
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "lexical module-owner prefix and exact separator visibility",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
