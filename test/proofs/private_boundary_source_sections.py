"""Collect and validate private-module source sections."""
import re


def collect_private_source_sections(
    MODULE_ALIAS_PRECEDENCE,
    UNKNOWN_STATIC_IMPORT_SMOKE,
    check_construct_field_type_text,
    check_named_type_mismatch_text,
    check_private_fields_types_text,
    check_readonly_ref_text,
    compact,
    consumer_text,
    diagnostic_output_text,
    function_section,
    import_visibility_text,
    parser_text,
    resolve_binding_capabilities_text,
    resolve_enum_owners_text,
    resolve_expr_walk_context_text,
    resolve_expr_walk_text,
    resolve_scope_text,
    semantic_text,
    source_text,
    symbols_hash_index_text,
    symbols_text,
    table_setup_text,
):
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
    wildcard_index_build = compact(function_section(consumer_text, "pma_build_wildcard_import_index"))
    wildcard_visibility = compact(function_section(consumer_text, "pma_visible_wildcard_import"))
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
    static_if_const_branch_wrapper = compact(function_section(consumer_text, "pma_static_if_const_branch_selection"))
    static_if_const_branch_selection = compact(function_section(consumer_text, "pma_static_if_const_branch_rows"))
    static_if_function_branch_wrapper = compact(function_section(consumer_text, "pma_static_if_function_branch_selection"))
    static_if_function_branch_selection = compact(function_section(consumer_text, "pma_static_if_function_branch_rows"))
    static_if_qualified_module_matches = compact(function_section(consumer_text, "pma_static_if_qualified_module_matches"))
    static_if_row_selection = compact(function_section(consumer_text, "pma_static_if_row_selection"))
    static_if_row_for_position = compact(function_section(consumer_text, "pma_static_if_row_for_position"))
    import_branch_selection = compact(function_section(consumer_text, "pma_import_branch_selection"))
    using_alias_for_using = compact(function_section(consumer_text, "pma_using_alias_for_using_row"))
    import_annotation_branch_selection = compact(function_section(consumer_text, "pma_import_annotation_branch_selection_indexed"))
    import_annotation_branch_wrapper = compact(function_section(consumer_text, "pma_import_annotation_branch_selection"))
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

    if 'index.wildcard_rows.push(row)ifannotations[row].name=="__binding_wildcard_import"' not in wildcard_index_build or not all(fragment in wildcard_visibility for fragment in (
            'forrowinindex.wildcard_rows:',
            'annotation:Ast::EnumAnnotation=annotations[row]',
            'annotation.owner!=ownerornotpma_import_scope_visible(current_module,annotation.module)')):
        raise SystemExit("wildcard row projection must preserve exact annotations and lexical visibility")

    # The indexed wrappers and the row walkers jointly implement branch selection.
    # Require both the guarded projection and the complete-source fallback; inspecting
    # only the wrapper misses the row identity/unknown-branch checks after extraction.
    for kind, wrapper in (("const", static_if_const_branch_wrapper), ("function", static_if_function_branch_wrapper)):
        helper = "pma_static_if_" + kind + "_branch_rows"
        if not all(fragment in wrapper for fragment in (
                "table.static_if_branch_source_count==file.enum_annotations.countandfile.enum_annotations.count>0",
                helper + "(table.static_if_branch_annotations,file,name,symbol,table,depth)",
                helper + "(file.enum_annotations,file,name,symbol,table,depth)")):
            raise SystemExit("static-if selection must validate its indexed rows and retain the complete-source fallback")
    static_if_projection = compact(function_section(consumer_text, "fill_static_if_branch_annotations"))
    if not all(fragment in static_if_projection for fragment in (
            "table.static_if_branch_annotations<-[]",
            'table.static_if_branch_annotations.push(annotation)ifannotation.owner=="__static_if_branch"',
            "table.static_if_branch_source_count<-file.enum_annotations.count")):
        raise SystemExit("static-if annotation projection must preserve complete exact branch rows")

    if not all(fragment in private_import_visibility for fragment in (
            'pma_visible_wildcard_import(index,annotations,current_module,owner,false)',
            "pma_selective_import_target_status(annotations,current_module,owner,member)",
            "target.foundand(nottarget.knownortarget.first)")) or not all(fragment in public_import_visibility for fragment in (
            'pma_visible_wildcard_import(index,annotations,current_module,owner,true)',
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
            'pma_import_annotation_branch_selection_indexed(annotation,relevant,markers,file,table)',
            'markers.push(candidate)ifcandidate.owner=="__static_if_branch"',
            'branch_rowandmarkers.count>0',
            'candidate.owner=="__from_member"',
            'candidate.owner=="__private_member_module"',
            'candidate.name=="__using"',
            'candidate.name=="__using_alias"',
            'candidate.name=="__using_alias_target"',
            'owner:"__pma_unknown_static_import"',
            'annotation.name=="__using_alias"',
            'notbranch.known')):
        raise SystemExit("PMA import visibility must filter known-inactive rows and mark unresolved static-arm imports as uncertain")

    return {
        'active_import_annotations': active_import_annotations,
        'alias_chain_match': alias_chain_match,
        'alias_chain_prefix_match': alias_chain_prefix_match,
        'alias_member_builder': alias_member_builder,
        'alias_precedence': alias_precedence,
        'alias_shadowed': alias_shadowed,
        'alias_target_matches_owner': alias_target_matches_owner,
        'argument_type_probe': argument_type_probe,
        'binding_import_builder': binding_import_builder,
        'binding_nominal_lookup': binding_nominal_lookup,
        'build_import_views': build_import_views,
        'call_index_walker': call_index_walker,
        'call_target_normalizer': call_target_normalizer,
        'candidate_module_visibility': candidate_module_visibility,
        'construct_call_lookup': construct_call_lookup,
        'enum_owner_lookup': enum_owner_lookup,
        'import_alias_global_winner': import_alias_global_winner,
        'import_alias_pair_target': import_alias_pair_target,
        'import_alias_target_canonical_owner': import_alias_target_canonical_owner,
        'import_alias_target_global_winner': import_alias_target_global_winner,
        'import_annotation_branch_selection': import_annotation_branch_selection,
        'import_annotation_branch_wrapper': import_annotation_branch_wrapper,
        'import_using_row_alias_pair': import_using_row_alias_pair,
        'module_alias_precedence_text': module_alias_precedence_text,
        'named_struct_lookup': named_struct_lookup,
        'named_type_spelling_unique': named_type_spelling_unique,
        'possible_import_alias': possible_import_alias,
        'possible_import_alias_branch': possible_import_alias_branch,
        'possible_import_alias_branch_marker_at': possible_import_alias_branch_marker_at,
        'possible_import_alias_branch_marker_count': possible_import_alias_branch_marker_count,
        'possible_import_alias_branch_stack': possible_import_alias_branch_stack,
        'possible_import_alias_definite': possible_import_alias_definite,
        'possible_import_alias_dependency': possible_import_alias_dependency,
        'possible_import_alias_head_target': possible_import_alias_head_target,
        'possible_import_alias_module_path': possible_import_alias_module_path,
        'possible_import_alias_order': possible_import_alias_order,
        'possible_import_alias_position': possible_import_alias_position,
        'possible_import_alias_precedence': possible_import_alias_precedence,
        'possible_import_alias_target_alias_matches': possible_import_alias_target_alias_matches,
        'possible_import_alias_target_head_status': possible_import_alias_target_head_status,
        'possible_import_alias_target_matches': possible_import_alias_target_matches,
        'possible_import_alias_target_prefix': possible_import_alias_target_prefix,
        'possible_import_alias_target_row_can_win': possible_import_alias_target_row_can_win,
        'possible_import_import_row_member': possible_import_import_row_member,
        'possible_import_member_owner': possible_import_member_owner,
        'possible_import_member_visible': possible_import_member_visible,
        'possible_import_module_member': possible_import_module_member,
        'possible_import_module_path': possible_import_module_path,
        'possible_import_module_path_alias_member': possible_import_module_path_alias_member,
        'possible_import_module_path_alias_module': possible_import_module_path_alias_module,
        'possible_import_module_path_candidate': possible_import_module_path_candidate,
        'possible_import_module_path_member': possible_import_module_path_member,
        'possible_import_module_path_module_candidate': possible_import_module_path_module_candidate,
        'possible_import_module_path_suffix': possible_import_module_path_suffix,
        'possible_import_module_symbol_alias': possible_import_module_symbol_alias,
        'possible_import_module_visible': possible_import_module_visible,
        'possible_import_name_visible': possible_import_name_visible,
        'possible_import_type_path_candidate': possible_import_type_path_candidate,
        'possible_import_type_selection': possible_import_type_selection,
        'prepare_symbol_table': prepare_symbol_table,
        'private_candidate_rank': private_candidate_rank,
        'private_field_owner_lookup': private_field_owner_lookup,
        'private_index_init': private_index_init,
        'private_record': private_record,
        'private_report': private_report,
        'public_call_sibling_rank': public_call_sibling_rank,
        'readonly_callee_lookup': readonly_callee_lookup,
        'resolver_module_alias': resolver_module_alias,
        'resolver_name_classification': resolver_name_classification,
        'resolver_name_known': resolver_name_known,
        'resolver_qualified_alias_uncertainty': resolver_qualified_alias_uncertainty,
        'resolver_wildcard_uncertainty': resolver_wildcard_uncertainty,
        'scope_owner': scope_owner,
        'selective_import_status': selective_import_status,
        'static_if_function_branch_selection': static_if_function_branch_selection,
        'static_if_row_for_position': static_if_row_for_position,
        'synthetic_import_marker': synthetic_import_marker,
        'unknown_static_import_smoke_text': unknown_static_import_smoke_text,
        'unresolved_references_setup': unresolved_references_setup,
        'unresolved_table_setup': unresolved_table_setup,
        'using_alias_target': using_alias_target,
        'wildcard_import_builder': wildcard_import_builder,
        'wildcard_visibility': wildcard_visibility,
    }
