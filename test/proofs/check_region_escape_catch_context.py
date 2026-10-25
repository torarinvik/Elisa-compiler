"""Bind RegionEscape catch classification to complete parser marker identity."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def function_source(path: Path, name: str) -> str:
    source = path.read_text()
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound RegionEscape helper {name} in {path.relative_to(ROOT)}")
    return match.group(0)


types = (ROOT / "src/semantic/semantic_types_symbol_table.elisa").read_text()
if "struct RegionEscapeCatchContext:" not in types:
    raise SystemExit("RegionEscape catch context type is missing")
if "markers: darray[Ast::EnumAnnotation]" not in types or "lexical_module: sview @source" not in types:
    raise SystemExit("RegionEscape catch context dropped parser marker rows or lexical module")

catchable = ROOT / "src/semantic/region_escape_provenance/catchable_raises.elisa"
marker_match = function_source(catchable, "region_escape_catch_marker_matches")
for identity in (
    'marker.owner == "__catch_match"',
    'marker.name == "__catch_match"',
    "marker.line == position.line",
    "marker.offset == position.offset",
    "marker.module == context.lexical_module",
):
    if identity not in marker_match:
        raise SystemExit(f"RegionEscape marker predicate omits identity component {identity}")

expression_termination = function_source(catchable, "region_escape_provenance_expression_terminates_with_metadata")
if "region_escape_provenance_statements_terminate_with_metadata(statements, catch_context)" not in expression_termination:
    raise SystemExit("nested block termination drops RegionEscape catch context")
if "region_escape_provenance_catchable_raise_with_metadata(guarded, catch_context)" not in expression_termination:
    raise SystemExit("Catch expression termination drops RegionEscape catch context")

match_termination = function_source(catchable, "region_escape_provenance_match_arms_terminate_with_metadata")
if "not guard_terminates and not body_terminates" not in match_termination or "region_escape_provenance_match_arm_reachable(scrutinee, arms, arm_index)" not in match_termination:
    raise SystemExit("Match termination still requires a body after a terminating guard")

catch_termination = function_source(catchable, "region_escape_provenance_catch_error_arms_terminate_with_metadata")
if "guard_terminates: bool = region_escape_provenance_expression_terminates_with_metadata(arm.guard, catch_context)" not in catch_termination or "not guard_terminates and not body_terminates" not in catch_termination or "region_escape_provenance_catch_arm_reachable(arms, arm_index)" not in catch_termination:
    raise SystemExit("Catch error-arm termination ignores terminating guards")

statement_termination = function_source(catchable, "region_escape_provenance_statement_terminates_with_metadata")
if "region_escape_catch_marker_matches(line, catch_context)" not in statement_termination:
    raise SystemExit("statement termination no longer checks complete catch-marker identity")
if "region_escape_provenance_match_arms_terminate_with_metadata(scrutinee, arms, catch_context)" not in statement_termination:
    raise SystemExit("ordinary Match termination drops nested RegionEscape catch context")

break_search = function_source(catchable, "region_escape_provenance_statement_has_break_for_loop")
if "scrutinee_aborts and (not is_catch_match or not scrutinee_may_raise)" not in break_search:
    raise SystemExit("loop break search treats arms after an aborting Match scrutinee as reachable")
if "reachable <- false if is_catch_match and scrutinee_aborts and arm_index == 0" not in break_search:
    raise SystemExit("loop break search counts the success arm of an aborting statement Catch")

body_flow = function_source(
    ROOT / "src/semantic/region_escape_provenance/body_flow.elisa",
    "region_escape_body_apply_statements_with_elements_flow",
)
if "region_escape_catch_marker_matches(match_line, catch_context)" not in body_flow:
    raise SystemExit("element body-flow Match classification is not marker-bound")
if "region_escape_provenance_expression_terminates_with_metadata(scrutinee, catch_context)" not in body_flow:
    raise SystemExit("element body-flow termination drops nested catch metadata")

summary = function_source(
    ROOT / "src/semantic/region_escape_provenance.elisa",
    "region_escape_provenance_catchable_raise_statement_summary",
)
if "region_escape_catch_marker_matches(match_line, catch_context)" not in summary:
    raise SystemExit("catchable-raise summary is not marker-bound")
if "region_escape_provenance_statement_terminates_with_metadata(statement, catch_context)" not in summary:
    raise SystemExit("catchable-raise summary dropped context-aware statement termination")

provenance = ROOT / "src/semantic/region_escape_provenance.elisa"
stored_value = function_source(provenance, "stored_value_region")
if "region_escape_provenance_statements_terminate_with_metadata(block_statements, catch_context)" not in stored_value:
    raise SystemExit("stored-value blocks drop RegionEscape catch context")
if "region_escape_provenance_statements_terminate_with_metadata(arm.body, catch_context)" not in stored_value:
    raise SystemExit("stored-value Match/Catch arms drop RegionEscape catch context")
if "region_escape_provenance_match_arm_reachable(scrutinee, arms, arm_index)" not in stored_value or "region_escape_provenance_catch_arm_reachable(arms, arm_index)" not in stored_value:
    raise SystemExit("stored-value Match/Catch arms include unreachable branches")

effective_value = function_source(provenance, "effective_value_region")
if "region_escape_body_value_region(block_statements, block_value" not in effective_value or "line, catch_context)" not in effective_value:
    raise SystemExit("effective value-region blocks drop RegionEscape catch context")
if effective_value.count("region_escape_value_arms_region_with_elements(") < 2:
    raise SystemExit("effective value-region Match/Catch fallback omits arm reachability or taint flow")

value_arms_flow = function_source(
    ROOT / "src/semantic/region_escape_provenance/body_flow.elisa",
    "region_escape_value_arms_region_with_elements",
)
if not re.search(r"region_escape_record_collection_element_mutation\(arm\.guard,[^\n]*, line, catch_context\)", value_arms_flow):
    raise SystemExit("effective value-arm guard mutation scan drops RegionEscape catch context")

stored_region = function_source(
    ROOT / "src/semantic/region_escape_provenance/stored_regions.elisa",
    "region_escape_stored_or_call_region",
)
if "effective_value_region(value, annotations, view_fns, nesting, taint_names, taint_regions, line, catch_context)" not in stored_region:
    raise SystemExit("stored-call fallback drops RegionEscape catch context")

region_escape_sources = [
    ROOT / "src/semantic/check_region_escape.elisa",
    ROOT / "src/semantic/check_region_escape/element_taints.elisa",
    ROOT / "src/semantic/check_region_escape/walk_recovery.elisa",
    ROOT / "src/semantic/region_escape_assignments.elisa",
    ROOT / "src/semantic/region_escape_provenance.elisa",
    ROOT / "src/semantic/region_escape_provenance/body_flow.elisa",
    ROOT / "src/semantic/region_escape_provenance/catchable_raises.elisa",
    ROOT / "src/semantic/region_escape_provenance/stored_regions.elisa",
    ROOT / "src/semantic/region_escape_stores.elisa",
]
for path in region_escape_sources:
    source = path.read_text()
    if "catch_match_lines" in source or "[catch_line for catch_line in catch_context]" in source:
        raise SystemExit(f"legacy line-only Catch context remains in {path.relative_to(ROOT)}")
    if re.search(r"any\s+catch_line\s+in\s+catch_context\s+where\s+catch_line\s*==", source):
        raise SystemExit(f"line-only Catch classification remains in {path.relative_to(ROOT)}")

store_check = function_source(
    ROOT / "src/semantic/region_escape_stores.elisa",
    "region_escape_check_store",
)
if "region_escape_catch_context(table)" not in store_check:
    raise SystemExit("RegionEscape store checks do not construct marker context from the symbol table")
if "table.catch_context" in store_check:
    raise SystemExit("RegionEscape store checks read a nonexistent table catch-context field")

atom = (ROOT / "test/atoms/catch_marker_identity.elisa").read_text()
for probe in (
    "return 17 if region_escape_catch_marker_matches(at, region_context)",
    "return 18 if not region_escape_catch_marker_matches(at, region_context)",
    "return 19 if not region_escape_provenance_expression_terminates_with_metadata(nested_catch_block, region_context)",
    "return 20 if region_escape_provenance_expression_terminates_with_metadata(nested_catch_block, region_context)",
    "return 24 if not region_escape_provenance_expression_terminates_with_metadata(aborting_guard_catch, region_context)",
    "return 29 if not region_escape_provenance_expression_terminates_with_metadata(aborting_guard_match, region_context)",
    "return 31 if not region_escape_provenance_expression_terminates_with_metadata(exhaustive_bool_match, region_context)",
    "wrong_owner_region: sview @source = effective_value_region(nested_catch_value_block",
    'return 22 if wrong_owner_region != ""',
    "right_owner_region: sview @source = effective_value_region(nested_catch_value_block",
    'return 23 if right_owner_region != "inner"',
    "stored_literal_match_region: sview @source = stored_value_region(literal_match_value",
    'return 25 if stored_literal_match_region != "outer"',
    "effective_literal_match_region: sview @source = effective_value_region(literal_match_value",
    'return 26 if effective_literal_match_region != "outer"',
    "stored_literal_catch_region: sview @source = stored_value_region(literal_catch_value",
    'return 27 if stored_literal_catch_region != "outer"',
    "effective_literal_catch_region: sview @source = effective_value_region(literal_catch_value",
    'return 28 if effective_literal_catch_region != "outer"',
    "guard_mutation_condition: Ast::Expr = Ast::Expr.Block([Ast::Stmt.Match(raise_call, catch_shape_arms, at)], Ast::Expr.BoolLit(true, at), [], at)",
    "guard_mutation_value: Ast::Expr = Ast::Expr.If(guard_mutation_condition, guard_push, Ast::Expr.IntLit(0, at), at)",
    "return 35 if guarded_mutation_region != \"inner\"",
    "region_escape_body_apply_statements_with_elements(statement_guard_body, region_annotations, region_view_fns, region_container_fns, region_nesting, statement_guard_names, statement_guard_regions, statement_guard_element_names, statement_guard_element_regions, region_context)",
    'return 50 if region_escape_element_taint_lookup(statement_guard_element_names, statement_guard_element_regions, "xs") != "inner"',
    "catch_array: Ast::Expr = Ast::Expr.Array([nested_catch_value_block], at)",
    'return 51 if region_escape_element_taint_lookup(catch_array_element_names, catch_array_element_regions, "items") != "inner"',
):
    if probe not in atom:
        raise SystemExit(f"catch marker identity atom is missing RegionEscape probe {probe}")

loop_atom = (ROOT / "test/atoms/region_loop_tail.elisa").read_text()
if "return 21 if aborting_match_value.found" not in loop_atom:
    raise SystemExit("loop tail atom is missing the aborting-Match break reachability control")

body_flow_path = ROOT / "src/semantic/region_escape_provenance/body_flow.elisa"
body_flow = function_source(body_flow_path, "region_escape_body_apply_statements_with_elements_flow")
if not re.search(r"region_escape_comprehension_element_region\(value,[^\n]*statement_line\.line, catch_context\)", body_flow):
    raise SystemExit("RegionEscape variable-declaration element lookup drops catch context")
if not re.search(r"region_escape_comprehension_element_region\(iterable,[^\n]*line\.line, catch_context\)", body_flow):
    raise SystemExit("RegionEscape loop element lookup drops catch context")
if not re.search(r"region_escape_record_collection_element_mutation\(arm\.guard,[^\n]*match_line\.line, catch_context\)", body_flow):
    raise SystemExit("statement-Match arm guard mutation drops its RegionEscape catch context")
element_taints = function_source(ROOT / "src/semantic/check_region_escape/element_taints.elisa", "region_escape_comprehension_element_region")
if len(re.findall(r"region_escape_stored_or_call_region_with_elements\(element,[^\n]*element_taint_regions, line, catch_context\)", element_taints)) != 2:
    raise SystemExit("RegionEscape array/tuple/set element lookup drops catch context")

print("RegionEscape catch identity source binding passed")
