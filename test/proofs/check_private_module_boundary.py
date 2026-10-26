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
consumer_text = CONSUMER.read_text()
semantic_text = SEMANTIC.read_text()
table_setup_text = TABLE_SETUP.read_text()
diagnostic_output_text = DIAGNOSTIC_OUTPUT.read_text()
import_visibility_text = IMPORT_VISIBILITY.read_text()
resolve_scope_text = RESOLVE_SCOPE.read_text()
resolve_expr_walk_text = RESOLVE_EXPR_WALK.read_text()
resolve_expr_walk_context_text = RESOLVE_EXPR_WALK_CONTEXT.read_text()
resolve_types_text = RESOLVE_TYPES.read_text()
resolve_enum_owners_text = RESOLVE_ENUM_OWNERS.read_text()
resolve_binding_capabilities_text = RESOLVE_BINDING_CAPABILITIES.read_text()
check_named_type_mismatch_text = CHECK_NAMED_TYPE_MISMATCH.read_text()
check_construct_field_type_text = CHECK_CONSTRUCT_FIELD_TYPE.read_text()
check_readonly_ref_text = CHECK_READONLY_REF.read_text()
check_private_fields_types_text = CHECK_PRIVATE_FIELDS_TYPES.read_text()
parser_text = PARSER.read_text()
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
unknown_static_import_smoke_text = UNKNOWN_STATIC_IMPORT_SMOKE.read_text()
module_alias_precedence_text = MODULE_ALIAS_PRECEDENCE.read_text()

expected_prefix = '''
def prefix_matches(text: sview, prefix: sview) -> bool:
    ensure result == (
        text.len >= prefix.len and
        (forall index in 0..<text.len:
            index >= prefix.len or text[index] == prefix[index]
        )
    )
    return false if text.len < prefix.len
    while index < prefix.len |index: usize = 0, text, prefix|:
        decreases prefix.len - index
        invariant index <= prefix.len and prefix.len <= text.len
        invariant forall checked in 0..<index: text[checked] == prefix[checked]
        return false if text[index] != prefix[index]
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
        return true if current_module == owner
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
unqualified_owner = compact(function_section(consumer_text, "pma_unqualified_owner"))
unqualified_call_owner = compact(function_section(consumer_text, "pma_unqualified_call_owner"))
private_import_owner = compact(function_section(consumer_text, "pma_unqualified_private_import_owner"))
scope_member = compact(function_section(consumer_text, "pma_report_scope_member"))
if not all(fragment in unqualified_owner for fragment in (
        "pma_has_global_value(table,member)",
        "pma_unqualified_private_import_owner(table,current_module,private_index,annotations,member)",
        "pma_has_public_imported_function_value(table,private_index,annotations,current_module,member,owner)")) or \
        not all(fragment in unqualified_call_owner for fragment in (
        "pma_has_global_non_callable_value(table,member)",
        "pma_unqualified_private_import_owner(table,current_module,private_index,annotations,member)")) or \
        "pma_within_module(current_module,owner)" not in private_import_owner or \
        "pma_within_module(current_module,owner)" not in scope_member:
    raise SystemExit("qualified and unqualified private-member checks must share the proved boundary predicate")

# Parser markers and semantic symbols share declaration-head offsets. Identifier token
# positions are a distinct span and must not be used to recover per-overload visibility.
private_position = compact(function_section(parser_text, "private_member_declaration_position"))
private_record = compact(function_section(parser_text, "record_private_member_if"))
collect_functions = compact(function_section(symbols_text, "collect_range_with_variadics"))
if "head_offset:usize=parser.private_declaration_head_offset()" not in private_position or \
        "returnAst::pos_of_token(token)" not in private_position or \
        "offset:member_position.offset" not in private_record:
    raise SystemExit("private-member annotation must preserve the parser's declaration-head offset")
if "Decl.Func(name,params,return_type,body,effects,decorators,line)" not in collect_functions or \
        "SymbolKind.Func,line.line,required" not in collect_functions or \
        "line.offset,function_pos" not in collect_functions:
    raise SystemExit("function symbols must retain the declaration-head offset from the parsed function position")

# Overload visibility must be tied to the exact private declaration. Calls may skip a
# spelling-only private report only when a visible sibling can win Core's call ranking
# and every exact private candidate is ineligible, incompatible, or outranked under the
# subset this checker can prove; unknown call shapes remain fail-closed.
private_index_build = compact(function_section(consumer_text, "pma_build_index"))
private_symbol_marker = compact(function_section(consumer_text, "pma_symbol_has_private_marker"))
public_call_sibling_rank = compact(function_section(consumer_text, "pma_public_call_sibling_rank"))
named_type_spelling_unique = compact(function_section(consumer_text, "pma_named_type_spelling_is_unique"))
private_candidate_rank = compact(function_section(consumer_text, "pma_private_candidate_excluded_by_public_rank"))
core_arity_filter = compact(function_section(consumer_text, "pma_symbol_core_accepts_receiver_arity"))
private_call_exclusion = compact(function_section(consumer_text, "pma_private_call_overloads_excluded"))
global_value_lookup = compact(function_section(consumer_text, "pma_has_global_value"))
global_non_callable_lookup = compact(function_section(consumer_text, "pma_has_global_non_callable_value"))
bare_owner_lookup = compact(function_section(consumer_text, "pma_unqualified_owner"))
call_owner_lookup = compact(function_section(consumer_text, "pma_unqualified_call_owner"))
private_import_owner_lookup = compact(function_section(consumer_text, "pma_unqualified_private_import_owner"))
public_imported_value = compact(function_section(consumer_text, "pma_has_public_imported_function_value"))
private_import_visibility = compact(function_section(consumer_text, "pma_private_imported_module_member_visible"))
public_import_visibility = compact(function_section(consumer_text, "pma_public_imported_module_member_visible"))
imported_member_visibility = compact(function_section(consumer_text, "pma_imported_module_member_visible"))
candidate_module_visibility = compact(function_section(consumer_text, "pma_unqualified_candidate_module_visible"))
selective_import_status = compact(function_section(consumer_text, "pma_selective_import_target_status"))
selective_import_index = compact(function_section(consumer_text, "pma_build_selective_import_index"))
import_source_hash = compact(function_section(consumer_text, "pma_import_source_hash"))
import_source_contains = compact(function_section(consumer_text, "pma_import_source_contains"))
using_member_registration = compact(function_section(consumer_text, "pma_selective_annotation_is_using_member"))
import_scope_visibility = compact(function_section(consumer_text, "pma_import_scope_visible"))
static_if_condition_value = compact(function_section(consumer_text, "pma_static_if_condition_value"))
static_if_char_value = compact(function_section(consumer_text, "pma_static_if_char_value"))
static_if_named_constant_value = compact(function_section(consumer_text, "pma_static_if_named_constant_value"))
static_if_const_branch_selection = compact(function_section(consumer_text, "pma_static_if_const_branch_selection"))
static_if_function_branch_selection = compact(function_section(consumer_text, "pma_static_if_function_branch_selection"))
static_if_qualified_module_matches = compact(function_section(consumer_text, "pma_static_if_qualified_module_matches"))
static_if_row_selection = compact(function_section(consumer_text, "pma_static_if_row_selection"))
static_if_row_for_position = compact(function_section(consumer_text, "pma_static_if_row_for_position"))
import_branch_selection = compact(function_section(consumer_text, "pma_import_branch_selection"))
using_alias_for_using = compact(function_section(consumer_text, "pma_using_alias_for_using_row"))
import_annotation_branch_selection = compact(function_section(consumer_text, "pma_import_annotation_branch_selection"))
build_import_views = compact(function_section(table_setup_text, "semantic_build_import_annotation_views"))
synthetic_import_marker = compact(function_section(import_visibility_text, "semantic_is_synthetic_unknown_import_marker"))
wildcard_import_builder = compact(function_section(symbols_hash_index_text, "index_wildcard_imports"))
binding_import_builder = compact(function_section(resolve_binding_capabilities_text, "binding_import_metadata"))
alias_member_builder = compact(function_section(symbols_text, "register_using_alias_members"))
prepare_symbol_table = compact(function_section(table_setup_text, "prepare_symbol_table"))
unresolved_table_setup = compact(function_section(diagnostic_output_text, "unresolved_table"))
unresolved_references_setup = compact(function_section(diagnostic_output_text, "unresolved_references"))
possible_import_name_visible = compact(function_section(import_visibility_text, "semantic_possible_import_name_visible"))
possible_import_member_visible = compact(function_section(import_visibility_text, "semantic_possible_import_member_visible"))
possible_import_alias = compact(function_section(import_visibility_text, "semantic_possible_import_module_alias"))
possible_import_module_visible = compact(function_section(import_visibility_text, "semantic_possible_import_module_visible"))
possible_import_module_member = compact(function_section(import_visibility_text, "semantic_possible_import_module_member_visible"))
possible_import_module_path = compact(function_section(import_visibility_text, "semantic_import_module_path_matches"))
possible_import_module_path_suffix = compact(function_section(import_visibility_text, "semantic_import_module_path_with_suffix_matches"))
possible_import_alias_branch = compact(function_section(import_visibility_text, "semantic_import_alias_is_static_branch"))
possible_import_alias_branch_marker_at = compact(function_section(import_visibility_text, "semantic_possible_import_alias_branch_marker_at"))
possible_import_alias_branch_marker_count = compact(function_section(import_visibility_text, "semantic_possible_import_alias_branch_marker_count"))
possible_import_alias_branch_stack = compact(function_section(import_visibility_text, "semantic_possible_import_alias_branch_stack_relation"))
possible_import_alias_definite = compact(function_section(import_visibility_text, "semantic_possible_import_alias_is_definite"))
import_alias_pair_target = compact(function_section(import_visibility_text, "semantic_import_alias_pair_target"))
import_alias_global_winner = compact(function_section(import_visibility_text, "semantic_import_alias_is_global_winner"))
import_alias_target_global_winner = compact(function_section(import_visibility_text, "semantic_import_alias_target_is_global_winner"))
import_alias_target_canonical_owner = compact(function_section(import_visibility_text, "semantic_import_alias_target_canonical_owner"))
import_using_row_alias_pair = compact(function_section(import_visibility_text, "semantic_import_using_row_has_alias_pair"))
possible_import_alias_target_row_can_win = compact(function_section(import_visibility_text, "semantic_possible_import_alias_target_row_can_win"))
possible_import_alias_order = compact(function_section(import_visibility_text, "semantic_possible_import_alias_precedes"))
possible_import_alias_position = compact(function_section(import_visibility_text, "semantic_possible_import_alias_precedes_position"))
possible_import_alias_head_target = compact(function_section(import_visibility_text, "semantic_possible_import_alias_head_target"))
possible_import_alias_target_prefix = compact(function_section(import_visibility_text, "semantic_possible_import_alias_target_prefix"))
possible_import_alias_target_matches = compact(function_section(import_visibility_text, "semantic_possible_import_alias_target_matches"))
possible_import_alias_target_head_status = compact(function_section(import_visibility_text, "semantic_possible_import_alias_target_head_status"))
possible_import_alias_target_alias_matches = compact(function_section(import_visibility_text, "semantic_possible_import_alias_target_alias_matches"))
possible_import_alias_precedence = compact(function_section(import_visibility_text, "semantic_possible_import_alias_can_win"))
possible_import_alias_dependency = compact(function_section(import_visibility_text, "semantic_possible_import_alias_dependency_exists"))
possible_import_alias_module_path = compact(function_section(import_visibility_text, "semantic_possible_import_alias_module_path_matches"))
possible_import_member_owner = compact(function_section(import_visibility_text, "semantic_possible_import_member_owner_visible"))
possible_import_module_path_alias_member = compact(function_section(import_visibility_text, "semantic_possible_import_module_path_alias_member_visible"))
possible_import_module_path_member = compact(function_section(import_visibility_text, "semantic_possible_import_module_path_member_visible"))
possible_import_module_path_candidate = compact(function_section(import_visibility_text, "semantic_possible_import_module_path_candidate_matches"))
possible_import_type_path_candidate = compact(function_section(import_visibility_text, "semantic_possible_import_type_path_candidate_matches"))
possible_import_module_symbol_alias = compact(function_section(import_visibility_text, "semantic_possible_import_module_symbol_is_using_alias"))
possible_import_module_path_alias_module = compact(function_section(import_visibility_text, "semantic_possible_import_module_path_alias_module_visible"))
possible_import_module_path_module_candidate = compact(function_section(import_visibility_text, "semantic_possible_import_module_path_module_candidate_matches"))
possible_import_import_row_member = compact(function_section(import_visibility_text, "semantic_possible_import_import_row_member_visible"))
possible_import_type_selection = compact(function_section(import_visibility_text, "semantic_possible_import_may_select_type"))
resolver_name_known = compact(function_section(resolve_scope_text, "name_known"))
resolver_module_alias = compact(function_section(resolve_scope_text, "name_is_module"))
resolver_name_classification = compact(function_section(resolve_scope_text, "resolver_name_classification"))
resolver_wildcard_uncertainty = compact(function_section(resolve_expr_walk_text, "rew_ambiguous_wildcard_type_name"))
resolver_qualified_alias_uncertainty = compact(function_section(resolve_expr_walk_context_text, "walk_expression_inner_with_context"))
binding_nominal_lookup = compact(function_section(resolve_binding_capabilities_text, "binding_nominal_declaration"))
named_struct_lookup = compact(function_section(check_named_type_mismatch_text, "named_struct_target"))
enum_owner_lookup = compact(function_section(resolve_enum_owners_text, "operator_named_type_symbol"))
construct_call_lookup = compact(function_section(check_construct_field_type_text, "darray_call_declaration_id"))
readonly_callee_lookup = compact(function_section(check_readonly_ref_text, "readonly_resolve_callee_owner"))
private_field_owner_lookup = compact(function_section(check_private_fields_types_text, "pft_owner_matches"))
using_alias_target = compact(function_section(consumer_text, "pma_using_alias_target"))
alias_chain_match = compact(function_section(consumer_text, "pma_alias_chain_ends_at"))
alias_chain_prefix_match = compact(function_section(consumer_text, "pma_alias_chain_prefix_ends_at"))
alias_target_matches_owner = compact(function_section(consumer_text, "pma_alias_target_matches_owner"))
scope_owner = compact(function_section(consumer_text, "pma_scope_owner"))
alias_precedence = compact(function_section(consumer_text, "pma_using_alias_precedes"))
alias_shadowed = compact(function_section(consumer_text, "pma_using_alias_is_shadowed"))
inactive_import_branch = compact(function_section(consumer_text, "pma_import_annotation_in_inactive_static_branch"))
uncertain_import_row = compact(function_section(consumer_text, "pma_import_row_branch_uncertain"))
active_import_annotations = compact(function_section(consumer_text, "pma_active_import_annotations"))
argument_type_probe = compact(function_section(consumer_text, "pma_argument_type_name"))
call_target_normalizer = compact(function_section(consumer_text, "pma_normalize_call_callee"))
call_index_walker = compact(function_section(consumer_text, "pma_report_call_callee_indices"))
private_report = compact(function_section(consumer_text, "pma_report"))
private_index_init = compact(consumer_text)
if not all(fragment in private_index_build for fragment in (
        "index.declaration_offsets.push(annotation.offset)",
        "index.modules.push(module_annotation.name)")) or not all(fragment in private_symbol_marker for fragment in (
        "index.declaration_offsets[index_position]==symbol.offset",
        "index.names[index_position]==symbol.name",
        "index.modules[index_position]==symbol.module_owner")):
    raise SystemExit("private overload visibility must match the parser's declaration-position marker to its exact symbol")
if not all(fragment in private_call_exclusion for fragment in (
        'returnfalseifanyargument_nameinargument_nameswhereargument_name!=""',
        "pma_public_call_sibling_rank(file,index,table,annotations,owner,member,current_module,unqualified_call,arguments,bound,bound_types)",
        "pma_symbol_core_accepts_receiver_arity(symbol,arguments.count)",
        "pma_private_candidate_excluded_by_public_rank(table,annotations,symbol,public_rank.rank,actual_type)",
        "returnprivate_candidates>0.usize()andall_excluded")) or not all(fragment in core_arity_filter for fragment in (
        "argument_count.u32()>=symbol.arity_min",
        "argument_count.u32()<=symbol.arity_max")) or \
        "function_param_has_default" in core_arity_filter:
    raise SystemExit("private-call suppression must match Core's coarse arity filter and remain fail-closed for named or unknown calls")
if not all(fragment in static_if_char_value for fragment in (
        "end-start!=2",
        "end-start!=1",
        "escaped==110",
        "escaped==116",
        "escaped==114")) or "escaped.i64()" in static_if_char_value or \
        "Expr.FloatLit" in static_if_condition_value or "Expr.StringLit" in static_if_condition_value or \
        "continueifnotbranch.knownornotbranch.active" not in public_call_sibling_rank:
    raise SystemExit("PMA must keep unsupported character, float, and string conditions unknown and count only proven-active public siblings")
if not all(fragment in global_value_lookup for fragment in (
        'symbol.kind!=SymbolKind.Moduleandsymbol.module_owner==""',
        "returnfalse")) or not all(fragment in global_non_callable_lookup for fragment in (
        'symbol.kind!=SymbolKind.Moduleandsymbol.kind!=SymbolKind.Funcandsymbol.module_owner==""',
        "returnfalse")):
    raise SystemExit("global-name shadowing must use explicit root ownership, not counts that conflate imported overloads")
if not all(fragment in bare_owner_lookup for fragment in (
        "pma_has_global_value(table,member)",
        "pma_unqualified_private_import_owner(table,current_module,private_index,annotations,member)",
        "pma_has_public_imported_function_value(table,private_index,annotations,current_module,member,owner)")) or not all(fragment in call_owner_lookup for fragment in (
        "pma_has_global_non_callable_value(table,member)",
        "pma_unqualified_private_import_owner(table,current_module,private_index,annotations,member)")) or \
        "pma_has_global_value" in call_owner_lookup or "pma_has_global_non_callable_value" in bare_owner_lookup or \
        "pma_is_private" not in private_import_owner_lookup:
    raise SystemExit("bare global functions must shadow values while call lookup still checks imported private overloads")
if not all(fragment in public_imported_value for fragment in (
        "symbol.kind!=SymbolKind.Func",
        "pma_module_owns(table,symbol.module_owner,member)",
        "pma_unqualified_candidate_module_visible(index,annotations,current_module,symbol.module_owner,member)",
        "notpma_symbol_has_private_marker(index,symbol)")) or "pma_has_public_imported_function_value(table,private_index,annotations,current_module,member,owner)" not in bare_owner_lookup:
    raise SystemExit("a visible public callable import must keep a same-name private wildcard function from blocking its value")
if "pma_public_imported_module_member_visible(index,annotations,current_module,owner,member)" not in imported_member_visibility or not all(fragment in candidate_module_visibility for fragment in (
        "pma_imported_module_member_visible(index,annotations,current_module,candidate_module,member)",
        "pma_is_private(index,owner,segment)",
        "notpma_within_module(current_module,owner)")):
    raise SystemExit("public import alternatives must be visible in scope and outside every private module path")
if not all(fragment in private_import_visibility for fragment in (
        'annotation.name=="__binding_wildcard_import"',
        "pma_selective_import_target_status(annotations,current_module,owner,member)",
        "target.foundand(nottarget.knownortarget.first)")) or not all(fragment in public_import_visibility for fragment in (
        'annotation.name=="__binding_wildcard_import"',
        "pma_import_row_branch_uncertain(annotations,annotation.owner,annotation.name,annotation.module,annotation.line,annotation.offset)",
        "target.foundandtarget.knownandtarget.first")) or not all(fragment in selective_import_status for fragment in (
        "member_annotation.offset",
        "member_annotation.module",
        "source_annotation.name==owner",
        "candidate_is_using",
        'known_order<-falseifpma_import_row_branch_uncertain(annotations,"__from_member",member_annotation.name,member_annotation.module,member_annotation.line,member_annotation.offset)',
        "known_order",
        "source_annotation.offset!=member_annotation.offset")) or not all(fragment in using_member_registration for fragment in (
        'annotation.name=="__using_member"',
        "annotation.offset==member_annotation.offset")) or "returntrueifimport_scope==\"\"" not in import_scope_visibility:
    raise SystemExit("import visibility must preserve root/ancestor scope, first selective target, and Core's using-member registration order")
if not all(fragment in import_source_hash for fragment in (
        "name_hash(module)",
        "line.u64()",
        "offset.u64()")) or not all(fragment in import_source_contains for fragment in (
        "index.modules[row.usize()]==module",
        "index.lines[row.usize()]==line",
        "index.offsets[row.usize()]==offset",
        "source_annotation.name==source_module")) or not all(fragment in selective_import_index for fragment in (
        "pma_import_source_hash(annotation.module,annotation.line,annotation.offset)",
        "pma_import_source_head(sources,annotation.module,annotation.line,annotation.offset)",
        "sources.modules.push(annotation.module)",
        "sources.offsets.push(annotation.offset)",
        "sources.offsets[row.usize()]==annotation.offset")):
    raise SystemExit("selective imports must pair source and member annotations by lexical module, logical line, and token offset")
if not all(fragment in static_if_condition_value for fragment in (
        "Expr.BoolLit(value,_)",
        "Expr.CharLit(value,_)",
        "pma_static_if_char_value(value)",
        "Expr.Ident(name,_)",
        "ga_static_if_target_constant(name)",
        "ga_static_if_target_predicate(name)",
        "pma_static_if_named_constant_value(name,current_module,file,table,depth+1)",
        "pma_static_if_named_constant_value(name,current_module,file,table,depth+1,base)",
        "Expr.Scope(_,_,_)",
        "Expr.Field(_,_,_)",
        "Expr.Call(_,_,_,_)",
        "return(false,0)ifdepth>=64",
        "Expr.Unary(operator,operand,_)")) or not static_if_condition_value.endswith("_:return(false,0)") or not all(fragment in static_if_named_constant_value for fragment in (
        "return(false,0)ifdepth>=64",
        "table.immutable_const_values",
        "table.immutable_const_names",
        "table.immutable_const_rows",
        "symbol.module_owner",
        "pma_static_if_const_branch_selection(file,name,symbol,table,depth+1)",
        "continueifbranch.knownandnotbranch.active",
        "found_unknown",
        "unknown_scope_length>=selected_scope_length",
        "selected_ambiguous<-true",
        "return(false,0)ifselected_ambiguous",
        "selected_module<-symbol.module_owner",
        "table.immutable_const_values[selected_row],selected_module,file,table")) or not all(fragment in static_if_const_branch_selection for fragment in (
        'marker.owner!="__static_if_branch"',
        'marker.name!="__const_static_branch"',
        "marker.detail_name!=name",
        "marker.module!=symbol.module_owner",
        "marker.line!=symbol.line",
        "marker.offset!=symbol.offset",
        "pma_static_if_row_selection(file,marker.identity_id.usize(),symbol.module_owner,table,depth+1)",
        "return(false,false)ifunknown")) or not all(fragment in static_if_qualified_module_matches for fragment in (
        "pma_chain_ends_at(base,owner,owner.len)",
        "candidate_scope:mutablesview=current_module",
        "owner[prefix_length]==58",
        "string_view_slice(owner,(prefix_length+2.usize()).i64(),owner.len.i64())")) or not all(fragment in static_if_row_selection for fragment in (
        "file.static_if_lines",
        "file.static_if_kinds",
        "file.static_if_depths",
        "StaticIfBranch::Kind.ChainHead",
        "StaticIfBranch::Kind.Fallback",
        "row>=file.static_if_modules.count",
        "condition_module:sview=file.static_if_modules[row]",
        "pma_static_if_condition_value(file.static_if_conds[row],condition_module,file,table,depth+1)",
        "depth>=64",
        "return(false,false)ifnotcondition.known",
        "condition.knownandcondition.value!=0",
        "return(true,false)ifrow==branch_row")) or not all(fragment in static_if_named_constant_value for fragment in (
        "selected_scope_length",
        "symbol.module_owner.len>selected_scope_length",
        "symbol.module_owner.len==selected_scope_length",
        "return(false,0)",
        "table.immutable_const_values[selected_row]")) or not all(fragment in import_branch_selection for fragment in (
        'marker.owner!=marker_owner',
        'marker.name!=marker_name',
        'marker.detail_name!=marker_detail',
        'pma_static_if_row_selection(file,marker.identity_id.usize(),module,table)',
        'unknown<-trueifmarker.identity_id==4294967295ornotbranch.known',
        'marker.identity_id!=4294967295')) or not all(fragment in import_annotation_branch_selection for fragment in (
        'annotation.name=="__binding_wildcard_import"',
        '"__binding_wildcard_import_static_branch"',
        '"__from_member_static_branch"',
        '"__static_if_branch"',
        'annotation.name=="__using_alias"',
        'annotation.name=="__using_alias_target"',
        '"__using_alias_static_branch"',
        'pma_using_alias_for_using_row(annotations,annotation)',
        'alias_pair.alias_offset',
        'annotation.owner=="__private_member"',
        '"__private_member_static_branch"')) or not all(fragment in using_alias_for_using for fragment in (
        'candidate.name!="__using"',
        'candidate.module!=using_row.module',
        'candidate.line!=using_row.line',
        'candidate.offset<=using_row.offset',
        'target_row.name!="__using_alias_target"',
        'target_row.owner!=using_row.owner',
        'target_row.module!=using_row.module',
        'target_row.line!=using_row.line',
        'target_row.offset<=using_row.offset',
        'target_row.offset>=next_using_offset',
        'alias_row.offset==target_row.offset')) or not all(fragment in inactive_import_branch for fragment in (
        'branch.knownandnotbranch.active')) or not all(fragment in uncertain_import_row for fragment in (
        'marker.owner=="__pma_unknown_static_import"',
        'marker.name==import_owner',
        'marker.detail_name==import_name')) or not all(fragment in active_import_annotations for fragment in (
        'pma_import_annotation_branch_selection(annotation,file.enum_annotations,file,table)',
        'owner:"__pma_unknown_static_import"',
        'annotation.name=="__using_alias"',
        'notbranch.known')):
    raise SystemExit("PMA import visibility must filter known-inactive rows and mark unresolved static-arm imports as uncertain")
if not all(fragment in selective_import_status for fragment in (
        'pma_import_row_branch_uncertain(annotations,"__from_member",member_annotation.name,member_annotation.module,member_annotation.line,member_annotation.offset)',
        'known_order<-false')) or not all(fragment in public_import_visibility for fragment in (
        'pma_import_row_branch_uncertain(annotations,annotation.owner,annotation.name,annotation.module,annotation.line,annotation.offset)')):
    raise SystemExit("uncertain selective or wildcard imports must not establish a definite public winner")
if not all(fragment in active_import_annotations for fragment in (
        'annotation.owner=="__from_member"',
        'annotation.name=="__binding_wildcard_import"',
        'annotation.name=="__using_alias"',
        'annotation.name=="__using_alias_target"')):
    raise SystemExit("PMA filtering must cover selective and wildcard import rows")
if not all(fragment in parser_using_alias for fragment in (
        'name:"__using_alias",module:parser.current_module,line:alias_token.line,offset:alias_token.start',
        'name:"__using_alias_target",module:parser.current_module,line:alias_token.line,offset:alias_token.start',
        'parser.record_static_if_branch_rows("__using_alias_static_branch",alias_name,alias_token)')):
    raise SystemExit("alias branch markers must stay tied to the alias-token coordinates used by import cache selection")
if not all(fragment in build_import_views for fragment in (
        'pma_active_import_annotations(file,table)',
        'table.definite_import_annotations<-[]',
        'table.possible_import_annotations<-[]',
        'semantic_is_synthetic_unknown_import_marker(annotation)',
        'pma_import_row_branch_uncertain(active,annotation.owner,annotation.name,annotation.module,annotation.line,annotation.offset)',
        'table.possible_import_annotations.push(annotation)',
        'table.definite_import_annotations.push(annotation)')) or not all(fragment in synthetic_import_marker for fragment in (
        'annotation.owner=="__pma_unknown_static_import"',
        'annotation.detail_name!=""')):
    raise SystemExit("post-collect import views must keep original unknown rows separate from definite caches")
if 'semantic_is_synthetic_unknown_import_marker(annotation)' not in wildcard_import_builder or 'semantic_is_synthetic_unknown_import_marker(annotation)' not in binding_import_builder or 'semantic_is_synthetic_unknown_import_marker(target_row)' not in alias_member_builder:
    raise SystemExit("ordinary import cache builders must discard synthetic sentinels without dropping same-spelled source aliases")
for setup in (prepare_symbol_table, unresolved_table_setup, unresolved_references_setup):
    if 'semantic_build_import_annotation_views(file,table)' not in setup or 'table.definite_import_annotations' not in setup:
        raise SystemExit("all table setup/rebuild entry points must build and consume the definite/possible import views")
if not all(fragment in prepare_symbol_table for fragment in (
        'table.protocol_annotations<-file.enum_annotations',
        'table.using_alias_rows.push(annotation)',
        'collect_range(file.top_decls,table,file.enum_annotations)',
        'semantic_build_import_annotation_views(file,table)')) or not (
        prepare_symbol_table.find('table.using_alias_rows.push(annotation)') < prepare_symbol_table.find('collect_range(file.top_decls,table,file.enum_annotations)') < prepare_symbol_table.find('semantic_build_import_annotation_views(file,table)')
    ):
    raise SystemExit("raw pre-collect using-alias ordering and post-collect import selection must remain separate")
if not all(fragment in possible_import_name_visible for fragment in (
        'semantic_possible_import_member_visible(table,name,current_scope)',
        'semantic_possible_import_module_alias(table,name,current_scope)',
        'module_import:bool=annotation.name=="__using"orannotation.name=="__using_alias_target"orannotation.name=="__binding_wildcard_import"',
        'module_importandsemantic_import_scope_visible(annotation.module,current_scope)',
        'semantic_possible_import_import_row_member_visible(table,annotation,name,current_scope)')) or not all(fragment in possible_import_member_visible for fragment in (
        'annotation.owner=="__from_member"',
        'annotation.name==name',
        'semantic_import_scope_visible(annotation.module,current_scope)')) or not all(fragment in possible_import_type_selection for fragment in (
        'semantic_import_scope_visible(annotation.module,current_scope)',
        'source.owner!="__from_src"',
        'semantic_possible_import_type_path_candidate_matches(table,symbol.module_owner,source.name,name,kind,include_constants,source.module,source.offset)',
        'annotation.name=="__using_alias_target"',
        'semantic_possible_import_alias_target_row_can_win(annotation,current_scope,table)',
        'annotation.name=="__using"',
        'semantic_import_using_row_has_alias_pair(annotation,table)',
        'annotation.name=="__binding_wildcard_import"',
        'semantic_possible_import_type_path_candidate_matches(table,symbol.module_owner,annotation.owner,name,kind,include_constants,annotation.module,annotation.offset)')) or not all(fragment in possible_import_alias for fragment in (
        'annotation.name=="__using_alias"',
        'annotation.owner==alias_name',
        'semantic_possible_import_alias_can_win(annotation,current_scope,4294967295,table)')) or not all(fragment in possible_import_module_visible for fragment in (
        'annotation.name=="__using_alias_target"',
        'semantic_possible_import_alias_target_row_can_win(annotation,current_scope,table)',
        'semantic_import_using_row_has_alias_pair(annotation,table)',
        'semantic_possible_import_module_path_module_candidate_matches(table,owner,annotation.owner,annotation.module,annotation.offset)')) or not all(fragment in possible_import_member_owner for fragment in (
        'semantic_possible_import_module_path_candidate_matches(table,owner,source.name,name,source.module,source.offset)')) or not all(fragment in possible_import_module_member for fragment in (
        'semantic_possible_import_module_path_member_visible(table,owner,name,current_scope,4294967295)',
        'semantic_possible_import_alias_target_row_can_win(target,current_scope,table)',
        'semantic_possible_import_module_path_member_visible(table,target.owner,name,target.module,target.offset)')) or not all(fragment in possible_import_module_path for fragment in (
        'candidate_owner==target',
        'at_scope_boundary:bool=prefix_length==import_scope.lenor(prefix_length+1.usize()<import_scope.lenandimport_scope[prefix_length]==58andimport_scope[prefix_length+1.usize()]==58)',
        'expected_length:usize=prefix_length+2.usize()+target.len',
        'candidate_owner.len==expected_length',
        'candidate_owner[prefix_length]==58andcandidate_owner[prefix_length+1.usize()]==58',
        'matches_target<-falseifcandidate_owner[prefix_length+2.usize()+index]!=target[index]',
        'returntrueifmatches_target')):
    raise SystemExit("possible imports must preserve ordinary scope visibility and resolve candidate paths through the selected alias or raw root")
if not all(fragment in possible_import_alias_target_row_can_win for fragment in (
        'target_row.name!="__using_alias_target"',
        'candidate.name=="__using_alias"',
        'candidate.name=="__using_alias_target"',
        'candidate.module==target_row.module',
        'candidate.line==target_row.line',
        'candidate.offset==target_row.offset',
        'alias_count!=1.usize()',
        'target_count!=1.usize()',
        'alias.owner==""',
        'paired_target_owner==""',
        'paired_target_owner!=target_row.owner',
        'semantic_possible_import_alias_can_win(alias,current_scope,4294967295,table)')) or not all(fragment in possible_import_alias_target_prefix for fragment in (
        'return(false,false,0)ifnotalias.known',
        'ifalias.found:',
        'semantic_import_module_path_prefix_matches(candidate_owner,alias.target,alias.scope)',
        'semantic_possible_import_alias_target_prefix(candidate_owner,alias.raw_target,alias.scope,alias.offset,table,depth+1.u32())',
        'return(true,false,0)ifnotcanonical_prefix.matches',
        'semantic_import_module_path_prefix_matches(candidate_owner,target_path,import_scope)')) or not all(fragment in possible_import_alias_target_matches for fragment in (
        'semantic_possible_import_alias_target_prefix(candidate_owner,target_path,import_scope,before_offset,table)',
        'returntrueifnottarget_prefix.known',
        'returnfalseifnottarget_prefix.matches',
        'appended.end==candidate_owner.len')) or not all(fragment in possible_import_alias_target_head_status for fragment in (
        'semantic_possible_import_alias_head_target(alias_name,import_scope,before_offset,table)',
        'return(alias.known,alias.found)')) or not all(fragment in possible_import_alias_target_alias_matches for fragment in (
        'semantic_possible_import_alias_target_head_status(target_path,import_scope,before_offset,table)',
        'returntrueifnothead.known',
        'returnfalseifnothead.found',
        'semantic_possible_import_alias_target_matches(candidate_owner,target_path,"",import_scope,before_offset,table)')) or not all(fragment in possible_import_module_path_alias_member for fragment in (
        'semantic_possible_import_alias_target_alias_matches(symbol.module_owner,target_path,import_scope,before_offset,table)',
        'semantic_possible_import_alias_target_alias_matches(table.module_member_owner[member_index],target_path,import_scope,before_offset,table)')) or not all(fragment in possible_import_module_path_member for fragment in (
        'semantic_possible_import_alias_target_head_status(target_path,import_scope,before_offset,table)',
        'semantic_possible_import_module_path_alias_member_visible(table,target_path,name,import_scope,before_offset)',
        'semantic_import_module_path_matches(symbol.module_owner,target_path,import_scope)',
        'semantic_import_module_path_matches(table.module_member_owner[member_index],target_path,import_scope)')) or not all(fragment in possible_import_module_path_candidate for fragment in (
        'semantic_possible_import_alias_target_head_status(target_path,import_scope,before_offset,table)',
        'semantic_possible_import_module_path_alias_member_visible(table,target_path,name,import_scope,before_offset)',
        'semantic_possible_import_alias_target_alias_matches(candidate_owner,target_path,import_scope,before_offset,table)',
        'semantic_import_module_path_matches(candidate_owner,target_path,import_scope)')) or not all(fragment in possible_import_type_path_candidate for fragment in (
        'semantic_possible_import_alias_target_head_status(target_path,import_scope,before_offset,table)',
        'symbol.name==name',
        'symbol.kind==kind',
        'semantic_possible_import_alias_target_alias_matches(symbol.module_owner,target_path,import_scope,before_offset,table)',
        'semantic_possible_import_alias_target_alias_matches(candidate_owner,target_path,import_scope,before_offset,table)',
        'semantic_import_module_path_matches(candidate_owner,target_path,import_scope)')) or not all(fragment in possible_import_module_symbol_alias for fragment in (
        'alias.name=="__using_alias"',
        'alias.owner==symbol.name',
        'alias.line==symbol.line',
        'alias.offset==symbol.offset')) or not all(fragment in possible_import_module_path_alias_module for fragment in (
        'formodule_rowintable.module_symbol_rows',
        'semantic_possible_import_module_symbol_is_using_alias(symbol,table)',
        'semantic_possible_import_alias_target_alias_matches(symbol.name,target_path,import_scope,before_offset,table)')) or not all(fragment in possible_import_module_path_module_candidate for fragment in (
        'semantic_possible_import_alias_target_head_status(target_path,import_scope,before_offset,table)',
        'semantic_possible_import_module_path_alias_module_visible(table,target_path,import_scope,before_offset)',
        'semantic_possible_import_alias_target_alias_matches(candidate_owner,target_path,import_scope,before_offset,table)',
        'semantic_import_module_path_matches(candidate_owner,target_path,import_scope)')) or not all(fragment in possible_import_import_row_member for fragment in (
        'import_row.name=="__using_alias_target"',
        'semantic_possible_import_alias_target_row_can_win(import_row,current_scope,table)',
        'import_row.name=="__using"',
        'semantic_import_using_row_has_alias_pair(import_row,table)',
        'semantic_possible_import_module_path_member_visible(table,import_row.owner,name,import_row.module,import_row.offset)')):
    raise SystemExit("possible alias targets and selective imports must preserve exact winner gating and candidate-level alias-before-raw selection")
if not (possible_import_alias_target_prefix.find('ifalias.found:') < possible_import_alias_target_prefix.find('direct:(matches:bool,end:usize)=semantic_import_module_path_prefix_matches(candidate_owner,target_path,import_scope)')):
    raise SystemExit("nested raw-target expansion must only fall back after the alias head is known absent")
for source, order in (
        (possible_import_module_path_member, (
            'returntrueifnotalias_head.known',
            'ifalias_head.found:',
            'semantic_possible_import_module_path_alias_member_visible(table,target_path,name,import_scope,before_offset)',
            'semantic_import_module_path_matches(symbol.module_owner,target_path,import_scope)')),
        (possible_import_module_path_candidate, (
            'semantic_possible_import_module_path_alias_member_visible(table,target_path,name,import_scope,before_offset)',
            'semantic_possible_import_alias_target_alias_matches(candidate_owner,target_path,import_scope,before_offset,table)',
            'semantic_import_module_path_matches(candidate_owner,target_path,import_scope)')),
        (possible_import_type_path_candidate, (
            'alias_candidate_exists:bool=anysymbolintable.symbols',
            'semantic_possible_import_alias_target_alias_matches(candidate_owner,target_path,import_scope,before_offset,table)',
            'semantic_import_module_path_matches(candidate_owner,target_path,import_scope)')),
        (possible_import_module_path_module_candidate, (
            'semantic_possible_import_module_path_alias_module_visible(table,target_path,import_scope,before_offset)',
            'semantic_possible_import_alias_target_alias_matches(candidate_owner,target_path,import_scope,before_offset,table)',
            'semantic_import_module_path_matches(candidate_owner,target_path,import_scope)'))):
    positions = [source.find(fragment) for fragment in order]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit("possible-import candidate selection must choose the complete alias candidate set before raw fallback")
if any(fragment in function for function in (possible_import_module_visible, possible_import_type_selection, possible_import_member_owner, possible_import_module_member) for fragment in (
        'semantic_import_module_path_matches(owner,annotation.owner,annotation.module)',
        'semantic_import_module_path_matches(symbol.module_owner,annotation.owner,annotation.module)',
        'semantic_import_module_path_matches(owner,source.name,source.module)',
        'semantic_import_module_path_matches(symbol.module_owner,source.name,source.module)',
        'semantic_possible_import_alias_module_path_matches(owner,annotation.owner,annotation.module,annotation.offset,table)',
        'semantic_possible_import_alias_module_path_matches(symbol.module_owner,annotation.owner,annotation.module,annotation.offset,table)',
        'semantic_possible_import_alias_module_path_matches(owner,source.name,source.module,source.offset,table)',
        'semantic_possible_import_alias_module_path_matches(symbol.module_owner,source.name,source.module,source.offset,table)')):
    raise SystemExit("possible-import consumers must not OR alias targets with raw root-path matches")
if not all(fragment in possible_import_module_path_suffix for fragment in (
        'tail_length:usize=target.len+2.usize()+suffix.len',
        'candidate_owner.len==tail_length',
        'candidate_owner[target_end]==58',
        'candidate_owner[target_end+1.usize()]==58')) or not all(fragment in possible_import_alias_module_path for fragment in (
        'string_view_slice(target,0,head_length.i64())',
        'string_view_slice(target,(head_length+2.usize()).i64(),target.len.i64())',
        'semantic_possible_import_alias_can_win(alias,import_scope,before_offset,table)',
        'semantic_possible_import_alias_target_matches(candidate_owner,target_row.owner,suffix,target_row.module,target_row.offset,table)',
        'semantic_possible_import_alias_dependency_exists(raw_target_row.owner,alias.module,alias.offset,table)',
        'semantic_possible_import_alias_target_matches(candidate_owner,raw_target_row.owner,suffix,raw_target_row.module,raw_target_row.offset,table)')):
    raise SystemExit("possible import path matching must preserve qualified alias suffixes and use the selected global alias rows")
if not all(fragment in possible_import_alias_dependency for fragment in (
        'depth>=64',
        'semantic_possible_import_alias_head_target(alias_name,import_scope,before_offset,table)',
        'semantic_possible_import_alias_dependency_exists(alias.raw_target,alias.scope,alias.offset,table,depth+1.u32())')) or not all(fragment in possible_import_alias_branch for fragment in (
        'marker.name=="__using_alias_static_branch"',
        'marker.detail_name==alias.owner')) or not all(fragment in possible_import_alias_branch_marker_at for fragment in (
        'marker.identity_id==4294967295',
        'seen==ordinal',
        'return(true,marker.identity_id)')) or not all(fragment in possible_import_alias_branch_marker_count for fragment in (
        'marker.identity_id==4294967295',
        'return(true,count)')) or not all(fragment in possible_import_alias_branch_stack for fragment in (
        'shared_count:usize=left_stack.countifleft_stack.count<right_stack.countelseright_stack.count',
        'left_marker.identity!=right_marker.identity',
        'shared_prefixandleft_stack.count==right_stack.count')):
    raise SystemExit("possible alias dependencies must use exact source targets and preserve branch identity stacks")
if not all(fragment in possible_import_alias_order for fragment in (
        'left.module==right.module',
        'branch_relation<-semantic_possible_import_alias_branch_stack_relation(left,right,table)',
        'left_is_branchandright_is_branchandnotbranch_relation.known',
        'return(true,notleft_is_branch)ifleft_is_branch!=right_is_branch',
        'branch_relation.shared_prefix',
        'branch_relation.left_count<branch_relation.right_count',
        'both_definite:bool=left_is_branchandright_is_branchandsemantic_possible_import_alias_is_definite(left,table)andsemantic_possible_import_alias_is_definite(right,table)',
        'return(true,true)ifbranch_relation.left_count<=branch_relation.right_count',
        'return(true,false)ifbranch_relation.right_count<=branch_relation.left_count',
        'ifnotright_is_branch:return(false,false)ifleft.offset==right.offsetreturn(true,left.offset<right.offset)',
        'ifnotleft_is_branch:return(false,false)ifleft.offset==right.offsetreturn(true,left.offset<right.offset)',
        'return(true,left.offset<right.offset)',
        'named_type_owner_is_lexical(left.module,right.module)',
        'named_type_owner_is_lexical(right.module,left.module)',
        'left.offset<right.offset')) or not all(fragment in possible_import_alias_definite for fragment in (
        'row.name==alias.name',
        'row.owner==alias.owner',
        'row.module==alias.module',
        'row.line==alias.line',
        'row.offset==alias.offset')) or not all(fragment in possible_import_alias_position for fragment in (
        'semantic_possible_import_alias_precedes(alias,requester,table)',
        'requester.name=="__using_alias"',
        'alias.module==scope',
        'named_type_owner_is_lexical(alias.module,scope)',
        'alias_is_branch',
        'return(true,true)')):
    raise SystemExit("possible alias winner selection must use Core's global order and fail closed for unknown branch relations")
if not all(fragment in possible_import_alias_head_target for fragment in (
        'table.definite_import_annotations',
        'semantic_possible_import_alias_precedes_position(alias,import_scope,before_offset,table)',
        'semantic_possible_import_alias_precedes(other,alias,table)',
        'raw_target_count!=1.usize()',
        'canonical_target_count!=1.usize()',
        'table.possible_import_annotations')):
    raise SystemExit("possible alias chains must choose one prior global winner and pair it with one raw/canonical target")
if not all(fragment in possible_import_alias_head_target for fragment in (
        'candidate_wins:mutablebool=true',
        'ifselected_found:',
        'raw_target_count:mutableusize=0',
        'canonical_target_count:mutableusize=0')) or (
        possible_import_alias_head_target.index('raw_target_count:mutableusize=0') <
        possible_import_alias_head_target.index('candidate_wins:mutablebool=true')):
    raise SystemExit("possible alias target rows must be validated after the final global winner is selected")
if not all(fragment in possible_import_alias_precedence for fragment in (
        'semantic_possible_import_alias_precedes_position(alias,import_scope,before_offset,table)',
        'table.definite_import_annotations',
        'semantic_possible_import_alias_precedes(candidate,selected,table)',
        'semantic_possible_import_alias_precedes(alias,selected,table)',
        'other_before_position.knownandnotother_before_position.precedes',
        'returntrueiffound_priorand(notselected_foundorwinner_ambiguous)',
        'returnfalseifcandidate_before.knownandnotcandidate_before.precedes',
        'returnnotcandidate_before.knownorcandidate_before.precedes',
        'returntrueifnotorder.known')) or 'semantic_possible_import_alias_can_win(alias,import_scope,before_offset,table)' not in possible_import_alias_module_path:
    raise SystemExit("possible alias paths must account for global definite winners and remain conservative when ordering is unknown")
if not all(fragment in resolver_name_known for fragment in ('semantic_possible_import_name_visible(table,name,table.current_module)',)) or not all(fragment in resolver_name_classification for fragment in (
        'semantic_possible_import_name_visible(table,name,table.current_module)')) or not all(fragment in resolver_wildcard_uncertainty for fragment in (
        'table.possible_import_annotations',
        'rew_has_type_declaration(name,possible.owner,table)')) or not all(fragment in resolver_module_alias for fragment in (
        'semantic_possible_import_module_alias(table,name,table.current_module)')) or not all(fragment in resolver_qualified_alias_uncertainty for fragment in (
        'semantic_possible_import_module_member_visible(table,base_name,name,table.current_module)')):
    raise SystemExit("resolver name and wildcard ambiguity paths must account conservatively for possible imports")
if not all(fragment in binding_nominal_lookup for fragment in (
        'semantic_possible_import_may_select_type(table,name,SymbolKind.Struct,scope,include_constants)',
        'possible_import_match')) or not all(fragment in named_struct_lookup for fragment in (
        'semantic_possible_import_may_select_type(table,type_name,SymbolKind.Struct,table.current_module)',
        'possible_import_matchandbest_rank==0')) or not all(fragment in enum_owner_lookup for fragment in (
        'semantic_possible_import_may_select_type(table,name,kind,context_module)')):
    raise SystemExit("exact nominal and enum-owner selection must decline when a possible import can change the winner")
if not all(fragment in construct_call_lookup for fragment in ('semantic_possible_import_name_visible(table,name,table.current_module)',)) or not all(fragment in readonly_callee_lookup for fragment in (
        'semantic_possible_import_name_visible(table,callee,caller_owner)')) or not all(fragment in private_field_owner_lookup for fragment in (
        'semantic_possible_import_module_visible(table,owner,scope)',
        'semantic_possible_import_member_owner_visible(table,owner,name,scope)')):
    raise SystemExit("type, constructor, readonly, and private-field consumers must not choose a definite owner from possible imports")
if 'UNKNOWN_DUPLICATE_IMPORT' not in module_alias_precedence_text or 'using Secret, Secret as UnknownDuplicateAlias' not in module_alias_precedence_text or 'UnknownDuplicateAlias::hidden()' not in module_alias_precedence_text:
    raise SystemExit("aliased using branch regression must cover a wildcard row followed by a same-target alias on one source line")
if not all(fragment in compact(parser_text) for fragment in (
        'parser<-parser.record_static_if_branch_rows("__from_member_static_branch",member,token)',
        'parser<-parser.record_static_if_branch_markers(marker_name,detail_name,token.line,token.start)',
        'owner:"__static_if_branch",name:marker_name,detail_name:detail_name,module:marker_module',
        'identity_id:branch_identity')):
    raise SystemExit("selective import parser rows must carry the member token's enclosing static-if branch identities")
function_declaration_parser = compact(function_section(parser_function_text, "function_declaration"))
if 'parser<-parser.record_static_if_branch_rows("__function_static_branch",function_name,token)' not in function_declaration_parser:
    raise SystemExit("function declarations must carry their exact enclosing static-if branch identities for overload ranking")
const_declaration_parser = compact(function_section(parser_const_text, "const_declaration"))
if 'parser.record_static_if_branch_rows("__const_static_branch",Lexer::text_or_empty(name_token,parser.source,parser.source_length),token)ifnotis_global' not in const_declaration_parser:
    raise SystemExit("immutable const declarations must carry static-if branch identities for PMA condition folding")
private_markers = compact(function_section(parser_text, "record_static_if_branch_markers"))
if not all(fragment in private_record for fragment in (
        'parser<-parser.record_static_if_branch_markers("__private_member_static_branch",member_name,section_line,member_position.offset)',)) or not all(fragment in private_markers for fragment in (
        'marker_name',
        'detail_name',
        'marker_module',
        'marker_line',
        'marker_offset',
        'owner:"__static_if_branch"',
        'identity_id:branch_identity')):
    raise SystemExit("private declarations must carry their enclosing static-if branch identities")
if not all(fragment in import_annotation_branch_selection for fragment in (
        'annotation.owner=="__private_member"',
        'module_annotation.owner!="__private_member_module"',
        'pma_import_branch_selection(annotations,file,table,"__static_if_branch","__private_member_static_branch",annotation.name,member_module,annotation.line,annotation.offset)',
        'annotation.name=="__using"',
        '"__binding_wildcard_import_static_branch"',
        'annotation.name=="__using_alias"',
        '"__using_alias_static_branch"',
        'annotation.name=="__using_alias_target"',
        '"__private_member_static_branch"',
        'module_annotation.name')) or not all(fragment in active_import_annotations for fragment in (
        'private_member_row:bool=annotation.owner=="__private_member"',
        'branch_row:bool=import_roworprivate_member_row',
        'annotation.name=="__using"',
        'annotation.name=="__using_alias"',
        'annotation.name=="__using_alias_target"',
        'branch.knownandnotbranch.active')):
    raise SystemExit("PMA must remove proven-inactive private declarations before building its privacy index")
if not all(fragment in parser_consume_using_target for fragment in (
        'parser.record_using_annotation(Ast::EnumAnnotation{owner:recorded_target,name:"__using",module:parser.current_module,line:target_token.line,offset:target_token.start})',
        'parser.using_alias(alias_target)')) or not all(fragment in parser_using_alias for fragment in (
        'offset:alias_token.start',
        'name:"__using_alias_target"')):
    raise SystemExit("the legacy using row and alias pair must retain their distinct parser token offsets")
if not all(fragment in import_using_row_alias_pair for fragment in (
        'using_row.name!="__using"',
        'candidate.module!=using_row.module',
        'candidate.line!=using_row.line',
        'candidate.offset<=using_row.offset',
        'candidate.offset<next_using_offset',
        'forcandidateintable.possible_import_annotations',
        'target_row.owner!=using_row.owner',
        'target_row.module!=using_row.module',
        'target_row.line!=using_row.line',
        'target_row.offset<=using_row.offset',
        'target_row.offset>=next_using_offset',
        'alias_row.name=="__using_alias"',
        'alias_row.module==target_row.module',
        'alias_row.line==target_row.line',
        'alias_row.offset==target_row.offset',
        'foralias_rowintable.possible_import_annotations',
        'fortarget_rowintable.possible_import_annotations')):
    raise SystemExit("alias-associated legacy using rows must be identified without altering the raw import views")
if not all(fragment in binding_import_builder for fragment in (
        'annotation.name=="__using_alias_target"',
        'binding_resolve_module_alias_target(annotation.owner,requester,table)',
        'normalized<-annotation{owner=canonical_target}',
        'table.binding_import_annotations.push(normalized)')) or not all(fragment in import_alias_pair_target for fragment in (
        'candidate.name=="__using_alias"',
        'target.name=="__using_alias_target"',
        'candidate.module==alias.module',
        'candidate.line==alias.line',
        'candidate.offset==alias.offset',
        'target.module==alias.module',
        'target.line==alias.line',
        'target.offset==alias.offset',
        'alias_count!=1.usize()',
        'definite_alias_count!=1.usize()',
        'target_count!=1.usize()',
        'definite_target_count!=1.usize()',
        'target_owner==""')) or not all(fragment in import_alias_global_winner for fragment in (
        'semantic_possible_import_alias_is_definite(alias,table)',
        'semantic_import_alias_pair_target(alias,table)',
        'semantic_possible_import_alias_precedes(candidate,alias,table)',
        'returnfalseifnotorder.knownororder.precedes')) or not all(fragment in import_alias_target_global_winner for fragment in (
        'target.name!="__using_alias_target"',
        'pair.target!=target.owner',
        'semantic_import_alias_is_global_winner(alias,table)')) or not all(fragment in import_alias_target_canonical_owner for fragment in (
        'semantic_import_alias_target_is_global_winner(target,table)',
        'binding_target.name=="__using_alias_target"',
        'binding_target.module==target.module',
        'binding_target.line==target.line',
        'binding_target.offset==target.offset',
        'canonical_count!=1.usize()',
        'canonical_owner==""')):
    raise SystemExit("module-alias projections must require one exact winner pair and one canonical target")
if not all(fragment in alias_member_builder for fragment in (
        'semantic_import_alias_target_canonical_owner(target_row,table)',
        'canonical_target==""',
        'table.module_member_owner[member_index]!=canonical_target',
        'table.module_member_owner.push(alias_name)')):
    raise SystemExit("mirrored alias members must come from the exact canonical target")
for setup in (prepare_symbol_table, unresolved_table_setup, unresolved_references_setup):
    if not all(fragment in setup for fragment in (
            'table.imported_modules.push(annotation.owner)ifannotation.name=="__using"andnotsemantic_import_using_row_has_alias_pair(annotation,table)',
            'semantic_import_alias_target_canonical_owner(annotation,table)',
            'table.imported_modules.push(canonical_target)ifcanonical_target!=""',
            'semantic_import_alias_is_global_winner(annotation,table)')):
        raise SystemExit("every symbol-table construction path must project only exact alias winners and canonical targets")
    definite_import_view_index = setup.find('definite_import_annotations:darray[Ast::EnumAnnotation]=table.definite_import_annotations')
    binding_metadata_index = setup.find('binding_import_metadata(definite_import_annotations,table)')
    alias_members_index = setup.find('register_using_alias_members(definite_import_annotations,table)')
    canonical_target_index = setup.find('semantic_import_alias_target_canonical_owner(annotation,table)')
    if definite_import_view_index < 0 or binding_metadata_index < 0 or alias_members_index < 0 or canonical_target_index < 0 or not (
            definite_import_view_index < binding_metadata_index < alias_members_index < canonical_target_index):
        raise SystemExit("canonical alias projections must run after binding import metadata is built")
if not all(fragment in using_alias_target for fragment in (
        'target_row.name=="__using_alias_target"',
        "target_row.module==alias.module",
        "target_row.line==alias.line",
        "target_row.offset==alias.offset",
        "target_count==1.usize()")) or not all(fragment in alias_chain_match for fragment in (
        'Expr.Ident(head_name,_)',
        'head_name!=alias.owner',
        'pma_alias_target_matches_owner(annotations,candidate_owner,alias,table)',
        'pma_alias_chain_prefix_ends_at(inner,owner,end,last_name,alias,annotations,table)',
        'Expr.Scope(inner,last_name,_)')) or not all(fragment in alias_chain_prefix_match for fragment in (
        'pma_alias_chain_ends_at(inner,owner,start-2.usize(),alias,annotations,table)')) or not all(fragment in alias_target_matches_owner for fragment in (
        'semantic_possible_import_alias_target_prefix(candidate_owner,target,alias.module,alias.offset,table)',
        'target_prefix.knownandtarget_prefix.matchesandtarget_prefix.end==candidate_owner.len')) or not all(fragment in scope_owner for fragment in (
        'alias.name!="__using_alias"',
        "alias.owner!=alias_name",
        "pma_import_annotation_branch_selection(alias,annotations,file,table)",
        "pma_alias_chain_ends_at(base,candidate,candidate.len,alias,annotations,table)",
        "pma_using_alias_is_shadowed(annotations,file,table,alias)",
        "notbranch.knownornotbranch.active")) or "pma_import_scope_visible(current_module,alias.module)" in scope_owner or not all(fragment in alias_precedence for fragment in (
        "semantic_possible_import_alias_precedes(left,right,table)")) or not all(fragment in alias_shadowed for fragment in (
        "pma_using_alias_precedes(earlier_alias,alias,table)",
        "returntrueifnotorder.known",
        "returntrueiforder.precedes")):
    raise SystemExit("PMA must resolve exact global alias winners, preserve active-branch checks, and decline uncertain aliases")
static_statement_walk = compact(function_section(consumer_text, "pma_walk_stmts"))
if not all(fragment in static_if_row_for_position for fragment in (
        "selected:mutableusize=file.static_if_lines.count",
        "file.static_if_lines[row]==position.line",
        "file.static_if_offsets[row]==position.offset",
        "returnfile.static_if_lines.countifselected<file.static_if_lines.count")) or not all(fragment in static_statement_walk for fragment in (
        'Stmt.Block(kind,clause,binding,body,block_line)',
        'ifkind=="static":',
        "pma_static_if_row_for_position(file,block_line)",
        "pma_static_if_row_selection(file,branch_row,current_module,table)",
        "continueifbranch.knownandnotbranch.selected",
        "defpma_walk_stmts(statements:darray[Ast::Stmt],file:Ast::File&",
        "pma_walk_stmts(body,file,current_module,index,annotations,table,block_bound,block_bound_types)")) or \
        "defpma_report(file:Ast::File&,expression:Ast::Expr" not in private_report:
    raise SystemExit("PMA must skip statement bodies whose static-if branch is proven inactive")
check_private_entry = compact(function_section(consumer_text, "check_private_member_access"))
if not all(fragment in check_private_entry for fragment in (
        "annotations:darray[Ast::EnumAnnotation]=pma_active_import_annotations(file,table)",
        "pma_build_selective_import_index(annotations,private_index)",
        'pma_walk_declarations(file.top_decls,file,"",private_index,annotations,table)')):
    raise SystemExit("private-member checking must build its import index and walk declarations from branch-filtered annotations")
if not all(fragment in public_call_sibling_rank for fragment in (
        "pma_argument_type_name(arguments[0],bound,bound_types)",
        "pma_symbol_has_private_marker(index,symbol)",
        "ifnotunqualified_call:continueifsymbol.module_owner!=owner",
        "pma_unqualified_candidate_module_visible(index,annotations,current_module,symbol.module_owner,member)",
        "first_parameter.name==actual_type",
        "actual_type==\"int\"and(first_parameter.kind==SemTypeKind.Intorfirst_parameter.kind==SemTypeKind.Char)",
        "symbol.module_owner==\"\"orpma_within_module(current_module,symbol.module_owner)",
        "candidate_rank<-2.usize()",
        "first_parameter.kind==SemTypeKind.Namedandfirst_parameter.name==actual_typeandpma_named_type_spelling_is_unique(table,first_parameter.name)",
        "pma_generic_parameter_identity(annotations,first_parameter.name,symbol)")) or not all(fragment in candidate_module_visibility for fragment in (
        'candidate_module==""orpma_within_module(current_module,candidate_module)',
        "pma_imported_module_member_visible(index,annotations,current_module,candidate_module,member)")) or not all(fragment in private_candidate_rank for fragment in (
        'actual_type=="bool"',
        "public_rank>0.usize()",
        "pma_generic_parameter_identity(annotations,first_parameter.name,symbol)")):
    raise SystemExit("private-call suppression must prove exact public formals outrank private generic candidates while ties stay fail-closed")
if not all(fragment in named_type_spelling_unique for fragment in (
        "symbol.name!=name",
        "type_symbol:bool=symbol.kind==SymbolKind.Structorsymbol.kind==SymbolKind.Enumorsymbol.kind==SymbolKind.Aliasor(symbol.kind==SymbolKind.Externandsymbol.opaque_extern_type)",
        "nottype_symbol",
        "returnfalseiffound",
        "found<-true",
        "returnfound")):
    raise SystemExit("named-formal ranking must fail closed when a type spelling belongs to multiple nominal declarations")
if not all(fragment in private_candidate_rank for fragment in (
        "public_rank>1.usize()",
        "public_rank>0.usize()")):
    raise SystemExit("direct lexical winners must outrank imported candidates before same-tier receiver specificity")
if not all(fragment in static_if_function_branch_selection for fragment in (
        'marker.owner!="__static_if_branch"',
        'marker.name!="__function_static_branch"',
        "marker.detail_name!=name",
        "marker.module!=symbol.module_owner",
        "marker.line!=symbol.line",
        "marker.offset!=symbol.offset",
        "pma_static_if_row_selection(file,marker.identity_id.usize(),symbol.module_owner,table,depth+1)",
        "return(true,false)ifbranch.knownandnotbranch.selected",
        "return(false,false)ifunknown")) or \
        "pma_static_if_function_branch_selection(file,member,symbol,table,0)" not in public_call_sibling_rank or \
        "continueifnotbranch.knownornotbranch.active" not in public_call_sibling_rank:
    raise SystemExit("public overload ranking may suppress private access only for function candidates proven active by exact declaration branch markers")
if not all(fragment in argument_type_probe for fragment in (
        "Expr.IntLit(_,_)",
        'return"int"',
        "Expr.FloatLit(_,_)",
        'return"f64"')):
    raise SystemExit("PMA must recognize Core's untyped integer and default float receiver types before suppressing a private generic winner")
if not all(fragment in call_target_normalizer for fragment in (
        "Expr.Paren(inner,_)",
        "Expr.Index(object,_,_)ifpma_is_private_function_target(file,object,current_module,index,annotations,table,bound)",
        "Expr.IndexN(object,_,_)ifpma_is_private_function_target(file,object,current_module,index,annotations,table,bound)")) or not all(fragment in call_index_walker for fragment in (
        "Expr.Index(object,argument,_)",
        "Expr.IndexN(object,arguments,_)",
        "defpma_report_call_callee_indices(file:Ast::File&,expression:Ast::Expr",
        "pma_report(file,argument,current_module,index,annotations,table,bound,bound_types)")):
    raise SystemExit("parenthesized and explicit-generic private call targets must normalize without dropping index-argument checks")
bare_call = private_report.index("Expr.Ident(callee_name,callee_line):")
qualified_call = private_report.index("Expr.Scope(base,callee_name,callee_line):")
qualified_body = private_report[qualified_call:]
qualified_order = (
    "pma_report(file,base,current_module,index,annotations,table,bound,bound_types)",
    "owner:sview@source=pma_scope_owner(file,index,annotations,current_module,table,base,callee_name)",
    "pma_private_call_overloads_excluded(file,index,table,annotations,owner,callee_name,current_module,false,arguments,argument_names,bound,bound_types)",
    "table.diagnostics<-table.diagnostics.push(Diagnostic{kind:DiagnosticKind.PrivateMemberAccess,name:callee_name",
)
if bare_call > qualified_call or not all(fragment in private_report for fragment in (
        "normalized_callee:Ast::Expr=pma_normalize_call_callee(file,callee,current_module,index,annotations,table,bound)",
        "matchnormalized_callee:",
        "pma_unqualified_call_owner(table,current_module,index,annotations,bound,callee_name)",
        "pma_private_call_overloads_excluded(file,index,table,annotations,owner,callee_name,current_module,true,arguments,argument_names,bound,bound_types)",
        "pma_report_call_callee_indices(file,callee,current_module,index,annotations,table,bound,bound_types)ifnormalized_callee_is_path")) or \
        not all(fragment in qualified_body for fragment in qualified_order) or \
        sorted(qualified_body.index(fragment) for fragment in qualified_order) != [qualified_body.index(fragment) for fragment in qualified_order] or \
        "notpma_within_module(current_module,owner)andnotprivate_candidates_excluded" not in qualified_body:
    raise SystemExit("call checking must normalize private call forms, preserve private base barriers, and check selected overload families")
if "declaration_offsets:mutabledarray[u32]" not in private_index_init or \
        "declaration_offsets:[]" not in private_index_init:
    raise SystemExit("private declaration offsets must be initialized alongside the member index")
static_private_branch_match = re.search(r"(?ms)^module StaticPrivateBranchProvider:\n(.*?)(?=^(?:module |static if |using |from |def ))", call_shapes_text)
static_private_branch_fixture = static_private_branch_match.group(1) if static_private_branch_match else ""
if not all(fragment in compact(static_private_branch_fixture) for fragment in (
        "staticiffalse:private:defchoose()",
        "staticelse:public:defchoose()")):
    raise SystemExit("private-branch control must pair an inactive private declaration with an active public declaration of the same name")
if not all(fragment in call_shapes_text for fragment in (
        "return (Provider::dispatch)(value)",
        "return Provider::dispatch[bool](value)",
        "return dispatch(value)",
        "return dispatch[bool](value)",
        "return Provider::sealed(value)",
        "return BroadProvider::prefer(value)",
        "return NamedProvider::inspect(value)",
        "return QualifiedNamedProvider::inspect(value)",
        "return LiteralProvider::choose(7)",
        "return wrap(fetch)",
        "return wrap(retrieve)",
        "static if false:",
        "static else:",
        "from InactivePrivateProvider import pick",
        "from ActivePublicProvider import pick",
        "def inactive_branch_private_import_does_not_shadow_public()",
        "return pick()",
        "module StaticPrivateBranchProvider:",
        "def inactive_branch_private_declaration_does_not_hide_public()",
        "return StaticPrivateBranchProvider::choose()",
        "def public_concrete_over_private_generic(value: i64)",
        "def public_named_concrete_over_private_generic(value: UniqueWidget)",
        "def same_spelling_different_modules_private_generic_winner(value: Widget)",
        "def public_concrete_literal_winner()",
        "def public_selective_function_value()")) or not all(fragment in call_shapes_smoke_text for fragment in (
        'private_call_overload_visibility_shapes.elisa',
        '[[ $(grep -cF \'is private to module\' <<< "$stage0_output") == 2 ]]',
        '[[ $(grep -cF \'is private to module\' <<< "$stage1_output") == 2 ]]',
        "QualifiedNamedProvider.inspect")):
    raise SystemExit("call-shape fixture must cover parenthesized, explicit-generic, static-import visibility, and private-only controls")

if not all(fragment in unknown_static_import_text for fragment in (
        "const USE_PUBLIC_IMPORT: bool = true",
        "const USE_PRIVATE_WILDCARD: bool = false",
        "static if USE_PUBLIC_IMPORT:",
        "using PrivateWildcardProvider",
        "using PublicWildcardProvider",
        "from PublicProvider import pick",
        "static else:",
        "from PrivateProvider import pick",
        "def pick[T](value: T) -> i64:",
        "return pick(true)")) or not all(fragment in unknown_static_import_smoke_text for fragment in (
        "private_call_static_unknown_import.elisa",
        "Stage0 rejected the definite root generic winner",
        "Stage1 reported an imported private overload that loses to the root generic")):
    raise SystemExit("named-constant static import fixture must preserve the direct root generic winner")

static_true_import_control_text = STATIC_TRUE_IMPORT_CONTROL.read_text()
static_true_import_control_smoke_text = STATIC_TRUE_IMPORT_CONTROL_SMOKE.read_text()
if not all(fragment in static_true_import_control_text for fragment in (
        "static if true:",
        "const USE_PUBLIC_IMPORT: bool = true",
        "const USE_PUBLIC_IMPORT: bool = false",
        "const ENABLED: bool = true",
        "static if 'A' == 65:",
        "static if Flags::ENABLED:",
        "def pick(value: bool) -> i64:",
        "from PublicProvider import pick",
        "from PublicCharProvider import choose_char",
        "from PublicQualifiedProvider import choose_qualified",
        "static else:",
        "from PrivateProvider import pick",
        "from PrivateCharProvider import choose_char",
        "from PrivateQualifiedProvider import choose_qualified",
        "return pick(true) + choose_char(true) + choose_qualified(true)")) or not all(fragment in static_true_import_control_smoke_text for fragment in (
        "private_call_static_true_import_control.elisa",
        "Stage0 rejected the active public import",
        "Stage1 reported the inactive private import")):
    raise SystemExit("named-constant static-true control must prove that an inactive private import does not trigger PMA")

inactive_static_statement_text = INACTIVE_STATIC_STATEMENT.read_text()
inactive_static_statement_smoke_text = INACTIVE_STATIC_STATEMENT_SMOKE.read_text()
if not all(fragment in inactive_static_statement_text for fragment in (
        "module PrivateProvider:",
        "private:",
        "def hidden() -> i64:",
        "def main() -> i64:",
        "static if false:",
        "PrivateProvider::hidden()")) or not all(fragment in inactive_static_statement_smoke_text for fragment in (
        "private_call_in_inactive_static_statement.elisa",
        "Stage0 reported a private call in an inactive static arm",
        "Stage1 reported a private call in an inactive static arm")):
    raise SystemExit("inactive static-statement control must bind Stage0 and Stage1 behavior for a private call in a known-false branch")

nested_inactive_static_statement_text = NESTED_INACTIVE_STATIC_STATEMENT.read_text()
nested_inactive_static_statement_smoke_text = NESTED_INACTIVE_STATIC_STATEMENT_SMOKE.read_text()
if not all(fragment in nested_inactive_static_statement_text for fragment in (
        "static if false:",
        "static if true:",
        "PrivateProvider::hidden()")) or not all(fragment in nested_inactive_static_statement_smoke_text for fragment in (
        "private_call_in_nested_inactive_static_statement.elisa",
        "beneath an inactive enclosing arm")):
    raise SystemExit("nested static-statement control must bind an inner selected arm beneath a known-inactive parent")

inactive_static_declaration_text = INACTIVE_STATIC_DECLARATION.read_text()
inactive_static_declaration_smoke_text = INACTIVE_STATIC_DECLARATION_SMOKE.read_text()
declaration_walk_source = function_section(consumer_text, "pma_walk_declarations")
if not all(fragment in inactive_static_declaration_text for fragment in (
        "static if false:",
        "def inactive_function() -> i64:",
        "PrivateProvider::hidden()",
        "def main() -> i64:")) or not all(fragment in inactive_static_declaration_smoke_text for fragment in (
        "private_call_in_inactive_static_declaration.elisa",
        "inside an inactive function declaration")):
    raise SystemExit("inactive static-declaration control must bind skipped traversal through a known-false Decl.Scoped branch")
if not all(fragment in declaration_walk_source for fragment in (
        "Decl.Scoped(scoped_body, scoped_line):",
        "pma_static_if_row_for_position(file, scoped_line)",
        "pma_static_if_row_selection(file, branch_row, current_module, table)",
        "continue if branch.known and not branch.selected",
        "pma_walk_declarations(scoped_body, file, current_module, index, annotations, table)")):
    raise SystemExit("PMA declaration traversal must skip a Decl.Scoped body when its static-if row is proven inactive")

inactive_public_rank_text = INACTIVE_PUBLIC_OVERLOAD_RANK.read_text()
inactive_public_rank_smoke_text = INACTIVE_PUBLIC_OVERLOAD_RANK_SMOKE.read_text()
if not all(fragment in inactive_public_rank_text for fragment in (
        "module PrivateProvider:",
        "private:",
        "def choose(value: bool)",
        "static if false:",
        "def choose[T](value: T)",
        "from PrivateProvider import choose",
        "return choose(true)")) or not all(fragment in inactive_public_rank_smoke_text for fragment in (
        "private_call_inactive_public_overload_rank.elisa",
        "Stage0 missed the private imported call",
        "Stage1 let the inactive public generic suppress the privacy diagnostic")):
    raise SystemExit("inactive public overload control must bind the active private overload against a proven-inactive public generic")

unproven_public_siblings_text = UNPROVEN_PUBLIC_SIBLINGS.read_text()
unproven_public_siblings_smoke_text = UNPROVEN_PUBLIC_SIBLINGS_SMOKE.read_text()
if not all(fragment in unproven_public_siblings_text for fragment in (
        "def choose_default[T](value: T, first: i64, second: i64)",
        "def choose_default(value: bool, optional: i64 = 0)",
        "choose_default(true, 1, 2)",
        "static if 1.0 == 0.0:",
        "static if \"a\" == \"b\":",
        "choose_float(true)",
        "choose_string(true)")) or not all(fragment in unproven_public_siblings_smoke_text for fragment in (
        "private_call_unproven_public_siblings.elisa",
        "only viable overload is private",
        "let an invalid-arity or unprovable public sibling suppress privacy")):
    raise SystemExit("unproven public sibling regression must cover defaulted arity and unsupported float/string conditions")

same_line_import_pairing_text = SAME_LINE_IMPORT_PAIRING.read_text()
same_line_import_pairing_smoke_text = SAME_LINE_IMPORT_PAIRING_SMOKE.read_text()
if not all(fragment in same_line_import_pairing_text for fragment in (
        "module PrivateProvider:",
        "module PublicProvider:",
        "#line 70 public_import.elisa",
        "from PublicProvider import pick",
        "#line 70 private_import.elisa",
        "from PrivateProvider import pick",
        "return pick(true)")) or not all(fragment in same_line_import_pairing_smoke_text for fragment in (
        "private_call_same_line_import_pairing.elisa",
        "first public selective import",
        "another source at the same #line value")):
    raise SystemExit("selective-import regression must keep same-line source/member pairs distinct by token offset")

module_alias_private_call_text = MODULE_ALIAS_PRIVATE_CALL.read_text()
module_alias_private_call_smoke_text = MODULE_ALIAS_PRIVATE_CALL_SMOKE.read_text()
if not all(fragment in module_alias_private_call_text for fragment in (
        "module Secret:",
        "private:",
        "def hidden() -> i64:",
        "using Secret as Pick",
        "return Pick::hidden()")) or not all(fragment in module_alias_private_call_smoke_text for fragment in (
        "private_call_module_alias.elisa",
        "private call through a module alias",
        "missed the private module-alias call")):
    raise SystemExit("module-alias private-call regression must bind alias-qualified access to its target private module")

module_alias_precedence_text = MODULE_ALIAS_PRECEDENCE.read_text()
module_alias_precedence_smoke_text = MODULE_ALIAS_PRECEDENCE_SMOKE.read_text()
if not all(fragment in module_alias_precedence_text for fragment in (
        "static if true:",
        "using Secret as ActivePick",
        "static if false:",
        "using Secret as InactivePick",
        "using Public as InactivePick",
        "static if UNKNOWN_PICK:",
        "using Secret as UnknownPick",
        "using Public as UnknownPick",
        "ActivePick::hidden()",
        "InactivePick::hidden()",
        "UnknownPick::hidden()")) or not all(fragment in module_alias_precedence_smoke_text for fragment in (
        "private_call_module_alias_branch_precedence.elisa",
        "definitely-active private alias",
        "private_count")):
    raise SystemExit("module-alias regression must distinguish active, inactive, and unknown branches from unconditional aliases")

module_alias_chain_text = MODULE_ALIAS_CHAIN.read_text()
module_alias_chain_smoke_text = MODULE_ALIAS_CHAIN_SMOKE.read_text()
if not all(fragment in module_alias_chain_text for fragment in (
        "using Secret as First",
        "using First as Second",
        "return Second::hidden()",
        "module Backend:",
        "module Nested:",
        "def nested_hidden() -> i64:",
        "using Backend as BackendRoot",
        "using BackendRoot::Nested as NestedSecret",
        "module ProjectionWinner:",
        "def winner_only() -> i64:",
        "module ProjectionLoser:",
        "def loser_only() -> i64:",
        "using ProjectionWinner as ProjectionChoice",
        "using ProjectionLoser as ProjectionChoice",
        "ProjectionChoice::winner_only()",
        "ProjectionChoice::loser_only()",
        "return Second::hidden() + NestedSecret::nested_hidden() + ProjectionChoice::winner_only() + ProjectionChoice::loser_only()")) or not all(fragment in module_alias_chain_smoke_text for fragment in (
        "private_call_module_alias_chain.elisa",
        "chained module alias",
        "private alias-chain call",
        "qualified private alias-suffix call",
        "nested_hidden",
        "ProjectionChoice.loser_only",
        'undefined identifier "NestedSecret.nested_hidden"',
        'undefined identifier "ProjectionChoice.winner_only"')):
    raise SystemExit("module-alias regression must resolve a private module through a chained alias")

if not all(fragment in root_overloads_text for fragment in (
        "def choose(value: i64)",
        "def choose_selective(value: bool)",
        "from SelectiveProvider import choose_selective",
        "def prefer[T](value: T)",
        "def choose[T](value: T)",
        "def choose_selective[T](value: T)",
        "def prefer(value: bool)",
        "return choose(value)",
        "return choose_selective(value)",
        "return prefer(value)",
        "def local_rank[T](value: T)",
        "from Provider import local_rank",
        "def local_rank(value: bool)",
        "def local_concrete_wins(value: bool)",
        "return local_rank(value)")) or not all(fragment in root_overloads_smoke_text for fragment in (
        'private_call_root_overload_hidden_import.elisa',
        'grep -q \'^P 0$\' <<< "$stage1_output"',
        'is private to module')):
    raise SystemExit("root/local overload fixture must bind generic and concrete visible winners against private imported candidates")

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
