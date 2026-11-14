"""Check try-site enclosing-function and position indexes."""
import re


def check_try_enclosing_index(
    MANIFEST,
    POSITION_CONSTANTS,
    ROOT,
    args,
    compact,
    compact_inline,
    constant_definitions,
    contains_contiguous_block,
    first_class_ambiguous_family_fixture,
    first_class_inactive_duplicate_family_fixture,
    function_section,
    line_zero_nonerror_fixture,
    nested_global_alias_fixture,
    positive_text,
    qualified_leaf_fixture,
    source_text,
    try_smoke,
    zero_offset_enclosing_fixture,
):
    if not args.source_only and not MANIFEST.is_file():
        raise SystemExit(f"missing proof build manifest: {MANIFEST}")
    source_constants = constant_definitions(source_text)
    if not source_constants:
        raise SystemExit("could not read production position constants")
    for name, definition in POSITION_CONSTANTS.items():
        if source_constants.get(name) != definition:
            raise SystemExit(f"production try-position constant changed: {name}")
    proof_constants = constant_definitions(positive_text)
    for proof_name, source_name in (
        ("TRY_ENCLOSING_NO_OFFSET", "FALLIBLE_FUNCTION_NO_OFFSET"),
        ("TRY_ENCLOSING_FIRST_POSITION", "FALLIBLE_FUNCTION_FIRST_POSITION"),
        ("TRY_ENCLOSING_POSITION_STEP", "FALLIBLE_FUNCTION_POSITION_STEP"),
        ("TRY_ENCLOSING_BINARY_DIVISOR", "FALLIBLE_FUNCTION_SEARCH_DIVISOR"),
    ):
        if proof_constants.get(proof_name) != source_constants.get(source_name):
            raise SystemExit(f"proof and production try-position constants differ: {proof_name} / {source_name}")

    expected_linear = """
def enclosing_try_function(table: SymbolTable&, try_line: u32, try_offset: u32) -> (line: u32, offset: u32):
    best_line: mutable u32 = FALLIBLE_FUNCTION_NO_LINE
    best_offset_line: mutable u32 = FALLIBLE_FUNCTION_NO_LINE
    best_offset: mutable u32 = 0
    best_offset_found: mutable bool = false
    for symbol in table.symbols |best_line, best_offset_line, best_offset, best_offset_found|:
        if symbol.kind == SymbolKind.Func:
            best_line <- symbol.line if symbol.line <= try_line and symbol.line >= best_line
            if try_offset != FALLIBLE_FUNCTION_NO_OFFSET and symbol.offset != FALLIBLE_FUNCTION_NO_OFFSET and symbol.offset <= try_offset and (not best_offset_found or symbol.offset >= best_offset):
                best_offset <- symbol.offset
                best_offset_line <- symbol.line
                best_offset_found <- true
    return (best_offset_line, best_offset) if best_offset_found
    return (best_line, FALLIBLE_FUNCTION_NO_OFFSET)
"""
    expected_builder = """
def fallible_function_position_index_build(index: mutable FallibleFunctionPositionIndex&, table: SymbolTable&) -> void:
    can Memory.Allocate, Abort.Panic:
        positions: mutable darray[FallibleFunctionPosition] = []
        offsets_ordered: mutable bool = true
        saw_previous: mutable bool = false
        previous_offset: mutable u32 = 0
        for symbol in table.symbols |positions, offsets_ordered, saw_previous, previous_offset|:
            if symbol.kind == SymbolKind.Func and symbol.offset != FALLIBLE_FUNCTION_NO_OFFSET:
                offsets_ordered <- false if saw_previous and symbol.offset < previous_offset
                positions <- positions.push(FallibleFunctionPosition{offset: symbol.offset, line: symbol.line})
                previous_offset <- symbol.offset
                saw_previous <- true
        index.positions <- positions
        index.offsets_ordered <- offsets_ordered
        index.ready <- true
"""
    expected_indexed = """
def enclosing_try_function_indexed(index: mutable FallibleFunctionPositionIndex&, table: SymbolTable&, try_line: u32, try_offset: u32) -> (line: u32, offset: u32):
    can Memory.Allocate, Abort.Panic:
        if not index.ready:
            fallible_function_position_index_build(index, table)
        if try_offset != FALLIBLE_FUNCTION_NO_OFFSET and index.offsets_ordered:
            low: mutable usize = FALLIBLE_FUNCTION_FIRST_POSITION
            high: mutable usize = index.positions.count
            while low < high |low, high, index, try_offset|:
                middle: usize = low + (high - low) / FALLIBLE_FUNCTION_SEARCH_DIVISOR
                if index.positions[middle].offset <= try_offset:
                    low <- middle + FALLIBLE_FUNCTION_POSITION_STEP
                else:
                    high <- middle
            if low > FALLIBLE_FUNCTION_FIRST_POSITION:
                position: FallibleFunctionPosition = index.positions[low - FALLIBLE_FUNCTION_POSITION_STEP]
                return (position.line, position.offset)
        return enclosing_try_function(table, try_line, try_offset)
"""
    for name, expected in (
        ("enclosing_try_function", expected_linear),
        ("fallible_function_position_index_build", expected_builder),
        ("enclosing_try_function_indexed", expected_indexed),
    ):
        if compact(function_section(source_text, name)) != compact(expected):
            raise SystemExit(f"production {name} changed without updating the source-bound proof")

    exact_zero_contracts = {
        "try_enclosing_function_decl_id": (
            "enclosing.offset != FALLIBLE_FUNCTION_NO_OFFSET and symbol.offset != enclosing.offset",
            "matches <- matches + 1.usize()",
        ),
        "try_enclosing_return_occurrence": (
            "function_offset != FALLIBLE_FUNCTION_NO_OFFSET and marker.offset != function_offset",
        ),
        "fallible_function_module_index_add": (
            "annotation.offset != FALLIBLE_FUNCTION_NO_OFFSET",
            "index.by_offset <- index.by_offset.put(annotation.offset.u64(), row)",
            "index.by_line <- index.by_line.put(line_key, CALLABLE_ERROR_ROW_NONE)",
            "index.unknown_offset_by_line",
        ),
        "fallible_fn_module_indexed": (
            "declaration_offset == FALLIBLE_FUNCTION_NO_OFFSET",
            "index.by_offset.get(declaration_offset.u64())",
            "return module_annotations[offset_row.usize()].name if offset_row != CALLABLE_ERROR_ROW_NONE and module_annotations[offset_row.usize()].line == declaration_line",
            "row != CALLABLE_ERROR_ROW_NONE",
        ),
        "fallible_fn_module": (
            "declaration_offset != FALLIBLE_FUNCTION_NO_OFFSET and module_annotation.offset == declaration_offset",
            "fallback_module <- module_annotation.name",
            "return fallback_module if fallback_count == 1.usize()",
        ),
        "fallible_fn_module_known": (
            "module_annotation.offset == declaration_offset",
            "declaration_offset != FALLIBLE_FUNCTION_NO_OFFSET",
            "return fallback_count == 1.usize()",
        ),
        "try_error_set_index_build": (
            "annotation.offset != FALLIBLE_FUNCTION_NO_OFFSET",
            "index.by_offset_heads <- index.by_offset_heads.put(offset_key, row_id)",
            "index.unknown_offset_line_heads",
        ),
        "try_error_set_destinations": (
            "declaration_offset == FALLIBLE_FUNCTION_NO_OFFSET",
            "candidate.offset == declaration_offset",
            "if destinations.count == 0.usize():",
        ),
        "try_error_family_path_for_declaration": (
            "declaration_offset != FALLIBLE_FUNCTION_NO_OFFSET and family_annotation.offset != declaration_offset",
        ),
        "try_error_family_refs_match": (
            "source.declaration_offset != FALLIBLE_FUNCTION_NO_OFFSET and destination.declaration_offset != FALLIBLE_FUNCTION_NO_OFFSET",
            "try_error_family_name_has_unique_module(file, annotations, source.family, expected_module_known, expected_module, table)",
        ),
        "try_error_set_decl_is_static_inactive": (
            'name_row.owner != "__lsp_decl_name" or name_row.name != declaration.name or name_row.line != declaration.line',
            "name_row.pos.offset != declaration.offset",
            "name_row_count != 1.usize()",
            "try_overload_nominal_type_declaration_is_static_inactive(file, annotations, declaration.name, declaration.module, declaration.line, declaration_keyword_offset, table)",
        ),
        "try_error_family_name_has_unique_module": (
            'declaration.owner != "__error_set_decl" or declaration.name != family',
            "try_error_set_decl_is_static_inactive(file, annotations, declaration, table)",
            "declaration.module != selected_module",
            "module_found and (not expected_module_known or selected_module == expected_module)",
        ),
        "try_error_family_subset_status": (
            "family.declaration_offset == FALLIBLE_FUNCTION_NO_OFFSET or family.family_path == \"\"",
        ),
        "try_error_family_has_empty_subset": (
            "family.declaration_offset == FALLIBLE_FUNCTION_NO_OFFSET or family.family_path == \"\"",
        ),
        "callable_function_declaration_visible_with": (
            "declaration_offset != FALLIBLE_FUNCTION_NO_OFFSET and annotation.offset != FALLIBLE_FUNCTION_NO_OFFSET",
            "annotation.offset == declaration_offset",
            "annotation.offset == FALLIBLE_FUNCTION_NO_OFFSET",
        ),
        "callable_symbol_accepts_arity": (
            "if symbol.offset == declaration_offset:",
            "declaration_offset == FALLIBLE_FUNCTION_NO_OFFSET or symbol.offset == FALLIBLE_FUNCTION_NO_OFFSET",
        ),
        "try_noncall_parameter_error_family": (
            "function_pos.offset != FALLIBLE_FUNCTION_NO_OFFSET and enclosing.offset != FALLIBLE_FUNCTION_NO_OFFSET",
            "function_pos.offset < enclosing.offset",
        ),
        "check_try_propagation_row": (
            "enclosing.offset != FALLIBLE_FUNCTION_NO_OFFSET and family_annotation.offset != FALLIBLE_FUNCTION_NO_OFFSET",
            "family_annotation.offset == enclosing.offset",
            "function_line != 0 or enclosing.offset != FALLIBLE_FUNCTION_NO_OFFSET",
        ),
        "try_parameter_error_family": (
            "parameter_found: mutable bool = false",
            "return (false, \"\") if not parameter_found",
        ),
        "try_noncall_static_effect_candidate_may_raise": (
            "operation_matches != 1.usize() or operation_name == \"\"",
            "operation_offset <- operation_row.offset",
        ),
        "try_fallback_extern_declaration_line": (
            "-> (found: bool, line: u32, offset: u32)",
            "function_count <- function_count + 1.usize()",
            "return (true, declaration_line, declaration_offset) if function_count == 1.usize()",
            "return (false, 0, 0)",
        ),
        "try_fallback_extern_return_info": (
            "declaration: (found: bool, line: u32, offset: u32) = try_fallback_extern_declaration_line(table, name)",
            "return info if not declaration.found",
        ),
    }
    for name, fragments in exact_zero_contracts.items():
        body = compact_inline(function_section(source_text, name))
        if any(compact_inline(fragment) not in body for fragment in fragments):
            raise SystemExit(f"Try source selector must treat byte offset zero as exact and reserve the sentinel for missing positions: {name}")
    if "declaration_line != 0" in compact_inline(function_section(source_text, "try_error_family_refs_match")):
        raise SystemExit("Try family identity must not treat logical line zero as missing provenance")

    rows_function = function_section(source_text, "check_try_fallible_rows")
    expected_dispatch = """
row_enclosing: mutable (line: u32, offset: u32) = (0, FALLIBLE_FUNCTION_NO_OFFSET)
if try_site_count > 1:
    row_enclosing <- enclosing_try_function_indexed(function_positions, table, annotation.line, annotation.offset)
else:
    row_enclosing <- enclosing_try_function(table, annotation.line, annotation.offset)
"""
    if not contains_contiguous_block(rows_function, expected_dispatch) or (
        "row_module: sview = fallible_fn_module_indexed(module_index, module_annotations, row_enclosing.offset, row_enclosing.line)"
        not in rows_function
    ):
        raise SystemExit("try rows must use indexed enclosing-function lookup only for multiple try sites and feed its result into module scope resolution")
    if compact_inline(rows_function).count("enclosing_try_function_indexed(") != 1 or \
            compact_inline(rows_function).count("enclosing_try_function(") != 1:
        raise SystemExit("try rows must retain exactly one indexed and one linear enclosing-function dispatch arm")
    propagation_call = "table <- check_try_propagation_row(file, annotation, row_enclosing, row_module, row_qualifier, annotations, try_named_arguments, argument_type_ids, receiver_ref_mutability_known, receiver_ref_mutable, error_set_annotations, error_set_family_paths, error_set_index, propagation_site_count, module_index, module_annotations, error_index, table, row_arity.known, row_arity.value, first_class_error_family, noncall_lambda_error_family, noncall_inside_lambda)"
    if compact_inline(propagation_call) not in compact_inline(rows_function):
        raise SystemExit("resolved enclosing function must flow into try-propagation diagnostics")

    argument_types = compact_inline(function_section(source_text, "try_call_argument_type_ids"))
    if not all(fragment in argument_types for fragment in (
            'marker.owner != "__try_callee_argument_position"',
            "ownership_binding_at_position(table, caller, argument_position)",
            "declared.binding_id.owner.value != binding.binding_id.owner.value",
            "declared.binding_id.serial != binding.binding_id.serial",
            'marker.owner != "__try_callee_argument_direct_call"',
            "ownership_binding_at_position(table, caller, nested_call_position)",
            "callable_try_static_binding_uncertain(annotations, nested_call_name, caller_module, \"\", table)",
            "callable_row_in_scope_with_owner(annotations, nested_call_name, symbol.module_owner, symbol.offset, symbol.line, caller_module, \"\", table)",
            "symbol.return_type_id",
            "call_return_function_offset: mutable u32 = 0",
            "call_return_function_offset <- symbol.offset",
            "type_id_contains_function_generic(call_return_type_id, call_return_function_line, call_return_function_offset, table)",
            "type_id_contains_region(call_return_type_id, table)",
            "call_return_conflict",
            "argument_type_firm or argument_type_ambiguous")):
        raise SystemExit("Try argument types must use exact bindings or one visible unshadowed concrete call result, and fail closed on unresolved imports, generic or region schemes")
    imported_argument_fixture = (ROOT / "test/repro/try_overload_imported_argument_type_id.elisa").read_text()
    if not all(fragment in imported_argument_fixture for fragment in (
            "module Helpers:",
            "def make_flag() -> bool",
            "module Consumer:",
            "from Helpers import make_flag",
            "def choose(value: bool)",
            "def choose(value: i64)",
            "def caller() -> i64 error[Consumer::IntegerFault]",
            "def caller_correct_family() -> i64 error[Consumer::BoolFault]",
            "return try choose(make_flag())")):
        raise SystemExit("Try imported-call argument coverage must bind receiver overload ranking to one visible imported function's concrete return type")
    imported_argument_smoke = (ROOT / "test/parity/try_overload_imported_argument_type_id_smoke.sh").read_text()
    if not all(fragment in imported_argument_smoke for fragment in (
            "try_overload_imported_argument_type_id.elisa",
            "expected_rows=$'L24'",
            "cannot propagate BoolFault from a function returning IntegerFault",
            "grep -q '^D 1$'")):
        raise SystemExit("Try imported-call parity smoke must reject the wrong ErrorSet and preserve the correct-family control")
    generic_parameter = compact_inline(function_section(source_text, "try_overload_type_is_generic_parameter"))
    if not all(fragment in generic_parameter for fragment in (
            'annotation.name == "__generic_param_identity"',
            "annotation.detail_line == declaration_symbol.line",
            "annotation.offset == declaration_symbol.offset",
            "annotation.module == declaration_symbol.module_owner")):
        raise SystemExit("Try overload ranking must identify generic parameters by their exact declaration identity")
    type_selection = compact_inline(function_section(source_text, "callable_symbol_type_selected_candidate"))
    if not all(fragment in type_selection for fragment in (
            'argument.owner == "__try_callee_named_arg"',
            "actual_receiver_type_id: u32 = argument_type_ids[0]",
            "try_overload_type_is_firm_in_module(file, actual_receiver_type_id, enclosing_module, annotations, table)",
            "callable_name_has_ufcs_overload_set_in_scope(module_index, module_annotations, annotations, name, enclosing_module, callee_qualifier, try_named_arguments, try_offset, table)",
            "callable_row_in_ufcs_candidate_set_indexed(module_index, module_annotations, annotations, name, symbol.offset, symbol.line, enclosing_module, callee_qualifier, table)",
            "continue if not receiver.found and not callable_symbol_has_parameter_rows(table, symbol) and symbol.arity_min == 0 and (symbol.arity_max == 0 or symbol.arity_max == 4294967295)",
            "try_overload_receiver_pattern_matches(file, receiver.type_id, actual_receiver_type_id, symbol.id, enclosing_module, annotations, table, 0)",
            "if actual_receiver_is_ref and not formal_receiver_is_ref and not try_overload_type_is_generic_parameter(receiver.type_id, symbol.id, annotations, table):",
            "return invalid if actual_receiver_base_kind == SemTypeKind.Int or actual_receiver_base_kind == SemTypeKind.Float or actual_receiver_base_kind == SemTypeKind.Bool",
            "continue if receiver.mutable_ref and not receiver_ref_mutable",
            "rank_score: usize = rank.score + 1.usize() if formal_receiver_is_ref and actual_receiver_is_ref and receiver.mutable_ref == receiver_ref_mutable else rank.score",
            "if best_count == 0.usize() or rank_score > best_rank:",
            "elif rank_score == best_rank:",
            "return selected if best_count == 1.usize()")):
        raise SystemExit("Try overload selection must use the known first argument, Core-compatible receiver ranking, and a unique top rank")
    if "for actual_type_id in argument_type_ids" in type_selection or "argument_type_ids[parameter_index]" in type_selection:
        raise SystemExit("Later argument types must not affect Core's first-receiver overload selection")
    raw_receiver_overload_set = compact_inline(function_section(source_text, "callable_name_has_ufcs_overload_set_candidate"))
    ranked_receiver_overload_gate = compact_inline(function_section(source_text, "callable_name_has_ufcs_overload_set_in_scope"))
    if not all(fragment in raw_receiver_overload_set for fragment in (
            "callable_row_in_ufcs_candidate_set_indexed",
            "symbol_chain_head(table, name)",
            "other.kind != SymbolKind.Func or other.name != name or other.module_owner != symbol.module_owner",
            "candidate_count >= 2.usize()")) or not all(fragment in ranked_receiver_overload_gate for fragment in (
            'argument.owner == "__try_callee_named_arg"',
            "return callable_name_has_ufcs_overload_set_candidate")):
        raise SystemExit("Try must distinguish Core's raw overload set from the call shapes eligible for receiver ranking")
    receiver_arity = compact_inline(function_section(source_text, "callable_symbol_core_accepts_receiver_arity"))
    if not all(fragment in receiver_arity for fragment in (
            "symbol.arity_max == 4294967295",
            "table.function_param_has_default[row]",
            "return symbol.arity_max == arity")):
        raise SystemExit("Try receiver candidate filtering must mirror Core's variadic, defaulted, and fixed-arity rules")
    if "declaration_id.value == symbol.id.value" not in compact_inline(function_section(source_text, "callable_symbol_has_parameter_rows")):
        raise SystemExit("Try overload ranking must distinguish an actual zero-parameter function from incomplete formal metadata")
    visible_overloads = compact_inline(function_section(source_text, "callable_name_has_ufcs_overload_set_in_scope"))
    visible_overload_candidates = compact_inline(function_section(source_text, "callable_name_has_ufcs_overload_set_candidate"))
    if not all(fragment in visible_overloads for fragment in (
            'argument.owner == "__try_callee_named_arg"',
            "callable_name_has_ufcs_overload_set_candidate(module_index, module_annotations, annotations, name, enclosing_module, callee_qualifier, table)")) or not all(fragment in visible_overload_candidates for fragment in (
            "callable_row_in_ufcs_candidate_set_indexed",
            "other.module_owner != symbol.module_owner",
            "candidate_count >= 2.usize()")):
        raise SystemExit("Try receiver ranking must detect Core overload sets across all visible module candidates")
    candidate_set = compact_inline(function_section(source_text, "callable_row_in_ufcs_candidate_set_indexed"))
    if not all(fragment in candidate_set for fragment in (
            'if callee_qualifier != "": return false if not try_error_alias_module_visible(annotations, candidate_module, enclosing_module) return callable_qualified_module_matches_candidate(annotations, candidate_module, enclosing_module, callee_qualifier, name, table)',
            "candidate_module == scope_module and callable_named_declaration_in_module",
            "callable_wildcard_imported_row_in_scope(annotations, table, name, candidate_module, scope_module)",
            "return callable_program_selective_import_row(annotations, name, candidate_module)")):
        raise SystemExit("Try receiver ranking must retain both lexical and imported functions in Core's visible candidate set")
    candidate_local = candidate_set.find("candidate_module == scope_module and callable_named_declaration_in_module")
    candidate_parent_walk = candidate_set.find("scope_module <- try_noncall_module_parent(scope_module)")
    candidate_wildcard = candidate_set.find("callable_wildcard_imported_row_in_scope")
    candidate_selective = candidate_set.find("return callable_program_selective_import_row(annotations, name, candidate_module)")
    if min(candidate_local, candidate_parent_walk, candidate_wildcard, candidate_selective) < 0 or not (
            candidate_local < candidate_parent_walk < candidate_wildcard < candidate_selective):
        raise SystemExit("Try receiver lookup must scan all lexical declarations before wildcard imports and selective aliases")
    wildcard_imported_row = compact_inline(function_section(source_text, "callable_wildcard_imported_row_in_scope"))
    if 'binding.name == "__binding_wildcard_import" and semantic_import_resolved_owner_matches(table, candidate_module, binding.owner, binding.module) and binding.module == scope_module' not in wildcard_imported_row:
        raise SystemExit("Try wildcard imports must remain tied to their lexical using scope")
    ordinary_row = compact_inline(function_section(source_text, "callable_row_in_scope_with_owner"))
    indexed_row = compact_inline(function_section(source_text, "callable_row_in_scope_indexed"))
    if "return callable_row_in_scope_with_owner(annotations, name, candidate_module, declaration_offset, declaration_line, enclosing_module, callee_qualifier, table)" not in indexed_row:
        raise SystemExit("Try indexed lookup must retain the shared owner-based visibility checks")
    qualified_module_match = compact_inline(function_section(source_text, "callable_qualified_module_matches_candidate"))
    if not all(fragment in qualified_module_match for fragment in (
            "callable_module_path_matches_suffix(symbol.module_owner, scope_module, callee_qualifier)",
            "callable_function_declaration_visible(annotations, name, symbol.module_owner, symbol.line, symbol.offset, enclosing_module)",
            "semantic_possible_import_alias_head_target(alias_head, enclosing_module, before_offset, table)",
            "semantic_possible_import_alias_target_prefix(symbol.module_owner, alias.raw_target, alias.scope, alias.offset, table)",
            "candidate_module == callee_qualifier and callable_named_visible_declaration_in_module(table, annotations, name, candidate_module, enclosing_module)")) or "module_last_segment(candidate_module)" in qualified_module_match:
        raise SystemExit("Try qualified overload ranking must use exact lexical modules, the shared global alias winner, and an exact root path")
    if 'return false if not try_error_alias_module_visible(annotations, candidate_module, enclosing_module) return false if not callable_function_declaration_visible(annotations, name, candidate_module, declaration_line, declaration_offset, enclosing_module) return callable_qualified_module_matches_candidate(annotations, candidate_module, enclosing_module, callee_qualifier, name, table)' not in ordinary_row:
        raise SystemExit("Try ordinary qualified lookup must reject private modules and exact private members while sharing the path matcher")
    linear_scope = compact_inline(function_section(source_text, "callable_row_in_scope"))
    if "callable_qualified_module_matches_candidate(annotations, candidate_module, enclosing_module, callee_qualifier, name, table)" not in linear_scope or "module_last_segment(candidate_module)" in linear_scope:
        raise SystemExit("Try linear family lookup must use the same exact qualified-module matcher")
    global_alias_lookup = compact_inline(function_section(source_text, "callable_using_alias_visible_target_global"))
    if not all(fragment in global_alias_lookup for fragment in (
            "semantic_possible_import_alias_head_target(alias_name, enclosing_module, 4294967295, table)",
            "return (2.usize(), \"\", \"\") if not alias.known",
            "return (1.usize(), alias.target, alias.scope) if alias.found")):
        raise SystemExit("Try must use the shared analyzer-wide alias winner and keep unresolved alias contenders unknown")
    cached_alias_chain = compact_inline(function_section(source_text, "callable_using_alias_target_chain_known"))
    if not all(fragment in cached_alias_chain for fragment in (
            "semantic_possible_import_alias_head_target(alias_head, alias_scope, before_offset, table)",
            "return false if not alias.known",
            "return callable_using_alias_target_chain_known(alias.raw_target, alias.scope, alias.offset, table, depth + 1.u32())")):
        raise SystemExit("Try cached aliases must validate target chains at each declaration cutoff")
    static_alias_binding = compact_inline(function_section(source_text, "callable_try_static_binding_uncertain"))
    if not all(fragment in static_alias_binding for fragment in (
            'unresolved.name == "__using_alias" and callee_qualifier != "" and unresolved.detail_name == alias_head',
            "semantic_possible_import_alias_head_target(alias_head, enclosing_module, 4294967295, table)",
            "continue if selected_alias.known and selected_alias.found return true")) or "try_noncall_module_is_ancestor(unresolved.module, enclosing_module)" in static_alias_binding.split('if unresolved.name == "__using_alias"', 1)[-1]:
        raise SystemExit("Try static alias uncertainty must follow the analyzer-wide alias winner rather than caller ancestry")
    if not all(fragment in qualified_leaf_fixture for fragment in (
            "module OuterB:", "def fail() -> i64 error[F]:", "module OuterA:",
            "def fail() -> i64 error[E]:", "module Caller:", "return try Common::fail()")) or not all(fragment in try_smoke for fragment in (
            "try_qualified_module_leaf_collision.elisa", "cannot propagate E from a function returning F")):
        raise SystemExit("Try smoke must bind the duplicate-leaf fixture where Common resolves only to the caller's OuterA ancestor")
    if not all(fragment in nested_global_alias_fixture for fragment in (
            "module AliasHome:", "module Provider:", "using Provider as Shared", "def good() -> i64 error[E]:", "return try Shared::load()")) or not all(fragment in try_smoke for fragment in (
            "try_nested_global_using_alias.elisa", 'undefined identifier "Shared.load"')):
        raise SystemExit("Try smoke must reject a root call through a module alias declared inside a nested module")
    if not zero_offset_enclosing_fixture.startswith("def caller() -> i64 error[E]:\n") or not all(fragment in zero_offset_enclosing_fixture for fragment in (
            "return try load()", "def load() -> i64 error[E]:",
            "#line 1 zero-offset-enclosing.elisa", "def sibling() -> i64 error[F]:")) or not all(fragment in try_smoke for fragment in (
            "try_zero_offset_enclosing_function_identity.elisa", "^D 0$",
            "same-#line sibling displaced the byte-zero caller")):
        raise SystemExit("Try smoke must bind a byte-zero enclosing function against a same-line sibling with a different error family")
    if "#line 0 try-line-zero.elisa\ndef caller() -> i64:" not in line_zero_nonerror_fixture or not all(fragment in line_zero_nonerror_fixture for fragment in (
            "def load() -> i64 error[E]:", "return try load()")) or not all(fragment in try_smoke for fragment in (
            "try_nonerror_enclosing_line_zero.elisa", "try without else requires the current function to return an error union")):
        raise SystemExit("Try smoke must retain the #line 0 non-error caller regression")
    if not all(fragment in first_class_ambiguous_family_fixture for fragment in (
            "module Provider:", "error Fault:", "module Caller:", "from Caller import Fault",
            "#line 0 try-family-ref-provenance.elisa", "error[Provider::Fault]", "return try value")) or not all(fragment in try_smoke for fragment in (
            "try_first_class_ambiguous_error_family.elisa", "^D 1$",
            "cannot propagate Fault from a function returning Fault")):
        raise SystemExit("Try family provenance must reject a line-zero name-only match when duplicate ErrorSet owners exist")
    if not all(fragment in first_class_inactive_duplicate_family_fixture for fragment in (
            "module Provider:", "error Fault:", "static if false:", "module InactiveCaller:",
            "error Fault:", "from Provider import Fault", "#line 0 try-family-inactive-owner.elisa",
            "error[Provider::Fault]", "return try value")) or not all(fragment in try_smoke for fragment in (
            "try_first_class_inactive_duplicate_error_family.elisa", "^D 0$")):
        raise SystemExit("Try family uniqueness must ignore a duplicate ErrorSet only when its static branch is proven inactive")
    ordinary_local = ordinary_row.find("if callable_named_visible_declaration_in_module(table, annotations, name, scope_module, enclosing_module): return candidate_module == scope_module")
    ordinary_parent_walk = ordinary_row.find("scope_module <- try_noncall_module_parent(scope_module)")
    ordinary_wildcard = ordinary_row.find("wildcard: (found: bool, matches: bool) = callable_first_wildcard_imported_row")
    ordinary_selective = ordinary_row.find("return callable_program_selective_import_row_visible(annotations, name, candidate_module, enclosing_module)")
    if min(ordinary_local, ordinary_parent_walk, ordinary_wildcard, ordinary_selective) < 0 or not (
            ordinary_local < ordinary_parent_walk < ordinary_wildcard < ordinary_selective):
        raise SystemExit("Try ordinary lookup must scan every visible lexical parent before wildcard imports and selective aliases")
    visible_lexical_declaration = compact_inline(function_section(source_text, "callable_named_visible_declaration_in_module"))
    if not all(fragment in visible_lexical_declaration for fragment in (
            "callable_function_declaration_visible(annotations, name, module, symbol.line, symbol.offset, enclosing_module)",
            "symbol.kind != SymbolKind.Func or symbol.name != name or symbol.module_owner != module")):
        raise SystemExit("Try lexical lookup must skip inaccessible declarations instead of letting them shadow visible imports")
    callable_declaration_visibility = compact_inline(function_section(source_text, "callable_function_declaration_visible_with"))
    if not all(fragment in callable_declaration_visibility for fragment in (
            "try_error_alias_module_visible(annotations, candidate_module, lexical_module)",
            'annotation.owner != "__section_private" and annotation.owner != "__section_public"',
            "annotation.offset == declaration_offset",
            "annotation.line == declaration_line",
            "return try_noncall_module_is_ancestor(candidate_module, lexical_module) if exact_private",
            "return true if exact_public",
            "return false if legacy_private_marker")):
        raise SystemExit("Try callable visibility must match private/public markers to the exact declaration and module path")
    first_wildcard = compact_inline(function_section(source_text, "callable_first_wildcard_imported_row"))
    if not all(fragment in first_wildcard for fragment in (
            'binding.name != "__binding_wildcard_import"',
            "try_noncall_module_is_ancestor(binding.module, enclosing_module)",
            "semantic_import_resolved_owner_matches(table, symbol.module_owner, binding.owner, binding.module)",
            "callable_function_declaration_visible(annotations, name, symbol.module_owner, symbol.line, symbol.offset, enclosing_module)",
            "ambiguous_imports <- true if selected_found and selected_target != symbol.module_owner",
            "selected_scope_length: mutable usize = enclosing_module.len + 1.usize()",
            "binding.module.len < selected_scope_length",
            "selected_target <- symbol.module_owner",
            "return (true, false) if ambiguous_imports",
            "return (selected_found, selected_target == candidate_module)")):
        raise SystemExit("Try ordinary wildcard lookup must preserve Core's outer-to-inner order and private visibility")
    program_selective_import = compact_inline(function_section(source_text, "callable_program_selective_import_row"))
    if not all(fragment in program_selective_import for fragment in (
            'binding.owner != "__from_member" or binding.name != name',
            'source.owner != "__from_src" or source.module != binding.module or source.line != binding.line or source.offset != binding.offset',
            'return candidate_module == source.name if binding.module == ""',
            "return callable_module_path_matches_suffix(candidate_module, binding.module, source.name)")):
        raise SystemExit("Try selective imports must match Core's raw source path relative to the importing namespace")
    program_selective_import_visible = compact_inline(function_section(source_text, "callable_program_selective_import_row_visible"))
    if not all(fragment in program_selective_import_visible for fragment in (
            "path_matches and callable_named_visible_declaration_in_module(table, annotations, name, candidate_module, enclosing_module)")):
        raise SystemExit("Try ordinary selective imports must reject private target modules and members")
    noncall_import_builder = compact_inline(function_section(source_text, "try_noncall_binding_at_site"))
    if not all(fragment in noncall_import_builder for fragment in (
            "already_imported_name: mutable bool = false",
            "environment.callable_imported_member_names[index] == import_annotation.name",
            "binding_import_module_owner(source_annotation.name, import_annotation.module, table)",
            "if imported_module != \"\" and not already_imported_name",
            "environment.callable_imported_member_names.push(import_annotation.name)")):
        raise SystemExit("Try non-call cached facts must retain only Core's first selective import for each bare name")
    noncall_module_path = compact_inline(function_section(source_text, "try_noncall_module_path"))
    cached_fact_builder = compact_inline(function_section(source_text, "try_noncall_callable_facts_add"))
    if not all(fragment in noncall_module_path for fragment in (
            'return child if parent == ""',
            "bytes.reserve(parent.len + 2.usize() + child.len)",
            "bytes.push(58) bytes.push(58)",
            "return intern_joined_text(bytes, table)")) or not all(fragment in cached_fact_builder for fragment in (
            "nested_module: sview @source = module_name",
            "try_noncall_callable_facts_add(module_body, annotations, marker_index, environment, nested_module, table)")):
        raise SystemExit("Try module path joins must preserve already-qualified declaration children while keeping relative joins")
    noncall_assignment_facts = compact_inline(function_section(source_text, "try_noncall_assignment_source_facts"))
    if 'return (call_facts.family, call_facts.return_nonfallible and call_facts.family == "") if call_facts.known' not in noncall_assignment_facts:
        raise SystemExit("Try non-call assignment facts must preserve known infallible callable returns")
    cached_lookup = compact_inline(function_section(source_text, "try_noncall_callable_cached_facts"))
    cached_local = cached_lookup.find("local_matches: mutable usize = 0")
    cached_parent_walk = cached_lookup.find("scope_module <- try_noncall_module_parent(scope_module)")
    cached_wildcard = cached_lookup.find("for import_index in 0..<environment.callable_wildcard_import_modules.count")
    cached_scope_rank = cached_lookup.find("import_scope.len < selected_import_scope_length")
    cached_selective = cached_lookup.find("for import_index in 0..<environment.callable_imported_member_names.count")
    if min(cached_local, cached_parent_walk, cached_wildcard, cached_scope_rank, cached_selective) < 0 or not (
            cached_local < cached_parent_walk < cached_wildcard < cached_scope_rank < cached_selective):
        raise SystemExit("Try cached lookup must scan all lexical declarations, then outer-to-inner wildcards, then selective aliases")
    if not all(fragment in cached_lookup for fragment in (
            "wildcard_ambiguous: mutable bool = false",
            "wildcard_ambiguous <- true if first_visible_import_module != \"\" and first_visible_import_module != environment.callable_wildcard_import_modules[import_index]",
            'return (false, "", false, false, false, true, "", 0.usize()) if wildcard_ambiguous')):
        raise SystemExit("Try cached lookup must fail closed when distinct visible wildcard targets make a bare name ambiguous")
    if not all(fragment in cached_fact_builder for fragment in (
            "callable_visible: bool = callable_function_declaration_visible_with(declaration_rows, annotations, name, current_module, function_position.line, function_position.offset, environment.current_module)",
            "environment.callable_names.push(name)",
            "environment.callable_visible.push(callable_visible)",
            "environment.callable_facts_known.push(not unresolved_static_branch and family_rows <= 1.usize())",
            "environment.callable_first_param_type_names.push(first_param_type_name)",
            "environment.callable_first_param_generic.push(first_param_is_generic)",
            "environment.callable_max_param_counts.push(params.count)",
            "environment.callable_has_default_params.push(has_default_param)",
            "environment.callable_variadic.push(variadic)")):
        raise SystemExit("Try cached facts must retain visibility separately from known family facts")
    if cached_lookup.count("environment.callable_visible[index]") < 4:
        raise SystemExit("Try cached local, wildcard, selective, and qualified lookup must filter inaccessible candidates")
    cached_hidden_rank = compact_inline(function_section(source_text, "try_noncall_cached_hidden_candidate_blocks"))
    if not all(fragment in cached_hidden_rank for fragment in (
            "not environment.callable_visible[index]",
            "environment.callable_max_param_counts[index] != arguments.count",
            "try_noncall_cached_argument_type_name(arguments[selected_argument_index], params)",
            "try_noncall_cached_argument_type_name(arguments[hidden_argument_index], params)",
            "try_noncall_cached_callable_in_ufcs_set(callee_name, environment.callable_modules[index], callee_qualifier, callee, environment)",
            "try_noncall_cached_receiver_type_matches(hidden_type, actual_type)",
            "actual_type == \"int\" and try_noncall_cached_integer_type(hidden_type) and try_noncall_cached_integer_type(selected_type)",
            "if selected_generic: return true")):
        raise SystemExit("Try cached family inference must fail closed when a viable hidden overload can win, while using known argument types to rule out incompatible private siblings")

    return {
        'argument_types': argument_types,
        'cached_lookup': cached_lookup,
        'noncall_import_builder': noncall_import_builder,
    }
