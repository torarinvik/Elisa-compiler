"""Bind field type-argument proofs to the semantic resolver's bracket handling."""
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
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/semantic/index_type_application_policy.elisa"
RESOLVER = ROOT / "src/semantic/resolve_expr_walk.elisa"
POSITIVE = HERE / "index_type_application_policy.elisa"
NEGATIVE = HERE / "index_type_application_policy_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking the proof product")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


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


def between(source: str, start: str, end: str) -> str:
    start_at = source.find(start)
    end_at = source.find(end, start_at + len(start))
    if start_at < 0 or end_at < 0:
        raise SystemExit(f"expected ordered source markers {start!r} and {end!r}")
    return source[start_at:end_at]


policy_text = POLICY.read_text()
resolver_text = RESOLVER.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_policy = '''
def field_name_is_type_argument(field_name: sview) -> bool:
    ensure result == (
        field_name == "cast" or field_name == "ref" or
        field_name == "specialize" or field_name == "call_as"
    )
    return match field_name:
        "cast" | "ref" | "specialize" | "call_as": true
        _: false
'''
if "moduleSemanticIndexTypeApplicationPolicy:" not in compact(policy_text):
    raise SystemExit("index type-application policy module is missing")
if compact(function_section(policy_text, "field_name_is_type_argument")) != compact(expected_policy):
    raise SystemExit("type-argument field classifier changed without updating its proof")
expected_candidate_policy = '''
def candidate_declaration_matches(requested_name_matches: bool, is_function: bool, is_struct: bool, is_enum: bool, is_alias: bool) -> bool:
    ensure result == (requested_name_matches and (is_function or is_struct or is_enum or is_alias))
    return requested_name_matches and (is_function or is_struct or is_enum or is_alias)
'''
if compact(function_section(policy_text, "candidate_declaration_matches")) != compact(expected_candidate_policy):
    raise SystemExit("candidate declaration policy changed without updating its proof")
if resolver_text.count('include "./index_type_application_policy.elisa"') != 1:
    raise SystemExit("semantic resolver must include the proved type-argument policy exactly once")
expected_helper = '''
def index_receiver_is_type_application(object: Ast::Expr) -> bool:
    can Abort.Panic:
        match object:
            Expr.Field(field_object, field_name, field_line):
                return SemanticIndexTypeApplicationPolicy::field_name_is_type_argument(field_name)
            _:
                return false
'''
if compact(function_section(resolver_text, "index_receiver_is_type_application")) != compact(expected_helper):
    raise SystemExit("resolver's syntactic field classifier no longer delegates to the proved policy")

semantic_classifier = compact(function_section(resolver_text, "index_receiver_is_semantic_type_application"))
if "truereturnifindex_receiver_is_type_application(object)" not in semantic_classifier:
    raise SystemExit("semantic type-application classification must retain the proved field-operator case")
identifier_arm = between(semantic_classifier, "Expr.Ident(base_name,base_line):", "Expr.Scope(")
candidate_call = compact('''
SemanticIndexTypeApplicationPolicy::candidate_declaration_matches(
    symbol.name == base_name,
    symbol.kind == SymbolKind.Func,
    symbol.kind == SymbolKind.Struct,
    symbol.kind == SymbolKind.Enum,
    symbol.kind == SymbolKind.Alias
)
''')
if identifier_arm.count(candidate_call) != 2:
    raise SystemExit("indexed and canonical identifier scans must share the proved declaration-kind predicate")
if compact("if table.symbol_name_index_valid and table.symbol_name_indexed_rows == table.symbols.count and table.symbol_name_next.count == table.symbols.count:") not in identifier_arm or \
        compact("row <- table.symbol_name_next[row.usize()]") not in identifier_arm or \
        compact("else: for symbol in table.symbols:") not in identifier_arm:
    raise SystemExit("candidate predicate must remain connected to both collision-chain and canonical scans")
walk = compact(function_section(resolver_text, "walk_expression_inner"))
index_arm = between(walk, "Expr.Index(object,index,line):", "Expr.Binary(left,operator,right,line):")
index_n_arm = between(walk, "Expr.IndexN(object,arguments,line):", "Expr.SetLit(elements,line):")
common_index_fragments = (
    "table<-walk_expression(object,table,bound,bound_mutability,bound_ids)canGlobal{Read,Write}",
    "table<-check_non_generic_specialization(object,line.line,table,bound)",
)
for fragment in common_index_fragments:
    if fragment not in index_arm or fragment not in index_n_arm:
        raise SystemExit("both index forms must resolve their receiver and retain specialization diagnostics")
if "table<-walk_expression(index,table,bound,bound_mutability,bound_ids)canGlobal{Read,Write}ifnotindex_receiver_is_semantic_type_application(object,table,bound)" not in index_arm:
    raise SystemExit("single-index value arguments must be suppressed for semantic type applications")
for fragment in (
    "forargumentinarguments|table|->table:",
    "table<-walk_expression(argument,table,bound,bound_mutability,bound_ids)canGlobal{Read,Write}ifnotindex_receiver_is_semantic_type_application(object,table,bound)",
):
    if fragment not in index_n_arm:
        raise SystemExit("multi-index type arguments must be suppressed from value resolution")

positive_names = {
    "field_operator_name_set_is_exact",
    "all_four_type_argument_operators_are_recognized",
    "ordinary_value_index_fields_are_not_type_argument_operators",
    "candidate_declaration_classifier_is_exact",
    "each_supported_declaration_kind_can_supply_type_arguments",
    "wrong_name_and_ineligible_declaration_kinds_are_rejected",
}
negative_names = {
    "ordinary_index_is_a_type_argument_operator",
    "specialize_is_a_value_index_operator",
    "constant_declaration_can_supply_type_arguments",
    "differently_named_function_can_supply_type_arguments",
}
if 'include "../../src/semantic/index_type_application_policy.elisa"' not in positive_text or \
        'include "./index_type_application_policy.elisa"' not in negative_text:
    raise SystemExit("type-application proofs must include the production classifier")
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("type-application proof declaration inventory changed")

positive_claims = {
    "field_operator_name_set_is_exact": "SemanticIndexTypeApplicationPolicy::field_name_is_type_argument(field_name)",
    "all_four_type_argument_operators_are_recognized": 'SemanticIndexTypeApplicationPolicy::field_name_is_type_argument("cast")andSemanticIndexTypeApplicationPolicy::field_name_is_type_argument("ref")andSemanticIndexTypeApplicationPolicy::field_name_is_type_argument("specialize")andSemanticIndexTypeApplicationPolicy::field_name_is_type_argument("call_as")',
    "ordinary_value_index_fields_are_not_type_argument_operators": 'notSemanticIndexTypeApplicationPolicy::field_name_is_type_argument("index")andnotSemanticIndexTypeApplicationPolicy::field_name_is_type_argument("length")andnotSemanticIndexTypeApplicationPolicy::field_name_is_type_argument("items")',
    "candidate_declaration_classifier_is_exact": "SemanticIndexTypeApplicationPolicy::candidate_declaration_matches(name_matches,is_function,is_struct,is_enum,is_alias)==(name_matchesand(is_functionoris_structoris_enumoris_alias))",
    "each_supported_declaration_kind_can_supply_type_arguments": "SemanticIndexTypeApplicationPolicy::candidate_declaration_matches(true,true,false,false,false)andSemanticIndexTypeApplicationPolicy::candidate_declaration_matches(true,false,true,false,false)andSemanticIndexTypeApplicationPolicy::candidate_declaration_matches(true,false,false,true,false)andSemanticIndexTypeApplicationPolicy::candidate_declaration_matches(true,false,false,false,true)",
    "wrong_name_and_ineligible_declaration_kinds_are_rejected": "notSemanticIndexTypeApplicationPolicy::candidate_declaration_matches(false,true,false,false,false)andnotSemanticIndexTypeApplicationPolicy::candidate_declaration_matches(true,false,false,false,false)",
}
for name, claim in positive_claims.items():
    section = compact(function_section(positive_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"positive theorem {name} no longer establishes its source-bound claim")

negative_claims = {
    "ordinary_index_is_a_type_argument_operator": 'SemanticIndexTypeApplicationPolicy::field_name_is_type_argument("index")',
    "specialize_is_a_value_index_operator": 'notSemanticIndexTypeApplicationPolicy::field_name_is_type_argument("specialize")',
    "constant_declaration_can_supply_type_arguments": "SemanticIndexTypeApplicationPolicy::candidate_declaration_matches(true,false,false,false,false)",
    "differently_named_function_can_supply_type_arguments": "SemanticIndexTypeApplicationPolicy::candidate_declaration_matches(false,true,false,false,false)",
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
    raise SystemExit("type-application policy proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", POLICY, RESOLVER, POSITIVE, NEGATIVE,
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
    "scope": "type-argument field operator classification and resolver suppression",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
