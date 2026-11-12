"""Source-bind conservative store-through collection to runtime-value AST children."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure
from store_walk_inspection import (
    CHV_FLOW_NAMES,
    compact,
    compact_code,
    function_section,
    enum_variant_names,
    explicit_match_arm_names,
    match_arm_body,
    source_route,
    direct_child,
    validate_ordered_source_lines,
    FOR_ITERATOR_STATEMENT,
    FOR_ITERATOR_BINDER_LOOP,
    FOR_ITERATOR_BIND,
    FOR_ITERATOR_BODY_WALK,
    validate_for_iterator_direct_routes,
    validate_for_iterator_order_self_cases,
    edge_parts,
    wrap_direct_child_block,
    struct_fields,
    validate_edge_set,
    validate_edge_set_without_mutation,
    validate_or_theorem,
    validate_exact_boolean_theorem,
    validate_exact_boolean_theorem_source_routes,
)
from store_walk_collection_edges import (
    EXPRESSION_EDGES,
    STATEMENT_COLLECTOR_EDGES,
    STATEMENT_UNIFIER_EDGES,
    EXPRESSION_UNIFIER_EDGES,
)
from store_walk_holder_traversal_edges import (
    HOLDER_SCAN_STATEMENT_EDGES,
    HOLDER_SCAN_EXPRESSION_EDGES,
    HOLDER_WALK_STATEMENT_EDGES,
    FOR_ITERATOR_VIEW_TAINT_EDGES,
    FOR_ITERATOR_REF_ALIAS_EDGES,
    ITERABLE_BINDING_FACTS_ALIAS_EDGES,
    HOLDER_WALK_EXPRESSION_EDGES,
    CATCH_ARM_PROVENANCE_EDGES,
    CATCH_PATTERN_BINDING_EDGES,
    EXPRESSION_BINDING_FACTS_OR_EDGES,
    PARALLEL_ASSIGNMENT_FLOW_EDGES,
)
from store_walk_view_flow_edges import (
    BINARY_AND_RIGHT_WALK_EDGE,
    BINARY_RIGHT_VIEW_EDGES,
    BINARY_OPERATOR_FALLBACK_EDGES,
)
from store_walk_view_flow_edges import (
    BINARY_NON_RUNTIME_TARGET_EDGES,
    CONSTRUCT_VIEW_TAINT_EDGES,
    RECORD_UPDATE_VIEW_TAINT_EDGES,
    FIELD_PROJECTION_VIEW_TAINT_EDGES,
    ARRAY_VIEW_TAINT_EDGES,
    DICT_VIEW_TAINT_EDGES,
    COMPREHENSION_VIEW_TAINT_EDGES,
    COMPREHENSION_BINDER_VIEW_TAINT_EDGES,
    IDENTIFIER_VIEW_TAINT_EDGES,
    METHOD_CALL_VIEW_RESULT_EDGES,
    CALLABLE_VIEW_RESULT_EDGES,
    CALL_RESULT_VIEW_TAINT_EDGES,
    CALL_RESULT_CALLEE_JOIN_EDGE,
    CALL_CALLEE_INDEXED_VIEW_EDGES,
    STATIC_EFFECT_RESULT_VIEW_TAINT_EDGES,
    ASSIGN_VIEW_TAINT_EDGES,
    PLACE_ROOT_PROJECTION_EDGES,
    EFFECT_CANDIDATE_EDGES,
    VIEW_FLOW_MERGE_EDGES,
    REF_ALIAS_FLOW_MERGE_EDGES,
    REF_ALIAS_HELPER_EDGES,
    COMPREHENSION_REF_ALIAS_EDGES,
    COMPREHENSION_CONTAIN_ALIAS_EDGES,
    ITERABLE_REF_ALIAS_EDGES,
    ITERABLE_CONTAIN_ALIAS_EDGES,
    TYPE_ALIAS_ITERABLE_COLLISION_EDGES,
    GETELSE_RECOVERY_TERMINATION_EDGES,
    SCALAR_SVIEW_FLOW_EDGES,
    VIEW_ALIAS_BINARY_EDGES,
    INDEX_OPERATOR_EDGES,
    INDEX_VIEW_RESULT_EDGES,
    INDEXN_VIEW_RESULT_EDGES,
    INDEXN_VIEW_WALK_EDGES,
    UNARY_NEGATION_EDGES,
    BINARY_VIEW_WALK_EDGES,
    BINARY_BOOLEAN_RESULT_EDGES,
    REINTERPRET_TARGET_MARKER_EDGES,
    UNARY_VIEW_RESULT_EDGES,
    REF_ALIAS_ADDRESS_EDGES,
    SUMMARY_CALL_EDGES,
    OVERLOAD_SUMMARY_EDGES,
    CALLEE_DISPATCH_EDGES,
    FIELD_UNKNOWN_CALL_EDGES,
    NAMED_CALL_EDGES,
    NAMED_ARGUMENT_UNIFIER_EDGES,
    NAMED_ARGUMENT_STATIC_EFFECT_EDGES,
    UNKNOWN_CALL_EDGES,
    UNIFIER_FALLBACK_EDGES,
)
from store_walk_theorem_routes import theorem_routes
from store_walk_theorem_checks import validate_theorem_routes


parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=not args.source_only)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not args.source_only)
SUMMARY = ROOT / "src/semantic/store_through_summary.elisa"
SUMMARY_PARTS = [SUMMARY, ROOT / "src/semantic/store_through_classes.elisa", ROOT / "src/semantic/store_through_summary_functions.elisa"]
HOLDER_SOURCE = ROOT / "src/semantic/check_call_holder_view_store.elisa"
HOLDER_PARTS = [
    HOLDER_SOURCE,
    ROOT / "src/semantic/check_call_holder_view_store/local_scans.elisa",
    ROOT / "src/semantic/check_call_holder_view_store/type_references.elisa",
    ROOT / "src/semantic/check_call_holder_view_store/alias_expressions.elisa",
    ROOT / "src/semantic/check_call_holder_view_store/alias_calls.elisa",
    ROOT / "src/semantic/check_call_holder_view_store/flow_binders.elisa",
    ROOT / "src/semantic/check_call_holder_view_store/walk.elisa",
]
SEMANTIC_ROOT = ROOT / "src/semantic/semantic.elisa"
AST_NODES = ROOT / "src/parser/ast_nodes.elisa"
AST_SIDE_TABLES = ROOT / "src/parser/ast_side_tables.elisa"
EFFECT_SHAPE = ROOT / "src/parser/effect_type_shape.elisa"
POSITIVE = HERE / "store_through_ast_walk.elisa"
NEGATIVE = HERE / "store_through_ast_walk_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
PROOF_TIMEOUT_SECONDS = 120

EXPECTED_EXPR_NAMES = tuple("""Invalid Absent IntLit FloatLit StringLit CharLit BoolLit Ident Call
    StaticEffectCall Field Scope ShorthandMember Index Slice IndexN Binary Unary Move RegionNew Paren
    Array Tuple SetLit DictLit Construct RecordUpdate If Match Catch Comprehension Refinement GetElse Lambda Block""".split())
EXPECTED_STMT_NAMES = tuple("Invalid Expr Block VarDecl Assign If While For Return Break Continue Match Contract".split())
EXPECTED_SIDE_TABLE_FIELDS = {
    "MatchArm": ("pattern:Pattern", "body:darray[Stmt] @source", "guard:Expr", "pos:Pos"),
    "DictEntry": ("key:Expr", "value:Expr"),
    "FieldInit": ("name:sview @source", "value:Expr", "is_copy_base:bool"),
    "StaticEffectCandidate": (
        "effect_type:Expr", "callee:sview @source", "captures:darray[Expr] @source",
        "effect_identity_id:u32", "handler_identity_id:u32", "callee_owner:sview @source",
    ),
}


_GUARDED_ARM_SAMPLE = """match statement:
    Stmt.For(bind, variables, iterable, body, _) if false:
        pass
"""
if "For" in explicit_match_arm_names(_GUARDED_ARM_SAMPLE, "match statement:", "Stmt."):
    raise SystemExit("guarded AST match arms must not satisfy exhaustive-source checks")


validate_for_iterator_order_self_cases()


semantic_root_text = SEMANTIC_ROOT.read_text()
for path in SUMMARY_PARTS[1:] + HOLDER_PARTS[1:]:
    include = f'include "./{path.relative_to(SEMANTIC_ROOT.parent).as_posix()}"'
    if semantic_root_text.count(include) != 1:
        raise SystemExit(f"semantic root must include {include!r} exactly once")
summary_text = "\n".join(path.read_text() for path in SUMMARY_PARTS)
ast_text = AST_NODES.read_text()
side_text = AST_SIDE_TABLES.read_text()
effect_text = EFFECT_SHAPE.read_text()
holder_text = "\n".join(path.read_text() for path in HOLDER_PARTS)
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

if enum_variant_names(ast_text, "Expr", "Stmt") != EXPECTED_EXPR_NAMES:
    raise SystemExit("Expr AST changed without revising the store-through collection proof")
if enum_variant_names(ast_text, "Stmt", "Decl") != EXPECTED_STMT_NAMES:
    raise SystemExit("Stmt AST changed without revising the store-through collection proof")
for record, expected in EXPECTED_SIDE_TABLE_FIELDS.items():
    if struct_fields(side_text, record) != expected:
        raise SystemExit(f"AST side-table record {record} changed without revising the store-through proof")

collector_wrapper = function_section(summary_text, "sts_collect_names")
expected_collector_wrapper = compact_code("""can Memory.Allocate, Abort.Panic:
    no_copy_safe: darray[sview] = []
    sts_collect_names_except(expression, out, no_copy_safe, no_copy_safe)""")
if compact_code(collector_wrapper) != expected_collector_wrapper:
    raise SystemExit("ordinary name collection must not suppress copied values")
collect_source = function_section(summary_text, "sts_collect_names_except")
statement_collect_source = function_section(summary_text, "sts_collect_statement_names")
unifier_source = function_section(summary_text, "sts_unify_calls")
statements_source = function_section(summary_text, "sts_statements")
bound_unifier_source = function_section(summary_text, "sts_unify_bound")
holder_scan_statements = function_section(holder_text, "chv_scan_locals")
holder_scan_expressions = function_section(holder_text, "chv_scan_expression_locals")
holder_walk_expressions = function_section(holder_text, "chv_walk_expression")
holder_walk_statements = function_section(holder_text, "chv_walk_statements")
scope_name_body = match_arm_body(collect_source, "match expression:", "Expr.Scope(_, _, _):")
if scope_name_body is None or compact_code(scope_name_body) != "pass":
    raise SystemExit("store-through name collector must not treat a namespace/type path as a runtime value")
if tuple(sorted(explicit_match_arm_names(collect_source, "match expression:", "Expr."))) != tuple(sorted(EXPECTED_EXPR_NAMES)):
    raise SystemExit("store-through name collector is not exhaustive over Expr")
if tuple(sorted(explicit_match_arm_names(statement_collect_source, "match statement:", "Stmt."))) != tuple(sorted(EXPECTED_STMT_NAMES)):
    raise SystemExit("store-through nested-statement collector is not exhaustive over Stmt")
statement_unifier_arms = explicit_match_arm_names(statements_source, "match statement:", "Stmt.")
statement_unifier_expected = set(EXPECTED_STMT_NAMES) - {"Invalid", "Break", "Continue"}
if tuple(sorted(statement_unifier_arms)) != tuple(sorted(statement_unifier_expected)):
    raise SystemExit("store-through statement walker omits an expression-bearing statement variant")
if len(re.findall(r"(?m)^\s*_:\s*$", statements_source)) != 1:
    raise SystemExit("store-through statement walker must retain a single explicit leaf fallback")

expr_unifier_arms = explicit_match_arm_names(unifier_source, "match expression:", "Expr.")
if tuple(sorted(expr_unifier_arms)) != tuple(sorted(("Call Field Index Binary Unary Move Paren If").split())):
    raise SystemExit("store-through unifier changed its explicit recursive cases")
if len(re.findall(r"(?m)^\s*_:\s*$", unifier_source)) != 3:
    raise SystemExit("store-through unifier must retain exactly one conservative fallback")
expected_fallback = compact_code("""hidden_names: mutable darray[sview] = []
sts_collect_names(expression, hidden_names)
sts_unify_all(classes, hidden_names)""")
fallback_block = match_arm_body(unifier_source, "match expression:", "_:")
if fallback_block is None or compact_code(fallback_block) != expected_fallback:
    raise SystemExit("store-through unifier fallback no longer unifies every collected hidden name")

validate_edge_set(collect_source, EXPRESSION_EDGES, "expression name collector")
validate_edge_set(statement_collect_source, STATEMENT_COLLECTOR_EDGES, "nested statement name collector")
validate_edge_set(unifier_source, EXPRESSION_UNIFIER_EDGES, "expression call unifier")
validate_edge_set(statements_source, STATEMENT_UNIFIER_EDGES, "statement call unifier")
expected_bound_unifier = compact_code("""can Memory.Allocate, Abort.Panic, Global{Read,Write}:
declared_type_id: u32 = annotation_type_id(declared_type, table) can Global{Read,Write}
bound_type_is_reference_free: mutable bool = false
can Memory.Allocate, Abort.Panic, Global{Read,Write}:
    bound_type_is_reference_free <- bam_type_is_proven_reference_free_cached(declared_type_id, reference_sites, table) if declared_type_id != 0
if declared_type_id != 0 and not type_marker_present_here(declared_type, TokenKind.Ampersand):
    bound_visited: mutable dict[u32, bool] = {}
    if bam_type_has_no_direct_reference(declared_type_id, bound_visited, reference_sites, table):
        bound_type_is_reference_free <- true
        classes.copy_safe.push(name)
        classes.copy_values.push(name)
bound_type_id: u32 = declared_type_id
bound_type_is_host_handle: bool = sts_type_is_llvm_handle(bound_type_id, table)
if not bound_type_is_reference_free and not bound_type_is_host_handle:
    bound_names: mutable darray[sview] = []
    bound_names.push(name) if name != ""
    sts_collect_names_except(value, bound_names, classes.copy_safe, classes.copy_values)
    sts_unify_all(classes, bound_names)
sts_unify_calls(value, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)""")
if compact_code(bound_unifier_source) != expected_bound_unifier:
    raise SystemExit("store-through binding union must be skipped only for proven reference-free types while preserving call summaries")
for fallback_child in ("sts_collect_names(expression, hidden_names)", "sts_unify_all(classes, hidden_names)"):
    if not direct_child(unifier_source, "_:", fallback_child, 2):
        raise SystemExit(f"store-through wildcard fallback is missing {fallback_child}")
    mutated = wrap_direct_child_block(unifier_source, "_:", fallback_child, 2)
    if mutated == unifier_source or direct_child(mutated, "_:", fallback_child, 2):
        raise SystemExit("store-through fallback child mutation did not disable its source route")

helper_body = compact_code(function_section(effect_text, "effect_runtime_children"))
expected_helper = compact_code("""children: mutable darray[Expr] = []
for candidate in candidates |children|:
    children.extend(candidate.captures)
children.extend(arguments)
return children""")
if helper_body != expected_helper:
    raise SystemExit("static-effect child projection no longer includes captures and arguments")

positive_names = set(theorem_routes)
negative_names = {"match_guard_name_is_dropped", "dictionary_key_name_is_dropped", "contract_call_is_dropped", "nested_callee_call_is_ignored", "static_effect_candidate_is_ignored", "ambiguous_owned_view_is_assumed_safe", "overload_store_row_is_ignored", "method_receiver_is_ignored", "indirect_call_is_assumed_safe", "named_arguments_are_treated_as_positional", "callable_field_is_assumed_ufcs", "scalar_target_is_assumed_reference"}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    names = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if names != expected:
        raise SystemExit(f"{path.name} theorem inventory changed")
validate_theorem_routes(
    collect_source,
    effect_text,
    holder_text,
    holder_walk_expressions,
    holder_walk_statements,
    positive_text,
    statement_collect_source,
    unifier_source,
)
if "children.extend(candidate.captures)" not in helper_body or "children.extend(arguments)" not in helper_body:
    raise SystemExit("static-effect proof inputs are not tied to helper children")

if tuple(sorted(explicit_match_arm_names(holder_scan_statements, "match statement:", "Stmt."))) != tuple(sorted(EXPECTED_STMT_NAMES)):
    raise SystemExit("holder-view local scanner is not exhaustive over Stmt")
if tuple(sorted(explicit_match_arm_names(holder_scan_expressions, "match expression:", "Expr."))) != tuple(sorted(EXPECTED_EXPR_NAMES)):
    raise SystemExit("holder-view local scanner is not exhaustive over Expr")
if tuple(sorted(explicit_match_arm_names(holder_walk_expressions, "match expression:", "Expr."))) != tuple(sorted(EXPECTED_EXPR_NAMES)):
    raise SystemExit("holder-view diagnostic walk is not exhaustive over Expr")
if tuple(sorted(explicit_match_arm_names(holder_walk_statements, "match statement:", "Stmt."))) != tuple(sorted(EXPECTED_STMT_NAMES)):
    raise SystemExit("holder-view diagnostic walk is not exhaustive over Stmt")
for source, edges, label in (
    (holder_scan_statements, HOLDER_SCAN_STATEMENT_EDGES, "holder-view local statement scan"),
    (holder_scan_expressions, HOLDER_SCAN_EXPRESSION_EDGES, "holder-view local expression scan"),
    (holder_walk_statements, HOLDER_WALK_STATEMENT_EDGES, "holder-view statement walk"),
    (holder_walk_expressions, HOLDER_WALK_EXPRESSION_EDGES, "holder-view expression walk"),
):
    validate_edge_set(source, edges, label)
validate_edge_set(holder_walk_expressions, CATCH_ARM_PROVENANCE_EDGES, "holder-view catch-arm provenance")
validate_edge_set(function_section(holder_text, "chv_flow_bind_pattern_name"), CATCH_PATTERN_BINDING_EDGES, "holder-view pattern binding direct/contained provenance")
validate_edge_set(function_section(holder_text, "chv_expression_binding_facts"), EXPRESSION_BINDING_FACTS_OR_EDGES, "holder-view disjunction binder provenance")
validate_edge_set(function_section(holder_text, "chv_type_iterable_yields_alias_reference"), TYPE_ALIAS_ITERABLE_COLLISION_EDGES, "holder-view ambiguous iterable alias fallback")
validate_edge_set(holder_walk_statements, PARALLEL_ASSIGNMENT_FLOW_EDGES, "holder-view parallel-assignment provenance")
validate_edge_set(holder_walk_statements, FOR_ITERATOR_VIEW_TAINT_EDGES, "holder-view for-iterator view taint")
validate_edge_set(holder_walk_statements, FOR_ITERATOR_REF_ALIAS_EDGES, "holder-view for-iterator reference alias")
assignment_arm = match_arm_body(holder_walk_statements, "match statement:", "Stmt.Assign(target, operator, assigned_value, assign_pos):")
if assignment_arm is None:
    raise SystemExit("holder-view assignment arm is missing")
validate_ordered_source_lines(assignment_arm, (
    "if parallel_shape:",
    "for parallel_value in parallel_values |table, parallel_owned_views, parallel_alias_refs, parallel_direct_alias_refs, parallel_contained_alias_refs, parallel_yield_alias_refs, parallel_yield_alias_knowns, parallel_scalar_sviews, parallel_yield_scalar_sviews, flow, assigned_value_may_be_owned_view, assigned_value_may_alias_reference, assigned_value_may_direct_alias_reference, assigned_value_may_contain_alias_reference, assigned_value_may_yield_alias_reference, assigned_value_yield_alias_reference_known| -> table:",
    "table <- chv_walk_expression(parallel_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)",
    "value_may_be_owned_view: bool = flow.last_value_may_be_owned_view",
    "parallel_owned_views.push(value_may_be_owned_view)",
    "assigned_value_may_be_owned_view <- assigned_value_may_be_owned_view or value_may_be_owned_view",
    "else:",
    "table <- chv_walk_expression(assigned_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)",
    "assigned_value_may_be_owned_view <- flow.last_value_may_be_owned_view",
    "chv_flow_bind_expression_binders(assigned_value, ref_params, flow, table)",
    "table <- chv_walk_expression(target, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)",
    "assigned_alias: bool = assigned_value_may_be_owned_view or ((operator != TokenKind.Assign or projection_assignment) and previous_may_owned_view)",
), "holder-view assignment taint order")
for_arm = match_arm_body(holder_walk_statements, "match statement:", "Stmt.For(bind, loop_variables, iterable, loop_body, _):")
if for_arm is None:
    raise SystemExit("holder-view for arm is missing")
validate_for_iterator_direct_routes(for_arm, holder_walk_statements, "holder-view for-iterator routes")
validate_ordered_source_lines(for_arm, (
    "table <- chv_walk_expression(iterable, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)",
    "iterable_may_be_owned_view: bool = chv_iterable_element_may_be_owned_view(iterable, flow, view_names, view_values, flow.last_value_may_be_owned_view, 0)",
    "iterable_may_alias_reference: bool = chv_expression_may_alias_ref(iterable, ref_params, flow, table, 0)",
    "loop_element_may_alias_reference: bool = chv_iterable_element_may_alias_reference(iterable, ref_params, flow, table, 0)",
    "loop_element_may_contain_alias_reference: bool = chv_iterable_element_may_contain_alias_ref(iterable, ref_params, flow, table, 0)",
    "loop_variable_may_alias_reference: bool = loop_element_may_alias_reference or (bind == \"mutable\" and iterable_may_alias_reference)",
    "branch_mark: usize = flow.names.count",
    "loop_flow: mutable CHVViewFlow = chv_flow_clone(flow)",
    "for loop_variable_index in 0..<loop_variables.count |loop_flow, loop_variables|:",
    "element_facts: (known: bool, may_owned_view: bool, may_alias_reference: bool, may_contain_alias_reference: bool, may_be_scalar_sview: bool, may_yield_scalar_sview: bool) = chv_iterable_binding_facts(iterable, loop_variable_index, loop_variables.count > 1, ref_params, flow, table, view_names, view_values)",
    "loop_variable: sview = loop_variables[loop_variable_index]",
    "loop_variable_may_be_owned_view: bool = element_facts.may_owned_view if element_facts.known else iterable_may_be_owned_view",
    "loop_variable_may_alias_reference: mutable bool = element_facts.may_alias_reference if element_facts.known else loop_element_may_alias_reference",
    "loop_variable_may_alias_reference <- loop_variable_may_alias_reference or (bind == \"mutable\" and iterable_may_alias_reference)",
    "loop_variable_may_contain_alias_reference: bool = element_facts.may_contain_alias_reference if element_facts.known else loop_element_may_contain_alias_reference",
    "chv_flow_bind(loop_flow, loop_variable, false, loop_variable_may_be_owned_view, loop_variable_may_alias_reference)",
    "loop_flow.may_contain_alias_reference[loop_index] <- loop_variable_may_contain_alias_reference if loop_index < loop_flow.names.count",
    "table <- chv_walk_statements(loop_body, in_region, ref_params, binders, owned, view_names, view_values, loop_flow, summary, table)",
    "chv_flow_merge(flow, loop_flow, branch_mark)",
), "holder-view for-iterator taint order")
validate_edge_set(holder_walk_expressions, BINARY_OPERATOR_FALLBACK_EDGES, "holder-view binary operator fallback")
validate_edge_set(function_section(holder_text, "chv_binary_operator_has_non_runtime_target"), (BINARY_NON_RUNTIME_TARGET_EDGES[0],), "holder-view non-runtime binary target classification")
validate_edge_set(holder_walk_expressions, ARRAY_VIEW_TAINT_EDGES, "holder-view array and tuple taint")
validate_edge_set(holder_walk_expressions, DICT_VIEW_TAINT_EDGES, "holder-view dictionary taint")
validate_edge_set(holder_walk_expressions, COMPREHENSION_VIEW_TAINT_EDGES, "holder-view comprehension result taint")
validate_edge_set(holder_walk_expressions, COMPREHENSION_BINDER_VIEW_TAINT_EDGES, "holder-view comprehension binder taint")
validate_edge_set(function_section(holder_text, "chv_is_owned_view"), IDENTIFIER_VIEW_TAINT_EDGES, "holder-view identifier taint lookup")
validate_edge_set(holder_walk_expressions, CONSTRUCT_VIEW_TAINT_EDGES, "holder-view constructed aggregate taint")
validate_edge_set(holder_walk_expressions, RECORD_UPDATE_VIEW_TAINT_EDGES, "holder-view record-update taint")
validate_edge_set(holder_walk_statements, ASSIGN_VIEW_TAINT_EDGES, "holder-view assigned aggregate taint")
validate_edge_set(function_section(holder_text, "chv_is_owned_view"), METHOD_CALL_VIEW_RESULT_EDGES, "holder-view method-call result taint")
validate_edge_set(function_section(holder_text, "chv_is_owned_view"), CALLABLE_VIEW_RESULT_EDGES, "holder-view callable result taint")
validate_edge_set(holder_walk_expressions, CALL_RESULT_VIEW_TAINT_EDGES, "holder-view call result taint")
validate_edge_set(holder_walk_expressions, STATIC_EFFECT_RESULT_VIEW_TAINT_EDGES, "holder-view static-effect result taint")
validate_edge_set(function_section(holder_text, "chv_place_root"), PLACE_ROOT_PROJECTION_EDGES, "holder-view projected assignment roots")
if compact("chv_flow_bind(flow, assigned_root, false, assigned_alias, assigned_alias_ref)") not in compact_code(holder_walk_statements):
    raise SystemExit("new projected assignment roots must join the view/reference flow")

effect_call_source = function_section(holder_text, "chv_check_static_effect_call")
validate_edge_set(effect_call_source, EFFECT_CANDIDATE_EDGES, "static-effect holder-call check")
validate_edge_set(effect_call_source, NAMED_ARGUMENT_STATIC_EFFECT_EDGES, "named-argument static-effect fallback")
validate_edge_set(unifier_source, NAMED_ARGUMENT_UNIFIER_EDGES, "named-argument store-through fallback")
reference_alias_source = function_section(holder_text, "chv_expression_may_alias_ref")
validate_edge_set(reference_alias_source, REF_ALIAS_HELPER_EDGES, "reference-alias expression classification")
validate_edge_set(function_section(holder_text, "chv_is_owned_view"), VIEW_ALIAS_BINARY_EDGES, "holder-view binary result classification")
validate_edge_set(function_section(holder_text, "chv_flow_set_merge"), REF_ALIAS_FLOW_MERGE_EDGES, "reference-alias branch join")
validate_edge_set(function_section(holder_text, "chv_check_call_target"), SUMMARY_CALL_EDGES, "summary-call reference target check")
scalar_reference_fallback = match_arm_body(reference_alias_source, "match argument:", "_:")
expected_scalar_reference_fallback = compact_code("""root: sview = chv_place_root(exclusivity_strip_address(argument).place)
if root == "":
    return false
index: usize = chv_flow_latest(flow, root)
if index < flow.names.count:
    return flow.may_alias_reference[index] or flow.may_contain_alias_reference[index]
return any reference_parameter in ref_params where reference_parameter == root""")
if scalar_reference_fallback is None or compact_code(scalar_reference_fallback) != expected_scalar_reference_fallback:
    raise SystemExit("scalar/non-place targets must not be treated as caller-reference aliases")
if "inner(id_holder(out), owned_view)" not in positive_text or "local_holder.slot" not in positive_text:
    raise SystemExit("reference alias proof must document call-result and projection cases")
if "&local_holder" not in positive_text:
    raise SystemExit("reference alias proof must document the local address-of control")
unary_alias_arm = match_arm_body(reference_alias_source, "match argument:", "Expr.Unary(operator, operand, _):")
if unary_alias_arm is None or compact_code(unary_alias_arm) != compact_code("return false if operator == TokenKind.Not\nreturn chv_expression_may_alias_ref(operand, ref_params, flow, table, depth + 1)"):
    raise SystemExit("logical Not must clear reference provenance while other unary operators retain it")
named_argument_detector = function_section(holder_text, "chv_call_has_named_arguments")
if compact_code(named_argument_detector) != compact_code("can Abort.Panic:\n    return any argument_name in argument_names where argument_name != \"\""):
    raise SystemExit("holder-view named-argument detection must recognize every nonempty label")
if compact("not chv_call_has_named_arguments(argument_names)") not in compact_code(function_section(holder_text, "chv_check_named_call")):
    raise SystemExit("holder-view named calls must bypass positional summary lookup")
if "chv_call_has_named_arguments(argument_names)" not in compact_code(effect_call_source):
    raise SystemExit("static-effect named calls must use the conservative unknown-call fallback")
callee_dispatch_source = function_section(holder_text, "chv_check_named_callee")
validate_edge_set(callee_dispatch_source, CALLEE_DISPATCH_EDGES, "holder-view callee dispatch")
validate_edge_set(function_section(holder_text, "chv_check_named_call"), NAMED_CALL_EDGES, "holder-view named-call resolution")
validate_edge_set(function_section(holder_text, "chv_check_unknown_call"), UNKNOWN_CALL_EDGES, "holder-view indirect-call fallback")
validate_edge_set(holder_walk_expressions, INDEX_OPERATOR_EDGES, "holder-view overloaded index fallback")
validate_edge_set(holder_walk_expressions, UNARY_NEGATION_EDGES, "holder-view unary negation fallback")
validate_edge_set(holder_walk_expressions, BINARY_VIEW_WALK_EDGES, "holder-view binary result provenance")
validate_edge_set(holder_walk_expressions, BINARY_RIGHT_VIEW_EDGES, "holder-view binary RHS provenance")
validate_edge_set(holder_walk_expressions, (BINARY_BOOLEAN_RESULT_EDGES[0], BINARY_BOOLEAN_RESULT_EDGES[3]), "holder-view boolean-result taint flow")
validate_edge_set(function_section(holder_text, "chv_binary_operator_returns_bool"), BINARY_BOOLEAN_RESULT_EDGES[1:3], "holder-view boolean operator classification")
validate_edge_set(function_section(holder_text, "chv_is_reinterpret_target_marker"), REINTERPRET_TARGET_MARKER_EDGES, "reinterpret target marker classification")
validate_edge_set(function_section(holder_text, "chv_is_owned_view"), INDEX_VIEW_RESULT_EDGES, "holder-view index result provenance")
owned_view_source = function_section(holder_text, "chv_is_owned_view")
validate_edge_set(owned_view_source, INDEXN_VIEW_RESULT_EDGES, "holder-view multi-index result provenance")
indexn_view_result_arm = match_arm_body(owned_view_source, "match argument:", "Expr.IndexN(object, arguments, _):")
expected_indexn_view_result_arm = compact_code("""# IndexN represents multi-index selection or generic application. Unlike
# single-key Index, it does not lower through the __index__ protocol, so
# selector/type arguments cannot become the returned view's storage.
return chv_is_owned_view(object, flow, depth + 1)""")
if indexn_view_result_arm is None or compact_code(indexn_view_result_arm) != expected_indexn_view_result_arm:
    raise SystemExit("IndexN result provenance must exclude selector and type argument taint")
validate_edge_set(holder_walk_expressions, INDEXN_VIEW_WALK_EDGES, "holder-view multi-index walk result provenance")
indexn_walk_arm = match_arm_body(holder_walk_expressions, "match expression:", "Expr.IndexN(object, arguments, _):")
expected_indexn_walk_arm = compact_code("""table <- chv_walk_expression(object, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)
object_may_be_owned_view: bool = flow.last_value_may_be_owned_view
if not index_receiver_is_type_application(object):
    for argument in arguments |table|:
        table <- chv_walk_expression(argument, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)
flow.last_value_may_be_owned_view <- object_may_be_owned_view or chv_is_owned_view(expression, flow, 0)""")
if indexn_walk_arm is None or compact_code(indexn_walk_arm) != expected_indexn_walk_arm:
    raise SystemExit("IndexN selectors must be visited without unknown-call dispatch or selector result taint")
call_callee_source = function_section(holder_text, "chv_walk_call_callee")
indexn_call_callee_arm = match_arm_body(call_callee_source, "match callee:", "Expr.IndexN(head, arguments, _):")
expected_indexn_call_callee_arm = compact_code("""table <- chv_walk_call_callee(head, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, receiver_owned_view, receiver_may_alias_reference, callee_may_be_owned_view, table)
head_may_be_owned_view: bool = callee_may_be_owned_view or chv_is_owned_view(head, flow, 0)
callee_may_be_owned_view <- head_may_be_owned_view
callee_value_may_be_owned_view: bool = callee_may_be_owned_view
flow.last_value_may_be_owned_view <- callee_value_may_be_owned_view""")
if indexn_call_callee_arm is None or compact_code(indexn_call_callee_arm) != expected_indexn_call_callee_arm:
    raise SystemExit("IndexN call-callee type arguments must not be walked or treated as runtime result provenance")
validate_edge_set(function_section(holder_text, "chv_is_owned_view"), UNARY_VIEW_RESULT_EDGES, "holder-view unary result provenance")

if "if owned.count > 0" in compact_code(function_section(holder_text, "chv_walk_declarations")):
    raise SystemExit("holder-view walk must visit reference functions to reach nested lambda scopes")
holder_entry_source = function_section(holder_text, "check_call_holder_view_store")
if "returnifsummary.writable_function.count==0" in compact_code(holder_entry_source):
    raise SystemExit("unknown-call holder checks must run even when no named callee summary rows exist")
holder_summary_setup = compact("summary: mutable StoreThroughSummary = chv_build_summary(file.top_decls, holders, reference_sites, table) can Global{Read,Write}")
holder_walk_setup = compact("table <- chv_walk_declarations(file.top_decls, summary, file.enum_annotations, table)")
if holder_summary_setup not in compact_code(holder_entry_source) or holder_walk_setup not in compact_code(holder_entry_source) or compact_code(holder_entry_source).find(holder_walk_setup) < compact_code(holder_entry_source).find(holder_summary_setup):
    raise SystemExit("holder-view call walk is no longer reached after summary construction")
holder_summary_source = function_section(holder_text, "chv_build_summary")
if "sts_declared_once" in compact_code(holder_summary_source):
    raise SystemExit("holder-view summaries must union every same-name overload body")
validate_edge_set(holder_summary_source, OVERLOAD_SUMMARY_EDGES, "holder-view overload summary")
validate_edge_set(function_section(holder_text, "chv_check_named_callee"), FIELD_UNKNOWN_CALL_EDGES, "callable field conservative fallback")
field_dispatch = function_section(holder_text, "chv_check_named_callee")
field_arm = match_arm_body(field_dispatch, "match callee:", "Expr.Field(receiver, method, _):")
method_proof = function_section(holder_text, "chv_has_direct_method_summary")
required_method_guards = (
    "return false if any binder in binders where binder == method",
    "return false if chv_flow_latest(flow, method) < flow.names.count",
    "return false if any field in table.struct_field_name where field == method",
    "return false if not source_type_found or not function_found",
    "interned_name(formal_type, table) == owner",
)
if field_arm is None or "chv_check_named_call" in compact_code(field_arm) or any(compact(guard) not in compact_code(method_proof) for guard in required_method_guards):
    raise SystemExit("field calls must require an unambiguous source method before summary dispatch")
if compact("comprehension_ref_params.push(outer_ref) if outer_ref != variable") not in compact_code(holder_walk_expressions):
    raise SystemExit("comprehension scope no longer masks a same-named outer reference parameter")
if compact("comprehension_binders.push(variable)") not in compact_code(holder_walk_expressions):
    raise SystemExit("comprehension scope no longer records its lexical binder")
owned_view_source = function_section(holder_text, "chv_is_owned_view")
validate_edge_set(owned_view_source, FIELD_PROJECTION_VIEW_TAINT_EDGES, "holder-view aggregate field projection")
field_projection_arm = match_arm_body(owned_view_source, "match argument:", "Expr.Field(_, _, _):")
expected_field_projection_arm = compact_code("""root_name: sview = chv_place_root(argument)
index: usize = chv_flow_latest(flow, root_name) if root_name != \"\" else flow.names.count
return index < flow.names.count and flow.may_owned_view[index]""")
if field_projection_arm is None or compact_code(field_projection_arm) != expected_field_projection_arm:
    raise SystemExit("aggregate field projections must inherit view taint from their root binding")
if "constCHV_DIAGNOSTIC_ARGUMENT_NUMBER_BASE:usize=1" not in compact_code(holder_text):
    raise SystemExit("holder-view diagnostic argument numbering must use a named constant")
if "ifdepth>" in compact_code(owned_view_source) or "ifdepth>" in compact_code(function_section(holder_text, "chv_expression_may_alias_ref")):
    raise SystemExit("AST nesting alone must not manufacture owned-view or reference provenance")
if "ifdepth>" in compact_code(function_section(holder_text, "chv_call_method_info")):
    raise SystemExit("transparent callee nesting must preserve view-producing method identity")
if "flow.may_owned_view[index]" not in compact_code(owned_view_source):
    raise SystemExit("holder-view alias lookup must read the latest flow binding")
if "flow.owned[index]orflow.may_owned_view[index]" not in compact_code(owned_view_source):
    raise SystemExit("view conversions and slices must inherit view provenance from alias roots")

negative_parameters = {
    "match_guard_name_is_dropped": "guard_has_name",
    "dictionary_key_name_is_dropped": "key_has_name",
    "contract_call_is_dropped": "call_is_present",
    "nested_callee_call_is_ignored": "callee_call_is_present",
    "static_effect_candidate_is_ignored": "candidate_call_is_present",
    "ambiguous_owned_view_is_assumed_safe": "view_binding_may_be_owned",
    "overload_store_row_is_ignored": "overload_body_has_store",
    "method_receiver_is_ignored": "receiver_store_is_present",
    "indirect_call_is_assumed_safe": "reference_and_view_are_present",
    "named_arguments_are_treated_as_positional": "named_argument_is_present",
    "callable_field_is_assumed_ufcs": "ufcs_candidate_is_missing",
    "scalar_target_is_assumed_reference": "scalar_target_is_present",
}
for name, parameter in negative_parameters.items():
    body = compact_code(function_section(negative_text, name))
    expected = compact_code(f"requires {parameter}\nensure result == false\nreturn {parameter}")
    if body != expected:
        raise SystemExit(f"{name} no longer expresses its rejected dropped-child claim")

if args.source_only:
    print(json.dumps({
        "source_bound": True,
        "positive_theorems": len(positive_names),
        "negative_controls": len(negative_names),
        "source_closure_files": len(source_include_closure([POSITIVE, NEGATIVE])),
    }, sort_keys=True))
    raise SystemExit(0)

if not __debug__:
    raise SystemExit("run without Python -O")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("store-through AST proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE])
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    *(HERE / name for name in ("store_walk_inspection.py", "store_walk_collection_edges.py", "store_walk_holder_traversal_edges.py", "store_walk_view_flow_edges.py", "store_walk_theorem_routes.py", "store_walk_theorem_checks.py")),
    SEMANTIC_ROOT, *SUMMARY_PARTS, *HOLDER_PARTS,
    AST_NODES, AST_SIDE_TABLES, EFFECT_SHAPE, POSITIVE, NEGATIVE, *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == len(positive_names)
assert not positive["findings"]
assert positive_names <= {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive == run(POSITIVE)[1], "store-through proof report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] == negative["summary"]["proven"] + negative["summary"]["failed"]
assert negative["summary"]["failed"] == len(negative_names)
assert negative["summary"]["proven"] == 0
assert negative["replay"]["certificates"] == negative["replay"]["replayed"] == negative["summary"]["failed"]
assert negative["replay"]["gaps"] == 0
assert not negative["trust"]["trusted_assumptions"]
assert not negative["findings"]
assert negative_names <= {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert negative == run(NEGATIVE)[1], "store-through negative report changed across identical runs"

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof or source inputs changed during replay"
