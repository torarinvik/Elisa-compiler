"""Bind path-segment proofs to the semantic collector used by qualified type checks."""
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
POLICY = ROOT / "src/semantic/type_path_collect_policy.elisa"
CONSUMER = ROOT / "src/semantic/check_type_path_separator.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
RESOLVER = ROOT / "src/semantic/resolve_expr_walk.elisa"
POSITIVE = HERE / "type_path_collect_policy.elisa"
NEGATIVE = HERE / "type_path_collect_policy_rejected.elisa"

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
resolver_text = RESOLVER.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_collect = '''
def collect(expression: Ast::Expr, names: mutable darray[sview]&, dotted: mutable darray[bool]&) -> bool:
    can Memory.Allocate, Abort.Panic:
        match expression:
            Ast::Expr.Ident(ident_name, ident_pos):
                names.push(ident_name)
                return true
            Ast::Expr.Field(field_object, field_name, field_pos):
                return false if not collect(field_object, names, dotted)
                names.push(field_name)
                dotted.push(true)
                return true
            Ast::Expr.Scope(scope_base, scope_name, scope_pos):
                return false if not collect(scope_base, names, dotted)
                names.push(scope_name)
                dotted.push(false)
                return true
            _:
                return false
'''
if "moduleSemanticTypePathCollectPolicy:" not in compact(policy_text):
    raise SystemExit("type-path collection policy module is missing")
if compact(function_section(policy_text, "collect")) != compact(expected_collect):
    raise SystemExit("type-path segment collector changed without updating its proof")
if consumer_text.count('include "./type_path_collect_policy.elisa"') != 1:
    raise SystemExit("semantic type-path consumer must include the proved collector exactly once")
expected_wrapper = '''
def type_path_collect(expression: Ast::Expr, names: mutable darray[sview]&, dotted: mutable darray[bool]&) -> bool:
    can Memory.Allocate, Abort.Panic:
        return SemanticTypePathCollectPolicy::collect(expression, names, dotted)
'''
if compact(function_section(consumer_text, "type_path_collect")) != compact(expected_wrapper):
    raise SystemExit("semantic type-path helper no longer delegates to the proved collector")
if semantic_text.count('include "./check_type_path_separator.elisa"') != 1:
    raise SystemExit("semantic root must include the type-path consumer exactly once")

semantic_classifier = compact(function_section(resolver_text, "index_receiver_is_semantic_type_application"))
scope_arm = semantic_classifier[semantic_classifier.find("Expr.Scope("):]
qualified_fragments = (
    "false return if not type_path_collect(object, names, dotted) or names.count == 0",
    "false return if any was_dotted in dotted where was_dotted",
    "return false if any bound_name in bound where bound_name == names[0]",
    "row: u32 = binding_nominal_declaration(object, table.current_module, table)",
    "return row != SYMBOL_INDEX_ROW_NONE",
)
positions = [scope_arm.find(compact(fragment)) for fragment in qualified_fragments]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("qualified applications must collect a pure path, reject dotted/shadowed heads, then require a nominal declaration")

positive_names = {
    "identifier_path_has_one_name_and_no_separators",
    "field_path_marks_the_value_separator",
    "scope_path_marks_the_namespace_separator",
    "mixed_path_preserves_segment_and_separator_order",
    "unsupported_leaf_preserves_existing_output",
}
negative_names = {
    "field_separator_is_a_namespace_separator",
    "scope_separator_is_a_value_separator",
}
if 'include "../../src/semantic/type_path_collect_policy.elisa"' not in positive_text or \
        'include "./type_path_collect_policy.elisa"' not in negative_text:
    raise SystemExit("type-path proof fixtures must import the production collector")
if 'include "../../src/parser/parser_tokens.elisa"' not in positive_text or \
        'include "../../src/parser/ast_nodes.elisa"' not in positive_text:
    raise SystemExit("AST path proofs must import the production AST node definitions")
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("type-path proof declaration inventory changed")
for name in positive_names | negative_names:
    signature = compact(function_section(positive_text if name in positive_names else negative_text, name).splitlines()[0])
    if "can[Memory.Allocate,Abort.Panic]" not in signature:
        raise SystemExit(f"AST path theorem {name} must declare the collector's allocation and panic effects")

positive_claims = {
    "identifier_path_has_one_name_and_no_separators": 'names.count==1andnames[0]=="Root"anddotted.count==0',
    "field_path_marks_the_value_separator": 'names.count==2andnames[0]=="Pack"andnames[1]=="Item"anddotted.count==1anddotted[0]',
    "scope_path_marks_the_namespace_separator": 'names.count==2andnames[0]=="Pack"andnames[1]=="Item"anddotted.count==1andnotdotted[0]',
    "mixed_path_preserves_segment_and_separator_order": 'names.count==4andnames[0]=="Root"andnames[1]=="Inner"andnames[2]=="Value"andnames[3]=="Type"anddotted.count==3andnotdotted[0]anddotted[1]andnotdotted[2]',
    "unsupported_leaf_preserves_existing_output": 'names.count==1andnames[0]=="Existing"anddotted.count==1anddotted[0]',
}
for name, claim in positive_claims.items():
    section = compact(function_section(positive_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"positive theorem {name} no longer establishes its source-bound claim")

negative_claims = {
    "field_separator_is_a_namespace_separator": "notdotted[0]",
    "scope_separator_is_a_value_separator": "dotted[0]",
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
    raise SystemExit("type-path collection proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", POLICY, CONSUMER, SEMANTIC, RESOLVER,
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
    "scope": "AST module/type path collection and separator classification",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
