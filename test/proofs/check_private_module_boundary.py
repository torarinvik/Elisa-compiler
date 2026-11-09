"""Bind private-module visibility proofs to the production semantic helper."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from private_boundary_source_sections import collect_private_source_sections
from private_boundary_import_checks import check_private_import_resolution
from private_boundary_fixture_checks import check_private_visibility_fixtures
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
TABLE_SETUP = ROOT / "src/semantic/semantic_api/table_setup.elisa"
DIAGNOSTIC_OUTPUT = ROOT / "src/semantic/semantic_api/diagnostic_output.elisa"
IMPORT_VISIBILITY = ROOT / "src/semantic/semantic_import_visibility.elisa"
RESOLVE_SCOPE = ROOT / "src/semantic/resolve_scope.elisa"
RESOLVE_EXPR_WALK = ROOT / "src/semantic/resolve_expr_walk.elisa"
RESOLVE_EXPR_WALK_CONTEXT = ROOT / "src/semantic/resolve_expr_walk_context.elisa"
RESOLVE_TYPES = ROOT / "src/semantic/resolve_types.elisa"
RESOLVE_ENUM_OWNERS = ROOT / "src/semantic/resolve_types_enum_owners.elisa"
RESOLVE_BINDING_CAPABILITIES = ROOT / "src/semantic/resolve_binding_capabilities.elisa"
CHECK_NAMED_TYPE_MISMATCH = ROOT / "src/semantic/check_named_type_mismatch.elisa"
CHECK_CONSTRUCT_FIELD_TYPE = ROOT / "src/semantic/check_construct_field_type.elisa"
CHECK_READONLY_REF = ROOT / "src/semantic/check_readonly_ref.elisa"
CHECK_PRIVATE_FIELDS_TYPES = ROOT / "src/semantic/check_private_fields_types.elisa"
PARSER = ROOT / "src/parser/parser_decl_module.elisa"
PARSER_FUNCTION = ROOT / "src/parser/parser_types_function.elisa"
SYMBOLS = ROOT / "src/semantic/symbols.elisa"
SYMBOLS_HASH_INDEX = ROOT / "src/semantic/symbols_hash_index.elisa"
POSITIVE = HERE / "private_module_boundary.elisa"
NEGATIVE = HERE / "private_module_boundary_rejected.elisa"
CALL_SHAPES = ROOT / "test/repro/private_call_overload_visibility_shapes.elisa"
CALL_SHAPES_SMOKE = ROOT / "test/parity/private_call_overload_visibility_shapes_smoke.sh"
ROOT_OVERLOADS = ROOT / "test/repro/private_call_root_overload_hidden_import.elisa"
ROOT_OVERLOADS_SMOKE = ROOT / "test/parity/private_call_root_overload_hidden_import_smoke.sh"
UNKNOWN_STATIC_IMPORT = ROOT / "test/repro/private_call_static_unknown_import.elisa"
UNKNOWN_STATIC_IMPORT_SMOKE = ROOT / "test/parity/private_call_static_unknown_import_smoke.sh"
STATIC_TRUE_IMPORT_CONTROL = ROOT / "test/repro/private_call_static_true_import_control.elisa"
STATIC_TRUE_IMPORT_CONTROL_SMOKE = ROOT / "test/parity/private_call_static_true_import_control_smoke.sh"
INACTIVE_STATIC_STATEMENT = ROOT / "test/repro/private_call_in_inactive_static_statement.elisa"
INACTIVE_STATIC_STATEMENT_SMOKE = ROOT / "test/parity/private_call_in_inactive_static_statement_smoke.sh"
NESTED_INACTIVE_STATIC_STATEMENT = ROOT / "test/repro/private_call_in_nested_inactive_static_statement.elisa"
NESTED_INACTIVE_STATIC_STATEMENT_SMOKE = ROOT / "test/parity/private_call_in_nested_inactive_static_statement_smoke.sh"
INACTIVE_STATIC_DECLARATION = ROOT / "test/repro/private_call_in_inactive_static_declaration.elisa"
INACTIVE_STATIC_DECLARATION_SMOKE = ROOT / "test/parity/private_call_in_inactive_static_declaration_smoke.sh"
INACTIVE_PUBLIC_OVERLOAD_RANK = ROOT / "test/repro/private_call_inactive_public_overload_rank.elisa"
INACTIVE_PUBLIC_OVERLOAD_RANK_SMOKE = ROOT / "test/parity/private_call_inactive_public_overload_rank_smoke.sh"
UNPROVEN_PUBLIC_SIBLINGS = ROOT / "test/repro/private_call_unproven_public_siblings.elisa"
UNPROVEN_PUBLIC_SIBLINGS_SMOKE = ROOT / "test/parity/private_call_unproven_public_siblings_smoke.sh"
SAME_LINE_IMPORT_PAIRING = ROOT / "test/repro/private_call_same_line_import_pairing.elisa"
SAME_LINE_IMPORT_PAIRING_SMOKE = ROOT / "test/parity/private_call_same_line_import_pairing_smoke.sh"
MODULE_ALIAS_PRIVATE_CALL = ROOT / "test/repro/private_call_module_alias.elisa"
MODULE_ALIAS_PRIVATE_CALL_SMOKE = ROOT / "test/parity/private_call_module_alias_smoke.sh"
MODULE_ALIAS_PRECEDENCE = ROOT / "test/repro/private_call_module_alias_branch_precedence.elisa"
MODULE_ALIAS_PRECEDENCE_SMOKE = ROOT / "test/parity/private_call_module_alias_branch_precedence_smoke.sh"
MODULE_ALIAS_CHAIN = ROOT / "test/repro/private_call_module_alias_chain.elisa"
MODULE_ALIAS_CHAIN_SMOKE = ROOT / "test/parity/private_call_module_alias_chain_smoke.sh"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking the proof product")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in expand_return_if_blocks(source).splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}(?:\[[^\n]*\])?\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*(?:\[[^\n]*\])?\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


source_text = SOURCE.read_text()
consumer_text = CONSUMER.read_text() + CONSUMER.with_name("check_private_import_visibility.elisa").read_text() + CONSUMER.with_name("check_private_member_walk.elisa").read_text()
semantic_text = SEMANTIC.read_text()
table_setup_text = TABLE_SETUP.read_text()
diagnostic_output_text = DIAGNOSTIC_OUTPUT.read_text()
import_visibility_text = IMPORT_VISIBILITY.read_text() + IMPORT_VISIBILITY.with_name("semantic_import_candidate_visibility.elisa").read_text()
resolve_scope_text = RESOLVE_SCOPE.read_text() + RESOLVE_SCOPE.with_name("resolve_reference_identity.elisa").read_text()
resolve_expr_walk_text = RESOLVE_EXPR_WALK.read_text()
resolve_expr_walk_context_text = RESOLVE_EXPR_WALK_CONTEXT.read_text()
resolve_types_text = RESOLVE_TYPES.read_text()
resolve_enum_owners_text = RESOLVE_ENUM_OWNERS.read_text()
resolve_binding_capabilities_text = RESOLVE_BINDING_CAPABILITIES.read_text()
check_named_type_mismatch_text = CHECK_NAMED_TYPE_MISMATCH.read_text()
check_construct_field_type_text = CHECK_CONSTRUCT_FIELD_TYPE.read_text()
check_readonly_ref_text = CHECK_READONLY_REF.read_text()
check_private_fields_types_text = CHECK_PRIVATE_FIELDS_TYPES.read_text()
parser_text = PARSER.read_text() + PARSER.with_name("parser_decl_imports.elisa").read_text()
parser_using_alias = compact(function_section(parser_text, "using_alias"))
parser_consume_using_target = compact(function_section(parser_text, "consume_using_target"))
parser_const_text = (ROOT / "src/parser/parser_types_aggregate.elisa").read_text()
parser_function_text = PARSER_FUNCTION.read_text()
symbols_text = SYMBOLS.read_text()
symbols_hash_index_text = SYMBOLS_HASH_INDEX.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
call_shapes_text = CALL_SHAPES.read_text()
call_shapes_smoke_text = CALL_SHAPES_SMOKE.read_text()
root_overloads_text = ROOT_OVERLOADS.read_text()
root_overloads_smoke_text = ROOT_OVERLOADS_SMOKE.read_text()
unknown_static_import_text = UNKNOWN_STATIC_IMPORT.read_text()
facts = collect_private_source_sections(
    MODULE_ALIAS_PRECEDENCE=MODULE_ALIAS_PRECEDENCE,
    UNKNOWN_STATIC_IMPORT_SMOKE=UNKNOWN_STATIC_IMPORT_SMOKE,
    check_construct_field_type_text=check_construct_field_type_text,
    check_named_type_mismatch_text=check_named_type_mismatch_text,
    check_private_fields_types_text=check_private_fields_types_text,
    check_readonly_ref_text=check_readonly_ref_text,
    compact=compact,
    consumer_text=consumer_text,
    diagnostic_output_text=diagnostic_output_text,
    function_section=function_section,
    import_visibility_text=import_visibility_text,
    parser_text=parser_text,
    resolve_binding_capabilities_text=resolve_binding_capabilities_text,
    resolve_enum_owners_text=resolve_enum_owners_text,
    resolve_expr_walk_context_text=resolve_expr_walk_context_text,
    resolve_expr_walk_text=resolve_expr_walk_text,
    resolve_scope_text=resolve_scope_text,
    semantic_text=semantic_text,
    source_text=source_text,
    symbols_hash_index_text=symbols_hash_index_text,
    symbols_text=symbols_text,
    table_setup_text=table_setup_text,
)
check_private_import_resolution(
    facts=facts,
    compact=compact,
    function_section=function_section,
    parser_const_text=parser_const_text,
    parser_consume_using_target=parser_consume_using_target,
    parser_function_text=parser_function_text,
    parser_text=parser_text,
    parser_using_alias=parser_using_alias,
)
check_private_visibility_fixtures(
    facts=facts,
    INACTIVE_PUBLIC_OVERLOAD_RANK=INACTIVE_PUBLIC_OVERLOAD_RANK,
    INACTIVE_PUBLIC_OVERLOAD_RANK_SMOKE=INACTIVE_PUBLIC_OVERLOAD_RANK_SMOKE,
    INACTIVE_STATIC_DECLARATION=INACTIVE_STATIC_DECLARATION,
    INACTIVE_STATIC_DECLARATION_SMOKE=INACTIVE_STATIC_DECLARATION_SMOKE,
    INACTIVE_STATIC_STATEMENT=INACTIVE_STATIC_STATEMENT,
    INACTIVE_STATIC_STATEMENT_SMOKE=INACTIVE_STATIC_STATEMENT_SMOKE,
    MODULE_ALIAS_CHAIN=MODULE_ALIAS_CHAIN,
    MODULE_ALIAS_CHAIN_SMOKE=MODULE_ALIAS_CHAIN_SMOKE,
    MODULE_ALIAS_PRECEDENCE=MODULE_ALIAS_PRECEDENCE,
    MODULE_ALIAS_PRECEDENCE_SMOKE=MODULE_ALIAS_PRECEDENCE_SMOKE,
    MODULE_ALIAS_PRIVATE_CALL=MODULE_ALIAS_PRIVATE_CALL,
    MODULE_ALIAS_PRIVATE_CALL_SMOKE=MODULE_ALIAS_PRIVATE_CALL_SMOKE,
    NESTED_INACTIVE_STATIC_STATEMENT=NESTED_INACTIVE_STATIC_STATEMENT,
    NESTED_INACTIVE_STATIC_STATEMENT_SMOKE=NESTED_INACTIVE_STATIC_STATEMENT_SMOKE,
    SAME_LINE_IMPORT_PAIRING=SAME_LINE_IMPORT_PAIRING,
    SAME_LINE_IMPORT_PAIRING_SMOKE=SAME_LINE_IMPORT_PAIRING_SMOKE,
    STATIC_TRUE_IMPORT_CONTROL=STATIC_TRUE_IMPORT_CONTROL,
    STATIC_TRUE_IMPORT_CONTROL_SMOKE=STATIC_TRUE_IMPORT_CONTROL_SMOKE,
    UNPROVEN_PUBLIC_SIBLINGS=UNPROVEN_PUBLIC_SIBLINGS,
    UNPROVEN_PUBLIC_SIBLINGS_SMOKE=UNPROVEN_PUBLIC_SIBLINGS_SMOKE,
    call_shapes_smoke_text=call_shapes_smoke_text,
    call_shapes_text=call_shapes_text,
    compact=compact,
    consumer_text=consumer_text,
    function_section=function_section,
    negative_text=negative_text,
    positive_text=positive_text,
    root_overloads_smoke_text=root_overloads_smoke_text,
    root_overloads_text=root_overloads_text,
    unknown_static_import_text=unknown_static_import_text,
)
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
    Path(__file__), HERE / "proof_product_gate.py",
    HERE / "private_boundary_source_sections.py", HERE / "private_boundary_import_checks.py", HERE / "private_boundary_fixture_checks.py", SOURCE, CONSUMER, SEMANTIC,
    POSITIVE, NEGATIVE, UNKNOWN_STATIC_IMPORT, UNKNOWN_STATIC_IMPORT_SMOKE,
    PARSER_FUNCTION,
    INACTIVE_STATIC_STATEMENT, INACTIVE_STATIC_STATEMENT_SMOKE,
    INACTIVE_PUBLIC_OVERLOAD_RANK, INACTIVE_PUBLIC_OVERLOAD_RANK_SMOKE,
    UNPROVEN_PUBLIC_SIBLINGS, UNPROVEN_PUBLIC_SIBLINGS_SMOKE,
    SAME_LINE_IMPORT_PAIRING, SAME_LINE_IMPORT_PAIRING_SMOKE, *source_closure,
    MODULE_ALIAS_PRIVATE_CALL, MODULE_ALIAS_PRIVATE_CALL_SMOKE,
    MODULE_ALIAS_PRECEDENCE, MODULE_ALIAS_PRECEDENCE_SMOKE,
    MODULE_ALIAS_CHAIN, MODULE_ALIAS_CHAIN_SMOKE,
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
