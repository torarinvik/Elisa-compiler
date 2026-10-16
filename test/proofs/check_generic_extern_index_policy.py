"""Bind generic-extern name proofs to the resolver's annotation-backed registry."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SEMANTIC_DIR = ROOT / "src/semantic"
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/semantic/generic_extern_index_policy.elisa"
RESOLVER = ROOT / "src/semantic/resolve_expr_walk.elisa"
SEMANTIC_API = ROOT / "src/semantic/semantic_api.elisa"
POSITIVE = HERE / "generic_extern_index_policy.elisa"
NEGATIVE = HERE / "generic_extern_index_policy_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking the proof product")
ARGS = parser.parse_args()

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
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


policy_text = POLICY.read_text()
resolver_text = RESOLVER.read_text()
semantic_api_text = SEMANTIC_API.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_scan = '''
    ghost def contains_from(names: darray[sview]&, target_name: sview, index: usize) -> bool:
    requires index <= names.count
    decreases names.count - index
    return false if index == names.count
    return true if names[index] == target_name
    return contains_from(names, target_name, index + 1)
'''
expected_contains = '''
def contains(names: darray[sview]&, target_name: sview) -> bool:
    ensure result == contains_from(names, target_name, 0)
    index: mutable usize = 0
    while index < names.count |index, names, target_name|:
        decreases names.count - index
        invariant index <= names.count
        invariant contains_from(names, target_name, index) == contains_from(names, target_name, 0)
        assert contains_from(names, target_name, index) == (
            names[index] == target_name or contains_from(names, target_name, index + 1.usize())
        )
        if names[index] == target_name:
            assert contains_from(names, target_name, index)
            return true
        assert contains_from(names, target_name, index) == contains_from(names, target_name, index + 1.usize())
        index <- index + 1.usize()
        assert contains_from(names, target_name, index) == contains_from(names, target_name, 0)
    assert index == names.count
    assert contains_from(names, target_name, index) == false
    assert contains_from(names, target_name, 0) == false
    return false
'''
if "moduleSemanticGenericExternIndexPolicy:" not in compact(policy_text):
    raise SystemExit("generic-extern index policy module is missing")
if compact(function_section(policy_text, "contains_from")) != compact(expected_scan):
    raise SystemExit("recursive generic-extern membership specification changed")
if compact(function_section(policy_text, "contains")) != compact(expected_contains):
    raise SystemExit("production generic-extern scan no longer refines its recursive specification")
if resolver_text.count('include "./generic_extern_index_policy.elisa"') != 1:
    raise SystemExit("semantic resolver must include the proved generic-extern scan exactly once")
expected_helper = '''
def index_receiver_is_generic_extern(object: Ast::Expr, table: SymbolTable&) -> bool:
    can Abort.Panic:
        match object:
            Expr.Ident(extern_name, extern_line):
                return SemanticGenericExternIndexPolicy::contains(table.generic_extern_names, extern_name)
            _:
                pass
        return false
'''
if compact(function_section(resolver_text, "index_receiver_is_generic_extern")) != compact(expected_helper):
    raise SystemExit("resolver no longer delegates generic-extern lookup to its proved scan")

semantic_classifier = compact(function_section(resolver_text, "index_receiver_is_semantic_type_application"))
ordered_fragments = (
    "false return if any bound_name in bound where bound_name == base_name",
    "true return if index_receiver_is_generic_extern(object, table)",
    "if table.symbol_name_index_valid and table.symbol_name_indexed_rows == table.symbols.count and table.symbol_name_next.count == table.symbols.count:",
    "for symbol in table.symbols:",
)
positions = [semantic_classifier.find(compact(fragment)) for fragment in ordered_fragments]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("generic externs must be checked after local shadowing and before symbol lookup fallback")

annotation_append = 'table.generic_extern_names <- table.generic_extern_names.push(annotation.name) if annotation.owner == "__extern_generic_name"'
api_sites = [
    function_section(semantic_api_text, "check_full_into_pipeline"),
    function_section(semantic_api_text, "unresolved_table"),
    function_section(semantic_api_text, "unresolved_references"),
]
if any(compact(site).count(compact(annotation_append)) != 1 for site in api_sites):
    raise SystemExit("all semantic entry paths must register the exact generic-extern annotation names")
annotation_append_compact = compact(annotation_append)
all_semantic_sources = [path.read_text() for path in SEMANTIC_DIR.rglob("*.elisa")]
if sum(compact(source).count(annotation_append_compact) for source in all_semantic_sources) != 3:
    raise SystemExit("unexpected generic-extern registry population path")

positive_names = {
    "production_scan_matches_recursive_specification",
    "empty_registry_has_no_generic_extern",
    "generic_extern_at_the_last_position_is_found",
    "absent_name_is_not_a_generic_extern",
    "duplicate_registry_rows_preserve_membership",
}
negative_names = {
    "false_claim_present_generic_extern_is_absent",
    "false_claim_absent_name_is_registered",
}
if 'include "../../src/semantic/generic_extern_index_policy.elisa"' not in positive_text or \
        'include "./generic_extern_index_policy.elisa"' not in negative_text:
    raise SystemExit("generic-extern proof fixtures must import the production scan")
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("generic-extern proof declaration inventory changed")

positive_claims = {
    "production_scan_matches_recursive_specification": "SemanticGenericExternIndexPolicy::contains(names, target_name)==SemanticGenericExternIndexPolicy::contains_from(names, target_name, 0)",
    "empty_registry_has_no_generic_extern": 'notSemanticGenericExternIndexPolicy::contains(names,"va_arg")',
    "generic_extern_at_the_last_position_is_found": 'SemanticGenericExternIndexPolicy::contains(names,"va_arg")',
    "absent_name_is_not_a_generic_extern": 'notSemanticGenericExternIndexPolicy::contains(names,"va_arg")',
    "duplicate_registry_rows_preserve_membership": 'SemanticGenericExternIndexPolicy::contains(names,"va_arg")',
}
for name, claim in positive_claims.items():
    section = compact(function_section(positive_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"positive theorem {name} no longer establishes its source-bound claim")

negative_claims = {
    "false_claim_present_generic_extern_is_absent": 'notSemanticGenericExternIndexPolicy::contains(names,"va_arg")',
    "false_claim_absent_name_is_registered": 'SemanticGenericExternIndexPolicy::contains(names,"va_arg")',
}
for name, claim in negative_claims.items():
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
    raise SystemExit("generic-extern index proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", POLICY, RESOLVER, SEMANTIC_API,
    *sorted(SEMANTIC_DIR.rglob("*.elisa")),
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
    "scope": "generic-extern name registry membership and type-application classification",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
