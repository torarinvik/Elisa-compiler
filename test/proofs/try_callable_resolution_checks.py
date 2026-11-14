"""Check callable resolution and visibility for try expressions."""
import re


def check_try_callable_resolution(
    facts,
    PARSER_ARGUMENT_SOURCE,
    PARSER_CATCH_SOURCE,
    PARSER_DECLARATION_SOURCE,
    PARSER_FUNCTION_SOURCE,
    PARSER_NOMINAL_SOURCES,
    PARSER_VISIBILITY_SOURCE,
    compact_inline,
    function_section,
    private_overload_fixture,
    private_overload_smoke,
    source_text,
):
    cached_candidate_set = compact_inline(function_section(source_text, "try_noncall_cached_callable_in_ufcs_set"))
    if not all(fragment in cached_candidate_set for fragment in (
            "try_noncall_module_is_ancestor(candidate_module, environment.current_module)",
            "try_noncall_module_is_ancestor(environment.callable_wildcard_import_scopes[import_index], environment.current_module)",
            "environment.callable_imported_member_names[import_index] != callee_name",
            "try_noncall_qualified_module_matches(callee, candidate_module, callee_name, environment, true)")):
        raise SystemExit("Try cached hidden-candidate checks must cover Core's lexical, wildcard, selective, and qualified receiver candidate modules")
    cached_module_match = compact_inline(function_section(source_text, "try_noncall_qualified_module_matches"))
    cached_qualifier_path = compact_inline(function_section(source_text, "try_noncall_qualifier_path_matches_module"))
    cached_alias_target = compact_inline(function_section(source_text, "try_noncall_visible_using_alias_target"))
    if not all(fragment in cached_module_match for fragment in (
            "include_hidden: bool",
            "try_noncall_qualifier_path_matches_module(qualifier, environment.callable_modules[index], scope_module)",
            "not include_hidden and not environment.callable_visible[index]",
            "try_noncall_callable_matches_using_alias(callee, alias_index, environment.callable_modules[index], environment)",
            "try_noncall_qualifier_path_matches_module(qualifier, module_path, \"\")")) or "module_path == name if lexical_scope == \"\"" not in cached_qualifier_path or "module_last_segment(module_path)" in cached_qualifier_path or "environment.using_alias_known[index]" not in cached_alias_target:
        raise SystemExit("Try cached qualified lookup must bind lexical module identity, the global alias target, and exact root spelling")
    if "try_noncall_qualified_module_matches(callee, candidate_module, callee_name, environment, true)" not in cached_candidate_set or "try_noncall_qualified_module_matches(callee, environment.callable_modules[index], callee_name, environment, false)" not in facts['cached_lookup'] or not all(fragment in private_overload_fixture for fragment in (
            "def qualified_private_winner_direct", "def qualified_private_winner_cached", "private:", "return try Provider::origin(value)")) or "try_overload_private_winner_visibility.elisa" not in private_overload_smoke:
        raise SystemExit("Try must match hidden qualified candidates in blocker mode while skipping them in ordinary cached lookup, with private winner coverage")
    cached_lookup_signature = compact_inline(function_section(source_text, "try_noncall_callable_cached_facts"))
    if "arguments: darray[Ast::Expr]&" not in cached_lookup_signature or "try_noncall_cached_hidden_candidate_blocks(callable_index, callee_name, callee_qualifier, callee, arguments, argument_names, params, environment)" not in cached_lookup_signature or "try_noncall_callable_cached_facts(callee_name, callee_qualifier, callee, environment)" in source_text:
        raise SystemExit("Every Try cached callable lookup must receive call arguments and caller parameter types before returning ErrorSet facts")
    cached_static_binding = compact_inline(function_section(source_text, "try_noncall_static_binding_may_affect_call"))
    if not all(fragment in cached_static_binding for fragment in (
            'unresolved.name == "__from_member"',
            'unresolved.name == "__binding_wildcard_import"',
            'unresolved.name == "__using_alias"',
            "try_noncall_visible_using_alias_target(environment, alias_head)",
            "continue if resolved_alias.known",
            "return true if environment.callable_names[callable_index] == callee_name and environment.callable_visible[callable_index]")) or "continue if not try_noncall_module_is_ancestor(unresolved.module, environment.current_module)" in cached_static_binding or not all(fragment in cached_lookup_signature for fragment in (
            "try_noncall_static_binding_may_affect_call(callee_name, callee_qualifier, callee, environment)",
            'return (false, "", false, false, false, true, "", 0.usize())')):
        raise SystemExit("Try cached callable facts must fail closed only when an unresolved static import or alias can reach a same-name candidate")
    if cached_lookup_signature.find("try_noncall_static_binding_may_affect_call") > cached_lookup_signature.find("match_count: mutable usize"):
        raise SystemExit("Try must reject an unresolved static candidate before selecting cached callable facts")
    static_alias_path_uncertain = compact_inline(function_section(source_text, "callable_static_alias_path_uncertain"))
    if not all(fragment in static_alias_path_uncertain for fragment in (
            "semantic_possible_import_alias_head_target(segments[0], current_scope, before_offset, table)",
            'unresolved.owner != "__try_unresolved_static_binding" or unresolved.name != "__using_alias" or unresolved.detail_name != segments[0]',
            "possible_alias.module != unresolved.module or possible_alias.line != unresolved.line or possible_alias.offset != unresolved.offset",
            "semantic_possible_import_alias_precedes_position(possible_alias, current_scope, before_offset, table)",
            "visible_alias.raw_target",
            "before_offset <- visible_alias.offset",
            "return segments.count > 0.usize()")):
        raise SystemExit("Try direct callable lookup must keep uncertainty when an alias target path crosses a visible or unresolved alias head")
    if not all(fragment in facts['noncall_import_builder'] for fragment in (
            "environment.unresolved_static_bindings.push(unresolved)",
            "environment.unresolved_static_binding_targets.push(target_module)",
            "try_noncall_module_path(unresolved.module, source.name, table)",
            "try_noncall_module_path(unresolved.module, alias_target.owner, table)",
            'candidate_alias.name == "__using_alias" and candidate_alias.detail_name == target_head',
            "callable_using_alias_visible_target_global(annotations, unresolved.module, target_head, table)",
            "visible_target_alias.count == 0.usize() and not unresolved_target_alias",
            "environment.using_alias_known.push(alias_target.count == 1.usize() and alias_chain_known)",
            "callable_using_alias_target_chain_known(alias_selection.raw_target, alias_selection.scope, alias_selection.offset, table)",
            'candidate_alias.name == "__using_alias" and candidate_alias.detail_name == target_head')):
        raise SystemExit("Try non-call environments must retain unresolved marker targets through branch clones")
    cached_env_clone = compact_inline(function_section(source_text, "try_noncall_family_clone"))
    if not all(fragment in cached_env_clone for fragment in (
            "clone.callable_first_param_type_names.extend(environment.callable_first_param_type_names)",
            "clone.callable_first_param_generic.extend(environment.callable_first_param_generic)",
            "clone.callable_max_param_counts.extend(environment.callable_max_param_counts)",
            "clone.callable_has_default_params.extend(environment.callable_has_default_params)",
            "clone.callable_variadic.extend(environment.callable_variadic)",
            "clone.using_alias_known.extend(environment.using_alias_known)",
            "clone.unresolved_static_bindings.extend(environment.unresolved_static_bindings)",
            "clone.unresolved_static_binding_targets.extend(environment.unresolved_static_binding_targets)")):
        raise SystemExit("Try branch clones must preserve cached overload signature facts")
    selected_receiver_acceptance = compact_inline(function_section(source_text, "callable_symbol_accepts_arity"))
    if not all(fragment in selected_receiver_acceptance for fragment in (
            "accepts_call <- false if selected_type_candidate.value != INVALID_DECL_ID_VALUE and symbol.id.value != selected_type_candidate.value",
            "symbol.id.value == selected_type_candidate.value and not callable_function_declaration_visible")):
        raise SystemExit("Try family selection must reject a private receiver winner and its public overload siblings")
    selected_receiver_count = compact_inline(function_section(source_text, "callable_symbol_arity_candidate_count"))
    if not all(fragment in selected_receiver_count for fragment in (
            "selected_type_candidate.value.usize() >= table.symbols.count",
            "return 1.usize() if callable_function_declaration_visible",
            "return 0.usize()")):
        raise SystemExit("Try receiver candidate counting must keep private winners out of accessible family selection")
    private_selected_fallibility = compact_inline(function_section(source_text, "callable_error_indexed_returns_error"))
    if not all(fragment in private_selected_fallibility for fragment in (
            "selected_type_candidate: DeclId = callable_symbol_type_selected_candidate",
            "selected_private_winner: bool = selected_symbol.line == annotation.line",
            "not callable_function_declaration_visible(annotations, name, candidate_module, annotation.line, annotation.offset, enclosing_module)",
            "return true if selected_private_winner",
            "forwarded_private_candidate: bool = callable_row_in_ufcs_candidate_set_indexed",
            "unresolved_private_candidate: bool = callable_overload_declaration_is_inaccessible_arity_candidate",
            "return true if unresolved_private_candidate")):
        raise SystemExit("Try must suppress cascading TryRequiresFallible diagnostics for exact or unresolved private winners without exposing their ErrorSets")
    private_family_ref = compact_inline(function_section(source_text, "callable_error_indexed_family_ref"))
    if not all(fragment in private_family_ref for fragment in (
            "callable_row_visible_for_try_call(module_index, module_annotations, annotations, name, annotation.offset, annotation.line",
            "callable_symbol_accepts_arity(file, table, annotations, try_named_arguments, argument_type_ids",
            "return TryErrorFamilyRef{family: \"\"")) or "selected_private_winner" in private_family_ref:
        raise SystemExit("Try's private-winner suppression must not expose an inaccessible ErrorSet to propagation checks")
    private_family_refs = compact_inline(function_section(source_text, "callable_error_indexed_family_refs"))
    if not all(fragment in private_family_refs for fragment in (
            "visible: bool = callable_row_visible_for_try_call",
            "and callable_symbol_accepts_arity(file, table, annotations, try_named_arguments, argument_type_ids",
            "if visible")):
        raise SystemExit("Try composite family collection must apply the same visibility filter before selecting a propagation family")
    unresolved_private_candidate = compact_inline(function_section(source_text, "callable_overload_declaration_is_inaccessible_arity_candidate"))
    if not all(fragment in unresolved_private_candidate for fragment in (
            "callable_name_has_ufcs_overload_set_in_scope",
            "callable_row_in_ufcs_candidate_set_indexed",
            "callable_symbol_core_accepts_receiver_arity",
            "callable_symbol_accepts_named_arguments",
            "or callable_function_declaration_visible",
            "try_overload_receiver_pattern_matches(file, receiver.type_id, argument_type_ids[0]",
            "try_overload_type_shared_ambiguous_match_state(file, receiver.type_id, argument_type_ids[0]",
            "receiver_ref_mutability_known",
            "receiver.mutable_ref and not receiver_ref_mutable")):
        raise SystemExit("Try unresolved private-candidate checks must model Core's overload set, receiver compatibility, and reference mutability")
    unresolved_private_guard = compact_inline(function_section(source_text, "callable_overload_has_inaccessible_arity_candidate"))
    if "callable_overload_declaration_is_inaccessible_arity_candidate" not in unresolved_private_guard:
        raise SystemExit("Try must identify inaccessible receiver candidates before unresolved family fallback")
    if "callable_overload_has_inaccessible_arity_candidate" not in selected_receiver_acceptance or "callable_overload_has_inaccessible_arity_candidate" not in selected_receiver_count:
        raise SystemExit("Try unresolved receiver selection must fail closed for ErrorSet family lookup when a private candidate remains")
    forwarded_family_guard = compact_inline(function_section(source_text, "callable_symbol_accepts_arity"))
    forwarded_candidate_count = compact_inline(function_section(source_text, "callable_symbol_arity_candidate_count"))
    if not all(fragment in forwarded_family_guard for fragment in (
            "callable_try_call_forwards_arguments(annotations, try_offset)",
            "callable_name_has_ufcs_overload_set_candidate")) or not all(fragment in forwarded_candidate_count for fragment in (
            "callable_try_call_forwards_arguments(annotations, try_offset)",
            "callable_name_has_ufcs_overload_set_candidate")):
        raise SystemExit("Try forwarded calls must not propagate an arbitrary sibling ErrorSet, while singleton lookup remains available")
    cached_source_facts = compact_inline(function_section(source_text, "try_noncall_callable_source_facts"))
    if 'return (false, "", false, false, false) if cached_facts.ambiguous or callee_qualifier != ""' not in cached_source_facts:
        raise SystemExit("Try cached source inference must not borrow a family from an ambiguous wildcard lookup")
    legacy_fallback = cached_source_facts.find("legacy_facts: (known: bool, family: sview @source) = try_noncall_callable_error_family(callee_name, annotations)")
    hidden_name_blocker = cached_source_facts.find("return (false, \"\", false, false, false) if any name in environment.callable_names where name == callee_name")
    if hidden_name_blocker < 0 or legacy_fallback < 0 or hidden_name_blocker > legacy_fallback:
        raise SystemExit("Try cached hidden-name metadata must block the unscoped legacy ErrorSet fallback")
    receiver_match = compact_inline(function_section(source_text, "try_overload_receiver_pattern_matches"))
    if not all(fragment in receiver_match for fragment in (
            "try_overload_type_is_generic_parameter(formal_type_id, declaration, annotations, table)",
            "return (true, true) if formal_type_id == actual_type_id",
            'interned_name(actual_type_id, table) == "int"',
            'formal_kind == SemTypeKind.Char and actual_kind == SemTypeKind.Int and interned_name(actual_type_id, table) == "int"',
            "type_ids_compatible(formal_type_id, actual_type_id, table)",
            "element_position in 0..<element_count.usize()")):
        raise SystemExit("Receiver matching must support exact generic parameters, compatible concrete types, and structural receiver shapes")
    cached_integer_type = compact_inline(function_section(source_text, "try_noncall_cached_integer_type"))
    cached_builtin_type = compact_inline(function_section(source_text, "try_noncall_cached_builtin_type"))
    if '"char"' not in cached_integer_type or '"uintptr"' not in cached_integer_type or '"char"' not in cached_builtin_type or '"uintptr"' not in cached_builtin_type:
        raise SystemExit("Try cached receiver ranking must treat char and uintptr as integral storage for an untyped int actual")
    primitive_type_facts = compact_inline(function_section(source_text, "try_noncall_type_name_facts"))
    primitive_integer_facts = primitive_type_facts.split("integer: bool =", 1)
    if len(primitive_integer_facts) != 2 or '"char"' not in primitive_integer_facts[0] or '"uintptr"' not in primitive_integer_facts[1] or "known_nonfallible: bool = numeric" not in primitive_integer_facts[1]:
        raise SystemExit("Try non-call primitive facts must keep char numeric and uintptr integral and known non-fallible")
    receiver_specificity = compact_inline(function_section(source_text, "try_overload_receiver_specificity"))
    if not all(fragment in receiver_specificity for fragment in (
            "return (true, 0.usize()) if try_overload_type_is_generic_parameter(type_id, declaration, annotations, table)",
            "score <- score + element_score.score",
            "return (true, 1.usize())")):
        raise SystemExit("Receiver specificity must rank generic leaves below concrete leaves and add structural specificity")
    receiver_type = compact_inline(function_section(source_text, "callable_symbol_receiver_type"))
    if "table.function_param_mutable_ref[row]" not in receiver_type or "mutable_ref_known: bool" not in receiver_type:
        raise SystemExit("Receiver ranking must retain the selected formal reference mutability")
    argument_types = compact_inline(function_section(source_text, "try_call_argument_type_ids"))
    if "declared.writable_borrow" not in argument_types or "receiver_ref_mutability_known" not in argument_types:
        raise SystemExit("Try receiver ranking must retain exact binding reference mutability when available")
    if not all(fragment in argument_types for fragment in (
            "receiver_ref_mutability_seen: bool = receiver_ref_mutability_known",
            "if not receiver_ref_mutability_seen:",
            "receiver_ref_mutability_resolved: bool = receiver_ref_mutability_known",
            "not receiver_ref_mutability_resolved")):
        raise SystemExit("Try receiver mutability reads must snapshot the mutable output reference before boolean negation")
    firm_type = compact_inline(function_section(source_text, "try_overload_type_is_firm"))
    if not all(fragment in firm_type for fragment in (
            "try_overload_type_is_generic_parameter(type_id, declaration, annotations, table)",
            "try_overload_nominal_type_owner(file, name, declaration, annotations, table)",
            "return identity.found")):
        raise SystemExit("Try firm named receiver types must resolve one nominal owner in the declaration's lexical scope")
    module_firm_type = compact_inline(function_section(source_text, "try_overload_type_is_firm_in_module"))
    if not all(fragment in module_firm_type for fragment in (
            "depth > 64",
            "try_overload_nominal_type_owner_for_module(file, name, lexical_module, annotations, table)",
            "try_overload_type_is_firm_in_module(file, interned_elem(type_id, element_position.u32(), table), lexical_module, annotations, table, depth + 1)")):
        raise SystemExit("Try receiver ranking must resolve named actual types in the call-site module, including nested type shapes")
    type_visibility = compact_inline(function_section(source_text, "try_overload_type_declaration_visible"))
    if not all(fragment in type_visibility for fragment in (
            "try_error_alias_module_visible(annotations, declaration_module, lexical_module)",
            "type_symbol_is_alias",
            "try_noncall_type_alias_declaration_is_static_inactive(file, annotations, name, declaration_module, declaration_line, declaration_offset, table)",
            "try_overload_nominal_type_declaration_is_static_inactive(file, annotations, name, declaration_module, declaration_line, declaration_offset, table)",
            'annotation.owner != "__section_private"',
            "exact_offset",
            "try_noncall_module_is_ancestor(declaration_module, lexical_module)")):
        raise SystemExit("Try nominal owner lookup must filter inaccessible modules and declaration-specific private type markers")
    nominal_static_activity = compact_inline(function_section(source_text, "try_overload_nominal_type_declaration_is_static_inactive"))
    nominal_type_classifier = compact_inline(function_section(source_text, "try_overload_type_symbol_is_nominal"))
    if not all(fragment in nominal_type_classifier for fragment in (
            "symbol.kind == SymbolKind.Struct",
            "symbol.kind == SymbolKind.Enum",
            "symbol.kind == SymbolKind.Alias",
            "symbol.kind == SymbolKind.Extern and symbol.opaque_extern_type")):
        raise SystemExit("Try nominal owner lookup must classify structs, enums, aliases, and opaque extern types")
    if not all(fragment in nominal_static_activity for fragment in (
            'marker.owner != "__static_if_branch"',
            'marker.name != "__nominal_type_static_branch"',
            "marker.detail_name != name",
            "marker.module != declaration_module",
            "marker.line != declaration_line",
            "marker.offset != declaration_offset",
            "continue if marker.identity_id == 4294967295",
            "pma_static_if_row_selection(file, marker.identity_id.usize(), declaration_module, table)",
            "return true if branch.known and not branch.selected")):
        raise SystemExit("Try nominal owner lookup must exclude only exact, proven-inactive non-alias type declarations")
    error_set_static_activity = compact_inline(function_section(source_text, "try_error_set_decl_is_static_inactive"))
    if not all(fragment in error_set_static_activity for fragment in (
            'name_row.owner != "__lsp_decl_name"',
            "name_row.line != declaration.line",
            "name_row.pos.offset != declaration.offset",
            "name_row_count != 1.usize()",
            "try_overload_nominal_type_declaration_is_static_inactive(file, annotations, declaration.name, declaration.module, declaration.line, declaration_keyword_offset, table)")) or not all(fragment in nominal_static_activity for fragment in (
            "continue if marker.identity_id == 4294967295",
            "return true if branch.known and not branch.selected")):
        raise SystemExit("Try family uniqueness must ignore only exact, proven-inactive ErrorSets and retain unknown branch owners")
    type_owner_module = compact_inline(function_section(source_text, "try_overload_type_owner_in_module"))
    if not all(fragment in type_owner_module for fragment in (
            "try_overload_type_symbol_is_nominal(symbol)",
            "try_overload_type_declaration_visible(file, annotations, symbol.kind == SymbolKind.Alias, name, declaration_module, symbol.line, symbol.offset, lexical_module, table)",
            "return (count > 0.usize(), false, declaration_module)")):
        raise SystemExit("Try nominal owner lookup must recognize a visible owner within one module and leave duplicate declarations to Core")
    nominal_type_identity = compact_inline(function_section(source_text, "try_overload_nominal_type_owner_for_module"))
    if not all(fragment in nominal_type_identity for fragment in (
            "try_overload_type_owner_in_module(file, name, scope_module, lexical_module, annotations, table)",
            "return local if local.found or local.ambiguous",
            "scope_module <- try_noncall_module_parent(scope_module)",
            'binding.owner != "__from_member"',
            'source.owner != "__from_src"',
            "callable_import_module_matches_target(symbol.module_owner, binding.module, source.name)",
            'binding.name != "__binding_wildcard_import"',
            "binding.module.len > wildcard_scope_length",
            "try_overload_type_declaration_visible(file, annotations, symbol.kind == SymbolKind.Alias, name, symbol.module_owner, symbol.line, symbol.offset, lexical_module, table)")):
        raise SystemExit("Try nominal identity must follow local and ancestor declarations, selective imports, then the nearest visible wildcard import")
    nominal_type_owner = compact_inline(function_section(source_text, "try_overload_nominal_type_owner"))
    if not all(fragment in nominal_type_owner for fragment in (
            "table.symbols[declaration.value.usize()].module_owner",
            "try_overload_nominal_type_owner_for_module(file, name, table.symbols[declaration.value.usize()].module_owner, annotations, table)")):
        raise SystemExit("Try formal nominal identities must be resolved from the owning declaration's module")
    ambiguous_type_identity = compact_inline(function_section(source_text, "try_overload_type_has_ambiguous_nominal_identity"))
    if not all(fragment in ambiguous_type_identity for fragment in (
            "try_overload_type_is_generic_parameter(type_id, declaration, annotations, table)",
            "try_overload_nominal_type_owner(file, name, declaration, annotations, table)",
            "identity.ambiguous",
            "interned_elem(type_id, element_position.u32(), table)")):
        raise SystemExit("Try ambiguous nominal receiver detection must preserve generic identity and recurse through structural types")
    if not all(fragment in receiver_match for fragment in (
            "try_overload_nominal_type_owner(file, name, declaration, annotations, table)",
            "try_overload_nominal_type_owner_for_module(file, name, actual_module, annotations, table)",
            "formal_identity.ambiguous or actual_identity.ambiguous",
            "formal_identity.owner == actual_identity.owner")):
        raise SystemExit("Try named receiver matching must compare lexical nominal owners and fail closed on ambiguity")
    if "try_overload_type_has_ambiguous_nominal_identity(file, argument_type_id, caller, annotations, table, 0)" not in argument_types or "argument_type_firm or argument_type_ambiguous" not in argument_types:
        raise SystemExit("Try argument typing must preserve ambiguous nominal identity for candidate lookup to fail closed")
    shared_ambiguous_match = compact_inline(function_section(source_text, "try_overload_type_shared_ambiguous_match_state"))
    if not all(fragment in shared_ambiguous_match for fragment in (
            "try_overload_nominal_type_owner_for_module(file, name, actual_module, annotations, table)",
            "try_overload_nominal_type_owner(file, name, formal_declaration, annotations, table)",
            "actual_identity.owner != formal_identity.owner",
            'formal_kind == SemTypeKind.Int and actual_kind == SemTypeKind.Int and interned_name(actual_type_id, table) == "int"',
            'formal_kind == SemTypeKind.Char and actual_kind == SemTypeKind.Int and interned_name(actual_type_id, table) == "int"',
            "element_count != interned_elem_count(formal_type_id, table)",
            "has_ambiguous_element <- true if element_state.ambiguous")):
        raise SystemExit("Try ambiguity overlap must include Core's int-to-integer and int-to-char receiver coercions, distinguish known different owners, and recurse through structural shapes")
    ambiguous_receiver_candidate = compact_inline(function_section(source_text, "callable_overload_has_ambiguous_nominal_receiver_candidate"))
    if not all(fragment in ambiguous_receiver_candidate for fragment in (
            "callable_name_has_ufcs_overload_set_in_scope(module_index, module_annotations, annotations, name, enclosing_module, callee_qualifier, try_named_arguments, try_offset, table)",
            "callable_row_in_ufcs_candidate_set_indexed(module_index, module_annotations, annotations, name, symbol.offset, symbol.line, enclosing_module, callee_qualifier, table)",
            "callable_symbol_core_accepts_receiver_arity(table, symbol, arity)",
            "callable_symbol_receiver_type(table, symbol)",
            "try_overload_type_shared_ambiguous_match_state(file, receiver.type_id, argument_type_ids[0], symbol.id, enclosing_module, annotations, table, 0)",
            "ambiguous_match.potential_match and ambiguous_match.ambiguous")):
        raise SystemExit("Try ambiguity rejection must be limited to a visible, arity-eligible receiver candidate with a shared ambiguous nominal spelling")
    if "return false if callable_overload_has_ambiguous_nominal_receiver_candidate" not in selected_receiver_acceptance or "return 0.usize() if callable_overload_has_ambiguous_nominal_receiver_candidate" not in selected_receiver_count:
        raise SystemExit("Try candidate fallback must not reselect a visible concrete overload after nominal receiver identity becomes ambiguous")
    parser_source = PARSER_ARGUMENT_SOURCE.read_text()
    if 'owner: "__try_callee_argument_position"' not in parser_source or "pos: Ast::expr_pos(arguments[index])" not in parser_source:
        raise SystemExit("Try calls must retain each actual argument's exact AST position for resolved type lookup")
    parser_nominal_text = [path.read_text() for path in PARSER_NOMINAL_SOURCES]
    if parser_nominal_text[0].count('record_static_if_branch_rows("__nominal_type_static_branch", name_text, token)') != 2 or \
            'record_static_if_branch_rows("__nominal_type_static_branch", target_name, token)' not in parser_nominal_text[1] or \
            'record_static_if_branch_rows("__nominal_type_static_branch", name, token)' not in parser_nominal_text[1]:
        raise SystemExit("Try nominal lookup must receive exact static-branch markers for structs, enums, opaque externs, and exported types")
    error_set_parser = compact_inline(function_section(parser_nominal_text[2], "error_type_declaration"))
    declaration_name_parser = compact_inline(function_section(PARSER_DECLARATION_SOURCE.read_text(), "record_lsp_declaration_name"))
    if not all(fragment in error_set_parser for fragment in (
            "record_lsp_declaration_name(error_set_name, token, name_token, name_token)",
            'record_static_if_branch_rows("__nominal_type_static_branch", error_set_name, token)',
            'owner: "__error_set_decl", name: error_set_name, module: parser.current_module, line: name_token.line, offset: name_token.start')) or not all(fragment in declaration_name_parser for fragment in (
            "offset: declaration_token.start",
            "offset: first_name_token.start")):
        raise SystemExit("Try ErrorSet activity lookup must join the name-token declaration row to the exact keyword-position branch marker")
    parser_try_expression = compact_inline(function_section(parser_source, "get_expression"))
    parser_call_arity = compact_inline(function_section(parser_source, "try_expression_call_arity"))
    parser_try_arguments = compact_inline(function_section(parser_source, "try_expression_record_named_arguments"))
    if not all(fragment in parser_try_arguments for fragment in (
            'marker.owner == "__arg_forward"',
            'owner: "__try_callee_argument_forward"',
            'Ast::Expr.Call(callee, _, _, _)',
            'owner: "__try_callee_argument_direct_call"',
            "call_position.offset",
            "offset: try_offset")):
        raise SystemExit("Try parser metadata must carry forwarding state and direct-call identity from each argument to its Try position")
    forward_try_selector = compact_inline(function_section(source_text, "callable_try_call_forwards_arguments"))
    forward_rows = compact_inline(function_section(source_text, "check_try_fallible_rows"))
    if 'marker.owner == "__try_callee_argument_forward"' not in forward_try_selector or not all(fragment in forward_rows for fragment in (
            "if callable_try_call_forwards_arguments(annotations, annotation.offset):",
            "try_forwarded_parameter_types(table, caller_decl_id, receiver_ref_mutability_known, receiver_ref_mutable)",
            "if forwarded.known:",
            "argument_type_ids <- forwarded.types")):
        raise SystemExit("Try receiver overload ranking must use forwarded argument types only when known")
    if not all(fragment in parser_try_expression for fragment in (
            'owner: "__try_callee_arity"',
            "line: get_token.line",
            "offset: get_token.start",
            "identity_id: call_arity.value",
            "if call_arity.known")) or not all(fragment in parser_call_arity for fragment in (
            "Ast::Expr.Call(_, arguments, _, _)",
            "return (false, 0) if any marker in parser.enum_annotations",
            'marker.owner == "__arg_forward"',
            "return (true, arguments.count.u32())",
            "Ast::Expr.Paren(inner, _)",
            "return parser.try_expression_call_arity(inner)")):
        raise SystemExit("Try calls must retain known positional arity, mark forwarded arity unknown, and recurse through parentheses")
    try_projection = compact_inline(function_section(source_text, "fallible_try_projection_add"))
    try_arity_lookup = compact_inline(function_section(source_text, "try_callee_arity"))
    try_rows = compact_inline(function_section(source_text, "check_try_fallible_rows"))
    if not all(fragment in try_projection for fragment in (
            'annotation.owner == "__try_callee_arity"',
            "projection.try_arities.get(annotation.offset.u64())",
            "projection.try_arities <- projection.try_arities.put(annotation.offset.u64(), annotation.identity_id)")) or not all(fragment in try_arity_lookup for fragment in (
            "index.get(try_offset.u64())",
            "return (true, arity)")) or not all(fragment in try_rows for fragment in (
            "try_callee_arity(try_arities, annotation.offset)",
            "row_arity.value",
            "if row_arity.known else []")):
        raise SystemExit("Try overload ranking must consume the parser's call arity by the exact try-site offset")
    parser_visibility_source = PARSER_VISIBILITY_SOURCE.read_text()
    parser_function_source = PARSER_FUNCTION_SOURCE.read_text()
    if not all(fragment in compact_inline(parser_function_source) for fragment in (
            'owner: function_name, name: "__error_return", line: token.line, offset: token.start',
            'owner: "__fn_module", name: parser.current_module, line: token.line, offset: token.start')):
        raise SystemExit("Try byte-zero return and module rows must retain their parser token offsets")
    section_marker = compact_inline(function_section(parser_visibility_source, "record_section_member"))
    if not all(fragment in section_marker for fragment in (
            '"__section_private" if visibility_name == "private" else "__section_public"',
            "line: member_position.line",
            "offset: member_position.offset",
            "module: owning_module")):
        raise SystemExit("Try declaration visibility requires parser section markers with exact line, offset, and module identity")
    parser_catch_source = compact_inline(function_section(PARSER_CATCH_SOURCE.read_text(), "catch_statement"))
    if 'owner: "__catch_match", name: "__catch_match", line: catch_token.line, offset: catch_token.start, module: parser.current_module' not in parser_catch_source:
        raise SystemExit("statement-catch markers must preserve module identity alongside exact token line and offset")

    family_module = compact_inline(function_section(source_text, "try_error_set_decl_module_for_annotation"))
    root_precedence = 'return (true, family_annotation.name, "", false) if not qualified and try_error_set_decl_has_owner(annotations, family_annotation.name, "")'
    if root_precedence not in family_module or family_module.index(root_precedence) > family_module.index("for declaration in annotations"):
        raise SystemExit("A bare root error-set declaration must win before Try scans lexical module candidates")
    if not all(fragment in family_module for fragment in (
            "(found: bool, uncertain: bool, module: sview @source) = catch_explicit_error_family_module",
            'return (false, family_annotation.name, "", true) if explicit_module.uncertain',
            'return (false, family_annotation.name, "", true) if not qualified and family_path != "" and not catch_module_path_matches(family_path, family_annotation.name)')):
        raise SystemExit("Try must keep uncertain qualified ErrorSet aliases unknown before considering raw module candidates")
    bare_path_guard = 'return (false, family_annotation.name, "", true) if not qualified and family_path != "" and not catch_module_path_matches(family_path, family_annotation.name)'
    root_alias_lookup = 'try_error_alias_index(family_annotation.name, "", table)'
    if family_module.index(bare_path_guard) > family_module.index(root_precedence) or family_module.index(bare_path_guard) > family_module.index(root_alias_lookup):
        raise SystemExit("Try must reject a malformed nonempty bare ErrorSet path before root declaration or alias lookup")
    root_nominal_precedence = 'return (false, family_annotation.name, "", false) if not qualified and function_module_known and try_error_local_nominal_type_shadows_family(annotations, family_annotation.name, function_module, table)'
    if root_nominal_precedence not in family_module or family_module.index(root_nominal_precedence) > family_module.index("try_error_alias_index(family_annotation.name, \"\", table)"):
        raise SystemExit("A root nominal type must shadow lexical and imported same-name ErrorSets before alias candidate lookup")
    alias_target_path = compact_inline(function_section(source_text, "try_error_alias_target_path"))
    if not all(fragment in alias_target_path for fragment in ("Expr.Scope(base, name, _)", "Expr.Paren(inner, _)", "intern_joined_text(bytes, table)")):
        raise SystemExit("Try alias lookup must retain complete qualified and parenthesized AST target paths")
    alias_cycle_guard = compact_inline(function_section(source_text, "try_error_alias_declaration_identity"))
    if not all(fragment in alias_cycle_guard for fragment in (
            "declaration.declaration_id.value",
            "any prior_id in visited where prior_id == declaration.declaration_id.value",
            "visited <- visited.push(declaration.declaration_id.value)",
            "try_error_alias_target_identity(annotations, declaration.target",
            "_ = visited.pop()")):
        raise SystemExit("Try alias resolution must follow TypeAliasDeclaration targets with declaration-identity cycle protection")
    alias_target_identity = compact_inline(function_section(source_text, "try_error_alias_target_identity"))
    if not all(fragment in alias_target_identity for fragment in (
            "try_error_alias_module_path_matches(target_path, target_family",
            "try_error_alias_declaration_identity(annotations, selected_alias, table, visited)",
            "try_error_alias_index(target_family, \"\", table)",
            "try_error_alias_imported_at_scope(annotations, target_family",
            "return try_error_alias_declaration_identity(annotations, selected_imported_alias_index, table, visited) if selected_imported_alias_count == 1.usize()",
            "return (true, selected_imported_family, selected_imported_module, false) if selected_imported_count == 1.usize()")):
        raise SystemExit("Try alias targets must resolve qualified chains, root aliases, and selectively imported aliases to canonical ErrorSet identity")
    import_path_match = compact_inline(function_section(source_text, "try_error_set_import_path_matches"))
    direct_import_visibility = compact_inline(function_section(source_text, "try_error_set_decl_imported_at_scope"))
    alias_visibility = compact_inline(function_section(source_text, "try_error_alias_imported_at_scope"))
    private_alias_path = compact_inline(function_section(source_text, "try_error_alias_module_visible"))
    private_alias_name = compact_inline(function_section(source_text, "try_error_alias_name_visible"))
    generic_return_identity = compact_inline(function_section(source_text, "try_noncall_function_return_is_generic"))
    generic_return_facts = compact_inline(function_section(source_text, "try_noncall_callable_facts_add"))
    if not all(fragment in private_alias_path for fragment in (
            "candidate_module: sview, lexical_module: sview) -> bool",
            "segment: sview = candidate_module[segment_start:segment_end]",
            "owner: sview = candidate_module[0:segment_start - 2.usize()] if segment_start >= 2.usize() else \"\"",
            "private_scope: sview = candidate_module[0:segment_end]")) or "@source" in private_alias_path:
        raise SystemExit("Try private-module visibility must compare temporary path slices without retaining source-region views")

    return {
        'alias_visibility': alias_visibility,
        'direct_import_visibility': direct_import_visibility,
        'generic_return_facts': generic_return_facts,
        'generic_return_identity': generic_return_identity,
        'import_path_match': import_path_match,
        'private_alias_name': private_alias_name,
        'private_alias_path': private_alias_path,
    }
