"""Linear consumption must use the exact visible overload and argument mapping."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
FLOW = (ROOT / "src/semantic/check_affine_use_linear_flow.elisa").read_text()
WALK = (ROOT / "src/semantic/check_affine_use_linear.elisa").read_text()
FIXTURE = (ROOT / "test/repro/affine_typestate_postcondition_overload_owner.elisa").read_text()
SMOKE = (ROOT / "test/parity/affine_typestate_postcondition_overload_owner_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^\s*def {re.escape(name)}\(.*?(?=^\s*def |^\s*public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


candidate_count = function_source(FLOW, "affine_call_candidate_count")
argument_map = function_source(FLOW, "affine_call_argument_map")
argument_exact = function_source(FLOW, "affine_call_argument_is_exact")
declaration_generic = function_source(FLOW, "affine_call_declaration_is_generic")
type_ids_exact = function_source(FLOW, "affine_call_type_ids_are_exact")
type_pattern_match = function_source(FLOW, "affine_call_type_pattern_may_match")
structured_match = function_source(FLOW, "affine_call_structured_argument_may_match")
qualified_type_id = function_source(FLOW, "affine_call_type_expression_type_id")
argument_type_id = function_source(FLOW, "affine_call_argument_type_id")
type_alias_application = function_source(FLOW, "affine_call_type_alias_application_id")
canonical_actual_type = function_source(FLOW, "affine_call_canonical_actual_type_id_with_alias_substitution")
canonical_actual_wrapper = function_source(FLOW, "affine_call_canonical_actual_type_id")
alias_row_at = function_source(FLOW, "affine_call_type_alias_row_at")
non_alias_nominal = function_source(FLOW, "affine_call_non_alias_nominal_in_module")
import_annotations_before = function_source(FLOW, "affine_call_import_annotations_before_call")
alias_formal_names = function_source(FLOW, "affine_call_alias_formal_names")
alias_type_substitution = function_source(FLOW, "affine_call_substitute_alias_type_args")
nominal_owner_qualification = function_source(FLOW, "affine_call_type_id_qualify_nominal_owners")
nominal_identity = function_source(FLOW, "affine_call_nominal_identity")
parameter_match = function_source(FLOW, "affine_call_argument_can_match")
extern_argument_map = function_source(FLOW, "affine_extern_call_argument_map")
resolve_alias = function_source(FLOW, "affine_call_resolve_type_alias")
type_expression_scope = function_source(FLOW, "affine_call_type_expression_has_scope")
type_path = function_source(FLOW, "affine_call_type_path")
type_alias_row = function_source(FLOW, "affine_call_type_alias_row")
argument_match = function_source(FLOW, "affine_call_argument_can_match_name")
argument_infer = function_source(FLOW, "affine_call_argument_infer_type")
local_type = function_source(FLOW, "affine_call_local_type")
match_binder_fixture = function_source(FIXTURE, "match_binder_does_not_inherit_outer_type")
last_function_fixture = function_source(FIXTURE, "seed_last_function_local_type")
use_walk = function_source(FLOW, "check_affine_uses")
symbol_visible = function_source(FLOW, "affine_callable_symbol_visible")
lookup_module = function_source(FLOW, "affine_call_lookup_module")
lookup_imported_module = function_source(FLOW, "affine_call_lookup_imported_module")
qualifier_path = function_source(FLOW, "affine_call_qualifier_path")
lookup_qualified_module = function_source(FLOW, "affine_call_lookup_qualified_module")
call_postcondition = function_source(FLOW, "affine_call_postcondition_argument_index")
call_walk = function_source(WALK, "walk_affine_statements")
statement_value_walk = function_source(WALK, "walk_affine_statement_value")
loop_walk = function_source(WALK, "walk_affine_loop_body")
loop_iterable_type = function_source(FLOW, "affine_call_loop_iterable_type_id")
loop_variable_type_ids = function_source(FLOW, "affine_call_loop_variable_type_ids")
qualified_return_type_id = function_source(FLOW, "affine_call_qualified_return_type_id")
unqualified_return_type_id = function_source(FLOW, "affine_call_unqualified_return_type_id")
unique_field_type_id = function_source(FLOW, "affine_call_unique_field_type_id")
unique_nominal_owner = function_source(FLOW, "affine_call_unique_nominal_owner")
unique_nominal_names = function_source(FLOW, "affine_call_type_id_has_unique_nominal_names")
field_type_id = function_source(FLOW, "affine_call_field_type_id")
projection_has_call = function_source(FLOW, "affine_call_projection_has_call")

if "Expr.Scope(_, _, _)" not in type_expression_scope or \
        "affine_call_type_expression_has_scope(parameter_type)" not in structured_match or \
        "return false if formal_id == 0" not in structured_match or \
        "return true if formal_id == 0" not in structured_match:
    raise SystemExit("unresolved qualified formals must fail closed instead of acting as wildcard candidates")

if "affine_call_argument_map(params, line" not in candidate_count or \
        "affine_extern_call_argument_map(param_start, arity" not in candidate_count or \
        "mapped.exact" not in candidate_count or \
        "not affine_call_declaration_is_generic" not in candidate_count or \
        "can Memory.Allocate, Abort.Panic, Global{Read,Write}" not in candidate_count or \
        "exact_only" not in candidate_count or \
        "affine_call_candidate_count(file.top_decls" not in call_postcondition or \
        "if candidates == 0" not in call_postcondition or \
        "postcondition.function_offset == selected_offset" not in call_postcondition or \
        "postcondition.line == selected_line" not in call_postcondition or \
        "marker.owner == \"__arg_forward\"" not in call_postcondition or \
        "can Memory.Allocate, Abort.Panic, Global{Read,Write}" not in call_postcondition or \
        "candidates != 1" not in call_postcondition:
    raise SystemExit("affine postcondition calls must identify one compatible declaration by exact source position")
if "argument_names[argument_index] != \"\"" not in argument_map or \
        "parameters[parameter_index].name == argument_names[argument_index]" not in argument_map or \
        "(accepted: bool, argument_index: usize, exact: bool)" not in argument_map or \
        "affine_call_argument_is_exact(arguments[argument_index]" not in argument_map or \
        "can Memory.Allocate, Abort.Panic, Global{Read,Write}" not in argument_map or \
        "affine_call_type_ids_are_exact(canonical_formal, canonical_actual" not in argument_exact or \
        "affine_call_canonical_actual_type_id(formal_id, declaration_module, declaration_line, declaration_line, annotations" not in argument_exact or \
        "affine_call_canonical_actual_type_id(actual_id, current_module, call_pos, caller_line, annotations" not in argument_exact or \
        "function_generic_param_named(table, declaration_line.line, declaration_line.offset, expected_path)" not in argument_exact or \
        "table.generic_param_owner_offsets[row] == offset" not in declaration_generic or \
        "original_formal_kind == SemTypeKind.Named and function_generic_param_named" not in type_pattern_match or \
        "if formal_id == 0:" not in type_pattern_match or \
        "return false if type_id_contains_function_generic(actual_id, caller_line.line, caller_line.offset, table)" not in type_pattern_match or \
        "actual_has_caller_generic: bool = type_id_contains_function_generic(actual_id, caller_line.line, caller_line.offset, table)" not in type_pattern_match or \
        "return false if original_formal_kind != SemTypeKind.Unknown and type_id_contains_function_generic(actual_id, caller_line.line, caller_line.offset, table)" not in type_pattern_match or \
        "if actual_kind == SemTypeKind.Named and function_generic_param_named(table, caller_line.line, caller_line.offset, interned_name(actual_id, table))" not in type_pattern_match or \
        "affine_call_type_ids_equal_as_generic_actuals(generic_actuals[generic_index], generic_canonical_actual, current_module, caller_line" not in type_pattern_match or \
        "not affine_call_type_id_has_unique_nominal_names_for_generic_owner(generic_canonical_actual, current_module, caller_line" not in type_pattern_match or \
        "generic_names.push(generic_name)" not in type_pattern_match or \
        "return false if actual_has_caller_generic" not in type_pattern_match or \
        "if actual_kind == SemTypeKind.Named and function_generic_param_named(table, caller_line.line, caller_line.offset, interned_name(actual_id, table))" not in type_pattern_match or \
        "region_formals.push(formal_id)" not in type_pattern_match or \
        "region_actuals[region_index] == actual_id" not in type_pattern_match or \
        "affine_call_type_expression_type_id(parameter_type, declaration_module, declaration_line, declaration_line, annotations, 0, table)" not in structured_match or \
        "affine_call_type_alias_row_at(type_path, module, use_pos, annotations, table)" not in qualified_type_id or \
        "affine_call_type_id_qualify_nominal_owners(canonical_target, alias_declaration.module_owner" not in qualified_type_id or \
        "Expr.Paren(inner, _)" not in qualified_type_id or \
        "Expr.Refinement(base, _, _)" not in qualified_type_id or \
        "operator == TokenKind.Mutable or operator == TokenKind.Lmut or operator == TokenKind.Static or operator == TokenKind.Heap or operator == TokenKind.Stack or operator == TokenKind.Tail" not in qualified_type_id or \
        "operator == TokenKind.Question or operator == TokenKind.Ampersand" not in qualified_type_id or \
        "binding_module_alias_row_before(first_component, requester, table)" not in qualified_type_id or \
        "binding_nominal_alias_target_owner(path_module, requester, table)" not in qualified_type_id or \
        "affine_call_nominal_identity_in_module(type_name, candidate_module, table)" not in qualified_type_id or \
        "identity <- affine_call_nominal_identity_in_module(type_name, path_module, table) if not identity.found" not in qualified_type_id or \
        "return 0 if canonical_module == \"\"" not in qualified_type_id or \
        "affine_call_non_alias_nominal_in_module(alias_name, candidate_module, table)" not in alias_row_at or \
        "return AFFINE_TYPE_ALIAS_ROW_AMBIGUOUS if canonical_module == \"\"" not in alias_row_at or \
        "concrete_nominal: bool = symbol.kind == SymbolKind.Struct or symbol.kind == SymbolKind.Enum" not in non_alias_nominal or \
        "affine_call_type_expression_type_id(type_expression, current_module, construct_pos, function_line, annotations, 0, table)" not in argument_type_id or \
        "Expr.Construct(type_expression, _, construct_pos) | Expr.RecordUpdate(type_expression, _, construct_pos)" not in argument_type_id or \
        "Expr.Tuple(elements, _)" not in qualified_type_id or \
        "element_handles.extend(elements)" not in qualified_type_id or \
        "intern_type(SemTypeKind.Tuple, \"tuple\", element_ids, table)" not in qualified_type_id or \
        "Expr.Index(indexed_head, index_argument, _)" not in qualified_type_id or \
        "Expr.IndexN(indexed_head, index_arguments, _)" not in qualified_type_id or \
        "affine_call_type_alias_application_id(alias_row, alias_arguments" not in qualified_type_id or \
        "affine_call_type_expression_type_id(alias_declaration.target, alias_declaration.module_owner" not in type_alias_application or \
        "affine_call_canonical_actual_type_id_with_alias_substitution(target_id, alias_declaration.module_owner, alias_declaration.pos, no_generic_owner, annotations, alias_formals.names, alias_actuals" not in type_alias_application or \
        "affine_call_type_expression_type_id(parameter_type, declaration_module, declaration_line, declaration_line, annotations, 0, table)" not in argument_exact or \
        "affine_call_canonical_actual_type_id(formal_id, declaration_module, declaration_line, declaration_line, annotations" not in type_pattern_match or \
        "affine_call_nominal_identity(formal_name, declaration_module, table)" not in type_pattern_match or \
        "affine_call_canonical_actual_type_id(actual_id, current_module, call_pos, caller_line, annotations" not in type_pattern_match or \
        "if canonical_argument_id == 0:" not in type_pattern_match or \
        "original_formal_kind == SemTypeKind.Region or type_id_contains_region(formal_id, table)" not in type_pattern_match or \
        "type_id_contains_region(formal_id, table)" not in type_pattern_match or \
        "interned_elem_count(formal_id, table) != interned_elem_count(actual_id, table)" not in type_pattern_match or \
        "annotation_type_id(alias_declaration.target, table)" not in canonical_actual_type or \
        "affine_call_type_alias_row_at(type_name, module, call_pos, annotations, table)" not in canonical_actual_type or \
        "table.type_row_region_ids[region_row] == 0" not in canonical_actual_type or \
        "affine_call_alias_formal_names(table.type_alias_name[alias_row.usize()], alias_declaration.pos, annotations)" not in canonical_actual_type or \
        "alias_formals: darray[sview @source]&" not in canonical_actual_type or \
        "alias_actuals: darray[u32]&" not in canonical_actual_type or \
        "alias_actuals[formal_index] if alias_formals[formal_index] == type_name" not in canonical_actual_type or \
        "affine_call_canonical_actual_type_id_with_alias_substitution(alias_target_id, alias_declaration.module_owner, alias_declaration.pos, no_generic_owner, annotations, nested_alias_formals.names, nested_alias_actuals" not in canonical_actual_type or \
        "affine_call_canonical_actual_type_id_with_alias_substitution(type_id, module, call_pos, generic_owner, annotations, empty_alias_formals, empty_alias_actuals" not in canonical_actual_wrapper or \
        "affine_call_type_id_qualify_nominal_owners(alias_argument_id, module" not in canonical_actual_type or \
        "affine_call_type_id_qualify_nominal_owners(canonical_target, alias_declaration.module_owner" not in canonical_actual_type or \
        "affine_call_import_annotations_before_call(table.possible_import_annotations, use_pos)" not in alias_row_at or \
        "errorset_import_scope(annotations, candidate_module, alias_name, module" not in alias_row_at or \
        "annotation.owner != \"__alias_param\"" not in alias_formal_names or \
        "formal_names.push(annotation.name)" not in alias_formal_names or \
        "formal_names[formal_index] == type_name" not in alias_type_substitution or \
        "definition_identity.module == \"\"" not in nominal_owner_qualification or \
        "return type_id if kind == SemTypeKind.Named and function_generic_param_named(table, generic_owner.line, generic_owner.offset, type_name)" not in nominal_owner_qualification or \
        "if kind == SemTypeKind.Region" not in nominal_owner_qualification or \
        "affine_call_nominal_identity_in_module(qualified_name, qualified_module, table)" not in nominal_identity or \
        "typestate_import_row(annotation)" not in import_annotations_before or \
        "errorset_import_precedes_call(annotation, call_position.line, call_position.offset" not in import_annotations_before or \
        "generic_names, generic_actuals" not in structured_match or \
        "return false if formal_id == 0 and type_id_contains_function_generic(actual_id, caller_line.line, caller_line.offset, table)" not in structured_match or \
        "return true if formal_id == 0" not in structured_match or \
        "affine_call_nominal_identity(formal_name, declaration_module, table)" not in type_ids_exact or \
        "affine_call_type_path(parameter_type, table)" not in parameter_match or \
        "affine_call_argument_can_match(arguments[argument_index], parameters[slot].type_expression, declaration_module, function_line, current_module, caller_line, call_pos, generic_names, generic_actuals, region_formals, region_actuals, annotations, local_names, local_types, local_type_ids, table)" not in argument_map or \
        "generic_names: mutable darray[sview @source]" not in argument_map or \
        "affine_call_argument_can_match_name(arguments[argument_index], parameters[parameter_slot].type_name, declaration_module, function_line, current_module, caller_line, annotations, local_names, local_types, local_type_ids, table)" not in extern_argument_map or \
        "affine_call_argument_infer_type(argument, current_module, caller_line, annotations, local_names, local_types, local_type_ids, table)" not in argument_match or \
        "stage0_value_spelling(inferred)" not in local_type or \
        "table: mutable SymbolTable&" not in local_type or \
        "can Memory.Allocate, Abort.Panic, Global{Read,Write}" not in local_type or \
        "return \"\" if scoped_type_id != 0" not in local_type or \
        "type_id_contains_function_generic(scoped_type_id" not in local_type or \
        "type_id_contains_region(scoped_type_id" in local_type or \
        "function_generic_param_named(table, function_line.line, function_line.offset, declared_name)" not in local_type or \
        "affine_call_resolve_type_alias(declared_name, current_module, declaration_pos, annotations, table)" not in local_type or \
        "affine_call_type_path(type_expression, table)" not in local_type or \
        "param_local_type: sview = affine_call_local_type(param.type_expression" not in use_walk or \
        "affine_call_type_expression_type_id(param.type_expression, current_module, line, line, file.enum_annotations, 0, table)" not in use_walk or \
        "local_type_ids.push(param_type_id)" not in use_walk or \
        "type_id_contains_region(param_type_id, table)" in use_walk or \
        "local_type_ids.push(param_type_id)" not in use_walk or \
        "local_types.push(local_type)" not in call_walk or \
        "local_type_ids.push(local_type_id)" not in call_walk or \
        "affine_call_type_expression_type_id(type_expression, current_module, line, function_line, file.enum_annotations, 0, table)" not in call_walk or \
        "affine_call_local_type(type_expression, value, names, local_types, local_type_ids, current_module, file.enum_annotations, function_line, line, table)" not in call_walk or \
        "else affine_call_argument_type_id(value, current_module, function_line, file.enum_annotations, names, local_types, local_type_ids, table)" not in call_walk or \
        "affine_call_local_type((Ast::Expr.Absent), value, names, local_types, local_type_ids, current_module, file.enum_annotations, function_line, line, table)" not in call_walk or \
        "assign_local_type_id: mutable u32 = affine_call_argument_type_id(value, current_module, function_line, file.enum_annotations, names, local_types, local_type_ids, table)" not in call_walk or \
        "type_id_contains_region(local_type_id, table)" in call_walk or \
        "local_types.push(assign_local_type)" not in call_walk or \
        "local_types.push(\"__firm_scope_binder__\")" not in call_walk or \
        "local_type_ids.push(assign_local_type_id)" not in call_walk or \
        "for statement in statements |names, local_types, local_type_ids, flags" not in call_walk or \
        "names.truncate(then_names_mark)" not in call_walk or \
        "local_types.truncate(then_types_mark)" not in call_walk or \
        "local_type_ids.truncate(then_types_mark)" not in call_walk or \
        "flags.truncate(then_flags_mark)" not in call_walk or \
        "names.truncate(else_names_mark)" not in call_walk or \
        "local_types.truncate(else_types_mark)" not in call_walk or \
        "local_type_ids.truncate(else_types_mark)" not in call_walk or \
        "flags.truncate(else_flags_mark)" not in call_walk or \
        "names.truncate(arm_names_mark)" not in call_walk or \
        "local_types.truncate(arm_types_mark)" not in call_walk or \
        "local_type_ids.truncate(arm_types_mark)" not in call_walk or \
        "flags.truncate(arm_flags_mark)" not in call_walk or \
        "names.truncate(block_names_mark)" not in call_walk or \
        "local_types.truncate(block_types_mark)" not in call_walk or \
        "local_type_ids.truncate(block_types_mark)" not in call_walk or \
        "flags.truncate(block_flags_mark)" not in call_walk or \
        "names.truncate(while_names_mark)" not in call_walk or \
        "local_types.truncate(while_types_mark)" not in call_walk or \
        "local_type_ids.truncate(while_types_mark)" not in call_walk or \
        "flags.truncate(while_flags_mark)" not in call_walk or \
        "names.truncate(value_names_mark)" not in statement_value_walk or \
        "local_types.truncate(value_types_mark)" not in statement_value_walk or \
        "local_type_ids.truncate(value_types_mark)" not in statement_value_walk or \
        "flags.truncate(value_flags_mark)" not in statement_value_walk or \
        "names.truncate(recovery_names_mark)" not in statement_value_walk or \
        "local_types.truncate(recovery_types_mark)" not in statement_value_walk or \
        "local_type_ids.truncate(recovery_types_mark)" not in statement_value_walk or \
        "flags.truncate(recovery_flags_mark)" not in statement_value_walk or \
        "names.truncate(outer_count)" not in loop_walk or \
        "local_types.truncate(outer_count)" not in loop_walk or \
        "local_type_ids.truncate(outer_count)" not in loop_walk or \
        "flags.truncate(outer_count)" not in loop_walk or \
        "collect_linear_locals(body, linear_names, table, loop_local_names, loop_local_lines)" not in loop_walk or \
        "affine_call_loop_variable_type_ids(loop_iterable, current_module, function_line, file.enum_annotations, loop_variables.count, names, local_type_ids, table)" not in loop_walk or \
        "local_types.push(loop_types[loop_variable_index])" not in loop_walk or \
        "local_type_ids.push(loop_type_ids[loop_variable_index])" not in loop_walk or \
        "affine_call_add_unknown_pattern_binders(arm.pattern, names, local_types, local_type_ids, flags)" not in call_walk or \
        "gather_truthy_condition_bindings(condition, table, then_bindings)" not in call_walk or \
        "gather_truthy_condition_bindings(condition, table, while_bindings)" not in call_walk or \
        "parameters[parameter_slot].name == argument_names[argument_index]" not in extern_argument_map or \
        "parameters[parameter_slot].type_name" not in extern_argument_map or \
        "function_generic_param_named(table, declaration_line.line, declaration_line.offset, expected_name)" not in argument_match or \
        "affine_call_resolve_type_alias(expected_name, declaration_module, declaration_line, annotations, table)" not in argument_match or \
        "binding_module_alias_row_before(first_component, requester, table)" not in resolve_alias or \
        "binding_nominal_alias_target_owner(path_module, requester, table)" not in resolve_alias or \
        "while module_scope != \"\" |module_scope, selected_row, path_module, alias_name, declaration_module, table|" not in resolve_alias or \
        "candidate_module: sview = affine_call_module_path_join(module_scope, path_module, table)" not in resolve_alias or \
        "selected_row <- affine_call_type_alias_row(alias_name, path_module, table)" not in resolve_alias or \
        "errorset_import_scope(annotations, candidate_module, alias_name, declaration_module, declaration_pos.line, declaration_pos.offset, true)" not in resolve_alias or \
        "affine_call_import_annotations_before_call(table.possible_import_annotations, declaration_pos)" not in resolve_alias or \
        "typestate_possible_import_may_select(alias_name, declaration_module, possible_imports)" not in resolve_alias or \
        "table.type_alias_declarations[selected_row.usize()]" not in resolve_alias or \
        "affine_call_resolve_type_alias(target_path, alias_declaration.module_owner, alias_declaration.pos, annotations, table, depth + 1)" not in resolve_alias or \
        "Expr.Scope(base, name, _)" not in type_path or \
        "operator == TokenKind.Mutable" not in type_path or \
        "TokenKind.Ampersand" in type_path or \
        "TokenKind.Lmut" in type_path or \
        "table.type_alias_declarations[alias_index].module_owner != module" not in type_alias_row or \
        "literal_never_fits(literal_kind, resolved_name)" not in argument_match or \
        "firm_never_fits(actual_family, resolved_name)" not in argument_match or \
        "return true if actual.kind == SemTypeKind.Unknown" not in argument_match:
    raise SystemExit("overload viability must map named arguments and reject only known type mismatches")
if "return local_type_ids[name_index]" not in loop_iterable_type or \
        "return global_type_id_of(iterable_name, table)" not in loop_iterable_type or \
        "return 0 if any local_name in names where local_name == function_name" not in loop_iterable_type or \
        "affine_call_unqualified_return_type_id(function_name, current_module, annotations, table)" not in loop_iterable_type or \
        "Expr.Scope(qualifier, qualified_function_name, _)" not in loop_iterable_type or \
        "affine_call_qualified_return_type_id(qualifier, qualified_function_name, current_module, annotations, table)" not in loop_iterable_type or \
        "callable_qualified_module_matches_candidate" not in lookup_qualified_module or \
        "can Memory.Allocate, Abort.Panic" not in lookup_qualified_module or \
        "can Memory.Allocate, Abort.Panic" not in qualified_return_type_id or \
        "affine_call_lookup_qualified_module(table, annotations, function_name, qualifier, lexical_module, selected_module)" not in qualified_return_type_id or \
        "callable_function_declaration_visible(annotations, function_name, symbol.module_owner, symbol.line, symbol.offset, lexical_module)" not in qualified_return_type_id or \
        "symbol.module_owner == selected_module" not in qualified_return_type_id or \
        "symbol_chain_head(table, function_name)" not in qualified_return_type_id or \
        "table.symbol_name_next[cursor.usize()]" not in qualified_return_type_id or \
        "declarations > 1" not in qualified_return_type_id or \
        "selected_return_id <- symbol.return_type_id" not in qualified_return_type_id or \
        "return selected_return_id if declarations == 1" not in qualified_return_type_id or \
        "type_id_contains_function_generic(selected_return_id" not in qualified_return_type_id or \
        "type_id_contains_region(selected_return_id" not in qualified_return_type_id or \
        "affine_call_lookup_module(table, annotations, function_name, lexical_module, selected_module)" not in unqualified_return_type_id or \
        "symbol.module_owner == selected_module" not in unqualified_return_type_id or \
        "callable_function_declaration_visible(annotations, function_name, symbol.module_owner, symbol.line, symbol.offset, lexical_module)" not in unqualified_return_type_id or \
        "symbol_chain_head(table, function_name)" not in unqualified_return_type_id or \
        "table.symbol_name_next[cursor.usize()]" not in unqualified_return_type_id or \
        "declarations > 1" not in unqualified_return_type_id or \
        "selected_return_id <- symbol.return_type_id" not in unqualified_return_type_id or \
        "return selected_return_id if declarations == 1" not in unqualified_return_type_id or \
        "type_id_contains_function_generic(selected_return_id" not in unqualified_return_type_id or \
        "type_id_contains_region(selected_return_id" not in unqualified_return_type_id or \
        "structural_type_id_of(iterable, names, local_types, table)" in loop_variable_type_ids or \
        "indexed_element_type_id(iterable_id, table)" not in loop_variable_type_ids or \
        "indexed_element_type_id(affine_call_loop_iterable_type_id(object" not in loop_iterable_type or \
        "affine_call_field_type_id(object, interned_name(object_id, table), field_name, current_module, table)" not in loop_iterable_type or \
        "affine_call_field_type_id(object, interned_name(object_id, table), field_name, current_module, table)" not in argument_infer or \
        "affine_call_unique_field_type_id(owner, field_name, table)" not in field_type_id or \
        "field_type_id_of_in_module(table, owner, field_name, current_module)" not in field_type_id or \
        "affine_call_projection_has_call(object)" not in field_type_id or \
        "affine_call_unique_nominal_owner(owner, table)" not in unique_field_type_id or \
        "module_owner != symbol.module_owner" not in unique_nominal_owner or \
        "affine_call_type_id_has_unique_nominal_names(candidate_id, table)" not in unique_field_type_id or \
        "affine_call_unique_nominal_owner(type_name, table)" not in unique_nominal_names or \
        "affine_call_nominal_identity(type_name, \"\", table).found" not in unique_nominal_names or \
        "symbol.kind == SymbolKind.Extern and symbol.opaque_extern_type" not in unique_nominal_owner or \
        "found_id != candidate_id" not in unique_field_type_id or \
        "Expr.Call(_, _, _, _)" not in projection_has_call:
    raise SystemExit("loop element types must use the current function's scoped TypeIds, not resolve-types scratch locals")
if "spelling == \"__firm_scope_binder__\"" not in argument_infer or \
        "local_type_ids[local_index]" not in argument_infer or \
        "Expr.Tuple(_, _)" not in argument_infer or \
        "SemTypeKind.Tuple" not in argument_infer or \
        "Expr.GetElse(guarded, _, _)" not in argument_infer or \
        "interned_elem(guarded_id, 0, table)" not in argument_infer or \
        "Expr.Slice(object, _, _, _)" not in argument_infer or \
        "receiver_type.kind == SemTypeKind.String" not in argument_infer or \
        "pointer_step and left_type.kind == SemTypeKind.Unknown and right_type.kind == SemTypeKind.Int" not in argument_infer or \
        "structural_type_id_of" in argument_infer or \
        "infer_expression_type" in argument_infer or \
        "local_names, local_types, local_type_ids, table" not in argument_map or \
        "local_names, local_types, local_type_ids, table" not in extern_argument_map or \
        "call_line, caller_line, names, local_types, local_type_ids, true, selected_line" not in call_postcondition or \
        "call_line, caller_line, names, local_types, local_type_ids, false, selected_line" not in call_postcondition:
    raise SystemExit("affine argument viability must use scoped locals and keep unknown binders out of stale TypeId scratch")
if "symbol.line != declaration_line" not in symbol_visible or \
        "symbol.offset != declaration_offset" not in symbol_visible or \
        "symbol_chain_head(table, function_name)" not in lookup_module or \
        "table.symbol_name_next[cursor.usize()]" not in lookup_module or \
        "callable_function_declaration_visible" not in lookup_module or \
        "selected_module <- module_scope" not in lookup_module or \
        "module_scope <- try_noncall_module_parent(module_scope)" not in lookup_module or \
        "symbol_chain_head(table, function_name)" not in lookup_qualified_module or \
        "table.symbol_name_next[cursor.usize()]" not in lookup_qualified_module or \
        "affine_call_lookup_imported_module(table, annotations, function_name, lexical_module, selected_module)" not in lookup_module or \
        "symbol_chain_head(table, function_name)" not in lookup_imported_module or \
        "table.symbol_name_next[cursor.usize()]" not in lookup_imported_module or \
        "callable_first_wildcard_imported_row" not in lookup_imported_module or \
        "callable_program_selective_import_row_visible" not in lookup_imported_module or \
        "candidate_modules.count != 1" not in lookup_imported_module or \
        "intern_joined_text(bytes, table)" not in qualifier_path or \
        "callable_qualified_module_matches_candidate" not in lookup_qualified_module or \
        "affine_call_function_name(consume_callee)" not in call_walk or \
        "affine_call_postcondition_argument_index(current_module, file, consume_callee" not in call_walk or \
        "affine_root(consume_args[argument_index])" not in call_walk:
    raise SystemExit("consumption must follow the exact visible callable and mapped actual argument")
if FIXTURE.count("#line 0 affine-postcondition-call-owner.elisa") != 89 or \
        "def consume(ticket: Ticket[Fresh], mode: bool) -> void ensures ticket => Used:" not in FIXTURE or \
        "def consume(ticket: Ticket[Fresh], mode: i64) -> void:" not in FIXTURE or \
        "type BoolMode = bool" not in FIXTURE or \
        "type TextMode = string" not in FIXTURE or \
        "struct T:\n    value: i64" not in FIXTURE or \
        "type Boxed[Elem] = darray[Elem]" not in FIXTURE or \
        "type BoxedWithOwner[Elem] = Pair[T, Elem]" not in FIXTURE or \
        "def consume_boxed_generic[Elem](ticket: Ticket[Fresh], value: Boxed[Elem]) -> void ensures ticket => Used:" not in FIXTURE or \
        "def consume_boxed_generic(ticket: Ticket[Fresh], value: Boxed[T]) -> void:" not in FIXTURE or \
        "def generic_boxed_actual_preserves_owner[T](value: Boxed[T]) -> void:" not in FIXTURE or \
        "consume_boxed_generic(generic_boxed_ticket, value)" not in FIXTURE or \
        "def generic_provider_box_actual[T](value: ImportedProvider::BoxedWithOwner[T]) -> void:" not in FIXTURE or \
        "consume_provider_box(generic_provider_box_ticket, value)" not in FIXTURE or \
        "def concrete_provider_box_actual(value: ImportedProvider::BoxedWithOwner[bool]) -> void:" not in FIXTURE or \
        "redeem(concrete_provider_box_ticket)" not in FIXTURE or \
        "def consume_nominal_t(ticket: Ticket[Fresh], value: T) -> void ensures ticket => Used:" not in FIXTURE or \
        "def generic_actual_does_not_select_nominal[T](value: T) -> void:" not in FIXTURE or \
        "consume_nominal_t(generic_nominal_ticket, value)" not in FIXTURE or \
        "def consume_bool_alias(ticket: Ticket[Fresh], mode: BoolMode) -> void ensures ticket => Used:" not in FIXTURE or \
        "def consume_text_alias(ticket: Ticket[Fresh], mode: TextMode) -> void:" not in FIXTURE or \
        "def consume_generic[T](ticket: Ticket[Fresh], mode: T) -> void ensures ticket => Used:" not in FIXTURE or \
        "def exact_bool_overload_shadows_generic_postcondition() -> void:" not in FIXTURE or \
        "consume_generic(generic_ticket, true)" not in FIXTURE or \
        "module Other:" not in FIXTURE or \
        "module OtherSibling:" not in FIXTURE or \
        "def bool_value() -> i64:" not in FIXTURE or \
        "struct Item:\n    mode: i64" not in FIXTURE or \
        "struct Item:\n        mode: bool" not in FIXTURE or \
        "def make_item() -> Item:" not in FIXTURE or \
        "return Item{mode: true}" not in FIXTURE or \
        "def consume_field_owner(ticket: Ticket[Fresh], mode: bool) -> void:" not in FIXTURE or \
        "def consume_field_owner(ticket: Ticket[Fresh], mode: i64) -> void ensures ticket => Used:" not in FIXTURE or \
        "consume(ticket, true)" not in FIXTURE or "consume(ticket, 1)" not in FIXTURE or \
        "def selects_local_bool_postcondition() -> void:" not in FIXTURE or \
        "mode: bool = true" not in FIXTURE or "consume(ticket, mode)" not in FIXTURE or \
        "def branch_local_bool_does_not_escape() -> void:" not in FIXTURE or \
        "mode: i64 = 1" not in FIXTURE or "mode: bool = true" not in FIXTURE or \
        "def match_binder_does_not_inherit_outer_type(holder: Holder) -> void:" not in match_binder_fixture or \
        "enum Holder:" not in FIXTURE or \
        "Flags(values: darray[i64])" not in FIXTURE or \
        "Holder.Flags(mode):" not in match_binder_fixture or \
        "consume(match_ticket, mode[0])" not in match_binder_fixture or \
        "mode: bool" in match_binder_fixture or \
        "def selects_loop_bool_postcondition() -> void:" not in FIXTURE or \
        "modes: darray[bool] = [true]" not in FIXTURE or "for mode in modes:" not in FIXTURE or \
        "def loop_i64_does_not_use_stale_bool_type() -> void:" not in FIXTURE or \
        "modes: darray[i64] = [1]" not in FIXTURE or \
        "def make_items() -> darray[bool]:" not in FIXTURE or \
        "def local_callable_does_not_use_global_iterable_return(make_items: fn() -> darray[i64]) -> void:" not in FIXTURE or \
        "for mode in make_items():" not in FIXTURE or \
        "def loop_branch_local_is_not_outer() -> void:" not in FIXTURE or \
        "branch_ticket: Ticket[Fresh] = Ticket.new(id: 1)" not in FIXTURE or \
        "from ImportedProvider import imported_finish" not in FIXTURE or \
        "using ImportedProvider as ImportedAlias" not in FIXTURE or \
        "module AffineAliasTypes:\n    type Mode = bool" not in FIXTURE or \
        "from AffineAliasTypes import Mode" not in FIXTURE or \
        "using AffineAliasTypes as AffineAlias" not in FIXTURE or \
        "def consume_qualified_type_alias(ticket: Ticket[Fresh], mode: AffineAliasTypes::Mode) -> void ensures ticket => Used:" not in FIXTURE or \
        "def consume_imported_type_alias(ticket: Ticket[Fresh], mode: Mode) -> void ensures ticket => Used:" not in FIXTURE or \
        "def consume_module_alias_type(ticket: Ticket[Fresh], mode: AffineAlias::Mode) -> void ensures ticket => Used:" not in FIXTURE or \
        "mode: AffineAliasTypes::Mode = true" not in FIXTURE or \
        "mode: Mode = true" not in FIXTURE or \
        "mode: AffineAlias::Mode = true" not in FIXTURE or \
        "consume_qualified_type_alias(qualified_type_alias_ticket, mode)" not in FIXTURE or \
        "consume_imported_type_alias(imported_type_alias_ticket, mode)" not in FIXTURE or \
        "consume_module_alias_type(module_alias_type_ticket, mode)" not in FIXTURE or \
        "imported_finish(ticket, true)" not in FIXTURE or \
        "ImportedAlias::imported_finish(ticket, true)" not in FIXTURE or \
        "mode: darray[bool] = [true]" not in last_function_fixture or \
        "modes: darray[bool]" in last_function_fixture or \
        "consume_bool_alias(ticket, true)" not in FIXTURE or \
        "consume_text_alias(ticket, true)" not in FIXTURE or \
        "consume_generic(ticket, 1)" not in FIXTURE or \
        "def consume_array(ticket: Ticket[Fresh], values: darray[i64]) -> void ensures ticket => Used:" not in FIXTURE or \
        "def consume_array(ticket: Ticket[Fresh], values: darray[bool]) -> void:" not in FIXTURE or \
        "def structured_argument_selects_postcondition() -> void:" not in FIXTURE or \
        "consume_array(structured_ticket, values)" not in FIXTURE or \
        "type Items[Elem] = darray[Elem]" not in FIXTURE or \
        "from ImportedProvider import Items" not in FIXTURE or \
        "def consume_imported_structural_alias(ticket: Ticket[Fresh], values: Items[bool]) -> void ensures ticket => Used:" not in FIXTURE or \
        "def consume_imported_structural_alias[T](ticket: Ticket[Fresh], values: T) -> void:" not in FIXTURE or \
        "consume_imported_structural_alias(imported_structural_alias_ticket, values)" not in FIXTURE or \
        "module ImportedNominal:" not in FIXTURE or \
        "type ImportedFoo = Foo" not in FIXTURE or \
        "from ImportedNominal import ImportedFoo" not in FIXTURE or \
        "def consume_imported_nominal_alias(ticket: Ticket[Fresh], value: ImportedFoo) -> void ensures ticket => Used:" not in FIXTURE or \
        "def consume_imported_nominal_alias(ticket: Ticket[Fresh], value: Foo) -> void:" not in FIXTURE or \
        "consume_imported_nominal_alias(imported_nominal_ticket, value)" not in FIXTURE or \
        "def consume_qualified_nominal_alias(ticket: Ticket[Fresh], value: ImportedNominal::ImportedFoo) -> void ensures ticket => Used:" not in FIXTURE or \
        "def qualified_nominal_alias_mismatch_does_not_select(value: Foo) -> void:" not in FIXTURE or \
        "consume_qualified_nominal_alias(qualified_nominal_mismatch_ticket, value)" not in FIXTURE or \
        "def qualified_nominal_alias_selects_postcondition(value: ImportedNominal::ImportedFoo) -> void:" not in FIXTURE or \
        "consume_qualified_nominal_alias(qualified_nominal_match_ticket, value)" not in FIXTURE or \
        "using ImportedNominal as ImportedNominalAlias" not in FIXTURE or \
        "def consume_module_alias_nominal(ticket: Ticket[Fresh], value: ImportedNominalAlias::Foo) -> void ensures ticket => Used:" not in FIXTURE or \
        "def module_alias_nominal_selects_postcondition(value: ImportedNominalAlias::Foo) -> void:" not in FIXTURE or \
        "consume_module_alias_nominal(module_alias_nominal_match_ticket, value)" not in FIXTURE or \
        "def consume_qualified_nominal_pair(ticket: Ticket[Fresh], pair: (ImportedNominal::Foo, i64)) -> void ensures ticket => Used:" not in FIXTURE or \
        "def qualified_nominal_tuple_selects_postcondition(pair: (ImportedNominal::Foo, i64)) -> void:" not in FIXTURE or \
        "consume_qualified_nominal_pair(qualified_nominal_tuple_ticket, pair)" not in FIXTURE or \
        "def consume_qualified_nominal_array(ticket: Ticket[Fresh], values: darray[ImportedNominal::Foo]) -> void ensures ticket => Used:" not in FIXTURE or \
        "def qualified_nominal_array_selects_postcondition(values: darray[ImportedNominal::Foo]) -> void:" not in FIXTURE or \
        "consume_qualified_nominal_array(qualified_nominal_array_ticket, values)" not in FIXTURE or \
        "def consume_qualified_structural_alias(ticket: Ticket[Fresh], values: ImportedProvider::Items[bool]) -> void ensures ticket => Used:" not in FIXTURE or \
        "def qualified_structural_alias_selects_postcondition(values: ImportedProvider::Items[bool]) -> void:" not in FIXTURE or \
        "consume_qualified_structural_alias(qualified_structural_alias_ticket, values)" not in FIXTURE or \
        "type ImportedFooPair = (Foo, i64)" not in FIXTURE or \
        "def consume_qualified_nominal_pair_alias(ticket: Ticket[Fresh], pair: ImportedNominal::ImportedFooPair) -> void ensures ticket => Used:" not in FIXTURE or \
        "def qualified_nominal_pair_alias_selects_postcondition(pair: ImportedNominal::ImportedFooPair) -> void:" not in FIXTURE or \
        "consume_qualified_nominal_pair_alias(qualified_nominal_pair_alias_ticket, pair)" not in FIXTURE or \
        "def consume_qualified_nominal_ref(ticket: Ticket[Fresh], value: ImportedNominal::Foo&) -> void ensures ticket => Used:" not in FIXTURE or \
        "def qualified_nominal_ref_selects_postcondition(value: ImportedNominal::Foo&) -> void:" not in FIXTURE or \
        "consume_qualified_nominal_ref(qualified_nominal_ref_ticket, value)" not in FIXTURE or \
        "def consume_qualified_nominal_optional(ticket: Ticket[Fresh], value: ImportedNominal::Foo?) -> void ensures ticket => Used:" not in FIXTURE or \
        "def qualified_nominal_optional_selects_postcondition(value: ImportedNominal::Foo?) -> void:" not in FIXTURE or \
        "consume_qualified_nominal_optional(qualified_nominal_optional_ticket, value)" not in FIXTURE or \
        "def region_pair_selects_nonconsuming_overload[@a, @b]" not in FIXTURE or \
        "AffineRegionPair[a, b]" not in FIXTURE or \
        "pair_copy = pair" not in FIXTURE or \
        "consume_region_pair(region_pair_ticket, pair_copy)" not in FIXTURE or \
        "def region_pair_same_region_selects_consuming_overload[@r]" not in FIXTURE or \
        "let pair_copy = pair" not in FIXTURE or \
        "consume_region_pair(same_region_ticket, pair_copy)" not in FIXTURE or \
        "consume(mode: true, ticket: ticket)" not in FIXTURE or \
        "Other::consume(ticket, true)" not in FIXTURE:
    raise SystemExit("regression must cover overloads, alias and generic type heads, named arguments, and qualified module calls")
if "module ImportedNoise:\n    def imported_modes() -> darray[i64]:" not in FIXTURE or \
        "module ImportedProvider:\n    struct T:\n        value: i64\n    struct Pair[A, B]:\n        first: A\n        second: B\n    type Items[Elem] = darray[Elem]\n    type Boxed[Elem] = darray[Elem]\n    type BoxedWithOwner[Elem] = Pair[T, Elem]\n    def imported_modes() -> darray[bool]:" not in FIXTURE or \
        "from ImportedProvider import imported_modes" not in FIXTURE or \
        "def selects_imported_bare_return_postcondition() -> void:" not in FIXTURE or \
        "consume(imported_return_ticket, imported_modes()[0])" not in FIXTURE:
    raise SystemExit("bare imported-call inference must use the uniquely visible declaration despite a same-leaf module collision")
if "Other::bool_value()" not in FIXTURE or \
        "module OtherSibling:\n    def bool_value() -> i64:" not in FIXTURE or \
        "Other::make_item().mode" not in FIXTURE or \
        "def qualified_return_field_owner_stays_unknown() -> void:" not in FIXTURE or \
        "consume_field_owner(field_owner_ticket, Other::make_item().mode)" not in FIXTURE or \
        "get mode else return" not in FIXTURE or \
        "pair: (i64, i64)" not in FIXTURE or \
        "consume_pair(pair_ticket, (1, 2))" not in FIXTURE:
    raise SystemExit("scoped inference must preserve firm qualified-call, get-else, and tuple argument types")
if "affine_typestate_postcondition_overload_owner.elisa" not in SMOKE or \
        "indexing requires string, array, view, packed store, or reference type" not in SMOKE or \
        '[[ "$count" -ne 4 ]]' not in SMOKE or \
        'generic_count="$(grep -Fc' not in SMOKE or \
        '[[ "$generic_count" -ne 1 ]]' not in SMOKE or \
        '[[ "$match_count" -ne 1 ]]' not in SMOKE or \
        'linear value "match_ticket" must be consumed before scope exit' not in SMOKE or \
        'linear value "region_pair_ticket" must be consumed before scope exit' not in SMOKE or \
        'for selected_name in qualified_ticket imported_return_ticket get_else_ticket pair_ticket structured_ticket imported_structural_alias_ticket imported_nominal_ticket qualified_nominal_match_ticket module_alias_nominal_match_ticket qualified_nominal_tuple_ticket qualified_nominal_array_ticket qualified_structural_alias_ticket qualified_nominal_pair_alias_ticket qualified_nominal_ref_ticket qualified_nominal_optional_ticket qualified_type_alias_ticket imported_type_alias_ticket module_alias_type_ticket' not in SMOKE or \
        'field_owner_count="$(grep -Fc' not in SMOKE or \
        '[[ "$field_owner_count" -ne 1 ]]' not in SMOKE or \
        '[[ "$loop_count" -ne 1 ]]' not in SMOKE or \
        'boxed_generic_count="$(grep -Fc' not in SMOKE or \
        '[[ "$boxed_generic_count" -ne 0 ]]' not in SMOKE or \
        'nominal_generic_count="$(grep -Fc' not in SMOKE or \
        '[[ "$nominal_generic_count" -ne 1 ]]' not in SMOKE or \
        'generic_boxed_ticket' not in SMOKE or \
        'generic_provider_box_ticket' not in SMOKE or \
        'concrete_provider_box_ticket' not in SMOKE or \
        'generic_nominal_ticket' not in SMOKE or \
        "linear value \"ticket\" must be consumed before scope exit" not in SMOKE:
    raise SystemExit("smoke must keep selected postcondition calls valid and report only the non-consuming sibling")

print("affine typestate call-owner source proof OK")
