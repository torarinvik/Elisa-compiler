"""Check global-authority type, alias, and source-location invariants."""


def check_global_authority_source(
    ACTIVE_STATIC_ALIAS_FIXTURE,
    ALIAS_CONFLICT_CHECKER,
    ALIAS_CONFLICT_DIAGNOSTICS,
    NESTED_ALIAS_SCOPE_FIXTURE,
    ALIAS_FIXTURE,
    ALIAS_LATE_CONFLICT_FIXTURE,
    ALIAS_SMOKE,
    FN_VALUE_SIGNATURES,
    IMPL_CONFORMANCE,
    ROOT,
    SAME_TARGET_ALIAS_FIXTURE,
    STATIC_BRANCH_ALIAS_FIXTURE,
    authority_text,
    authority_types_text,
    compact,
    function_section,
    policy_text,
    semantic_text,
):
    for helper_name in ("ga_module", "ga_module_readonly"):
        helper = compact(function_section(authority_text, helper_name))
        if "ga_module_parts_resolve(parts,resolved_scope,state,depth,Ast::expr_pos(expression).offset)" not in helper:
            raise SystemExit(f"{helper_name} drops the source offset while resolving qualified module expressions")
    store_slot = compact(function_section(authority_text, "ga_store_slot"))
    if "ga_module_parts_resolve(module_parts,state.module_scope,state,0,before_offset)" not in store_slot:
        raise SystemExit("global-store module lookup drops its source offset")
    statement_walk = compact(function_section(authority_text, "ga_statements_inner"))
    if "ga_store_slot(clause[0],state,at.offset)" not in statement_walk:
        raise SystemExit("global-store statement lookup does not forward the statement offset")
    permission_slot = compact(function_section(authority_text, "ga_permission_slot"))
    if "ga_text_module(head[0:last_scope],lexical_scope,state,before_offset)" not in permission_slot:
        raise SystemExit("qualified permission lookup drops its source offset")
    coverage = compact(function_section(authority_text, "ga_ref_covers"))
    if "ga_capability_slot(grant,grant_scope,state,grant_before_offset)" not in coverage or "ga_permission_slot(required,required_scope,state,required_before_offset)" not in coverage:
        raise SystemExit("authority coverage does not bind grant and required aliases to their source offsets")
    row_add = compact(function_section(authority_text, "ga_row_add"))
    if "before_offset:u32=GLOBAL_AUTHORITY_OFFSET_NONE" not in row_add or \
            "ga_capability_slot(ref,lexical_scope,state,before_offset)" not in row_add or \
            "ga_permission_slot(ref,lexical_scope,state,before_offset)" not in row_add or \
            "state.capability_offsets[row]" not in row_add:
        raise SystemExit("effect-row normalization drops the source offset while resolving capability and permission aliases")
    row_leaf = compact(function_section(authority_text, "ga_row_add_leaf"))
    if "state.effect_row_offsets.push(before_offset)" not in row_leaf:
        raise SystemExit("normalized effect rows do not retain the source offset used for alias resolution")
    row_replay = compact(function_section(authority_text, "ga_resolve_initial_rows"))
    if "state.effect_row_offsets[row]" not in row_replay:
        raise SystemExit("signature effect-row replay loses its original alias source offset")
    row_close = compact(function_section(authority_text, "ga_close_rows"))
    if "state.effect_row_offsets[row]" not in row_close:
        raise SystemExit("call-graph effect-row propagation loses the originating alias source offset")
    row_publish = compact(function_section(authority_text, "ga_publish_rows"))
    if "effect_row_offsets:darray[u32]&" not in row_publish or \
            "table.effect_canonical_row_offset" not in row_publish:
        raise SystemExit("canonical effect rows do not publish their source offsets")
    generic_rows = compact(function_section(authority_text, "ga_generic_call_rows_at"))
    if "table.effect_canonical_row_offset[row]" not in generic_rows:
        raise SystemExit("call-site effect coverage does not use each normalized row's source offset")
    refs_at = compact(function_section(authority_text, "ga_refs_cover_at"))
    if "offsets[index]" not in refs_at or "ga_ref_covers(grants[index],required" not in refs_at:
        raise SystemExit("stored authority grants are not resolved at their individual declaration offsets")
    lambda_effects = compact(function_section(authority_types_text, "ga_declared_global_members"))
    if 'ga_ref_covers(annotation.name,"Global.Read",ga_module_text(annotation.module,state),0,state,0,annotation.offset' not in lambda_effects or \
            'ga_ref_covers(annotation.name,"Global.Write",ga_module_text(annotation.module,state),0,state,0,annotation.offset' not in lambda_effects:
        raise SystemExit("lambda effect inference drops the annotation source offset")
    fn_value_text = FN_VALUE_SIGNATURES.read_text()
    fn_value_families = compact(function_section(fn_value_text, "fver_type_families"))
    fn_value_rows = compact(function_section(fn_value_text, "fver_canonical_within"))
    if "ga_capability_slot(ref,origin_scope,context,before_offset)" not in fn_value_families or \
            "context.capability_offsets[row]" not in fn_value_families or \
            "table.effect_canonical_row_offset[row]" not in fn_value_rows or \
            "ga_refs_cover_at(expected_refs,expected_scopes,expected_offsets" not in fn_value_rows:
        raise SystemExit("function-value effect comparison drops source offsets from actual or expected alias rows")
    impl_text = IMPL_CONFORMANCE.read_text()
    impl_effects = compact(function_section(impl_text, "imc_protocol_effects"))
    impl_check = compact(function_section(impl_text, "imc_check_effects"))
    if "offsets:mutabledarray[u32]&" not in impl_effects or "offsets.push(effect.offset)" not in impl_effects or \
            "ga_refs_cover_at(allowed,allowed_scopes,allowed_offsets" not in impl_check or \
            "table.effect_canonical_row_offset[row]" not in impl_check:
        raise SystemExit("protocol effect conformance drops source offsets while comparing aliases")
    alias_atom = (ROOT / "test/atoms/authority_coverage.elisa").read_text()
    for probe in (
        'ga_ref_covers("P::Cap.Read", "Old::Cap.Read", 0, 0, &permission_aliases, 0, 125, 125)',
        'ga_ref_covers("P::Cap.Read", "Old::Cap.Read", 0, 0, &permission_aliases, 0, 150, 150)',
        'ga_ref_covers("P::Cap.Read", "New::Cap.Read", 0, 0, &permission_aliases, 0, 150, 150)',
        'return 39 if ga_ref_covers("P::Cap.Read", "Old::Cap.Read", 0, 0, &permission_aliases, 0, 150, 150)',
        'return 40 if not ga_ref_covers("P::Cap.Read", "New::Cap.Read", 0, 0, &permission_aliases, 0, 150, 150)',
        'return 45 if ga_text_module("P", 0, permission_aliases, 150) != new_permission_scope',
        'return 59 if ga_text_module("P::Leaf", 0, permission_aliases, 125) != old_permission_leaf',
        'return 60 if ga_text_module("P::Leaf", 0, permission_aliases, 150) != new_permission_leaf',
        'return 61 if ga_module_alias_resolve("P::Leaf", 0, permission_aliases, 0, true, 125) != old_permission_leaf',
        'return 62 if ga_module_alias_resolve("P::Leaf", 0, permission_aliases, 0, true, 150) != new_permission_leaf',
    ):
        if probe not in alias_atom:
            raise SystemExit(f"authority coverage atom is missing source-order alias probe {probe}")
    for probe in (
        'return 21 if not conflicting_choice.found or conflicting_choice.ambiguous or conflicting_choice.index != 0',
        'return 36 if ga_module_alias_resolve("Alias", 0.usize(), conflicting_aliases) != conflicting_actual',
    ):
        if probe not in alias_atom:
            raise SystemExit(f"authority coverage atom has stale first-registration expectation {probe}")
    for probe in (
        '_ = ga_row_add(0, "Choice", true, &permission_aliases, 0, 0, 150)',
        'return 42 if row_ref != "P::Cap.Read" or row_offset != 120',
        'ga_ref_covers(row_ref, "Old::Cap.Read", 0, 0, &permission_aliases, 0, row_offset, 125)',
        'ga_ref_covers(row_ref, "New::Cap.Read", 0, 0, &permission_aliases, 0, row_offset, 150)',
        'ga_edge_rows(0, 1, &edge_filters)',
        'ga_edge_ref_suppressed(0, "Old::Unsafe", 0, 150, edge_filters)',
        'edge_old_scope: usize = ga_collect_module(0, "Old", edge_filters)',
        'edge_new_scope: usize = ga_collect_module(0, "New", edge_filters)',
        'return 48 if ga_text_module("P", 0, edge_filters, 125) != edge_old_scope',
        'return 49 if ga_text_module("P", 0, edge_filters, 150) != edge_new_scope',
        'return 53 if not tied_conflict.found or tied_conflict.ambiguous or tied_conflict.index != 0',
        'return 54 if ga_module_alias_resolve("Tie::Leaf", 0.usize(), tied_aliases) != tied_actual_leaf',
        'return 55 if ga_text_module("Tie::Leaf", 0.usize(), tied_aliases) != tied_actual_leaf',
        'return 57 if not same_target_tie.found or same_target_tie.ambiguous or same_target_tie.index != 4',
        'return 58 if ga_module_alias_resolve("Same::Leaf", 0.usize(), tied_aliases) != tied_actual_leaf',
    ):
        if probe not in alias_atom:
            raise SystemExit(f"authority coverage atom is missing effect-row alias probe {probe}")
    for probe in (
        'Ast::EnumAnnotation{owner: "__static_if_branch", name: "__using_alias_static_branch", detail_name: "Shared", line: 90, module: "", offset: 90, identity_id: 0}',
        'return 63 if not branch_choice.found or branch_choice.ambiguous or branch_choice.index != 3',
        'return 65 if ga_module_alias_resolve("Shared::Leaf", 0.usize(), branch_aliases) != direct_target_leaf',
        'Ast::EnumAnnotation{owner: "__static_if_branch", name: "__using_alias_static_branch", detail_name: "Shared", line: 91, module: "", offset: 100, identity_id: 1}',
        'static_if_conds: [Ast::Expr.BoolLit(false, alias_branch_at), Ast::Expr.Absent]',
        'static_if_kinds: [StaticIfBranch::Kind.ChainHead, StaticIfBranch::Kind.Fallback]',
        'return 66 if not selected_branch_choice.found or selected_branch_choice.ambiguous or selected_branch_choice.index != 3',
        'unknown_branch_condition: Ast::Expr = Ast::Expr.Scope(Ast::Expr.Ident("Feature", alias_branch_at), "Enabled", alias_branch_at)',
        'return 68 if not unknown_branch_choice.found or not unknown_branch_choice.ambiguous',
        'Ast::Expr.Ident("UNKNOWN_STATIC_CONDITION", alias_branch_at)',
        'return 74 if not unfoldable_fallback_choice.found or unfoldable_fallback_choice.ambiguous or unfoldable_fallback_choice.index != 0',
        'return 75 if not backend_unknown_fallback_choice.found or not backend_unknown_fallback_choice.ambiguous',
        'identity_id: 0},\n                        Ast::EnumAnnotation{owner: "__static_if_branch", name: "__using_alias_static_branch", detail_name: "Shared", line: 92, module: "", offset: 120, identity_id: 1}',
        'static_if_depths: [0, 1]',
        'return 69 if nested_branch_choice.found or nested_branch_choice.ambiguous',
    ):
        if probe not in alias_atom:
            raise SystemExit(f"authority coverage atom is missing static-branch registration probe {probe}")
    for probe in (
        'Ast::EnumAnnotation{owner: "__static_if_branch", name: "__from_member_static_branch", detail_name: "hidden", line: 101, module: "", offset: 101, identity_id: 0}',
        'Ast::EnumAnnotation{owner: "__static_if_branch", name: "__binding_wildcard_import_static_branch", detail_name: "InactiveWildcard", line: 103, module: "", offset: 103, identity_id: 2}',
        'Ast::EnumAnnotation{owner: "__static_if_branch", name: "__binding_wildcard_import_static_branch", detail_name: "ActiveWildcard", line: 104, module: "", offset: 104, identity_id: 3}',
        'Ast::Expr.Ident("UNKNOWN_STATIC_CONDITION", alias_branch_at)',
        'ga_index_import_annotations(&branch_imports)',
        'return 70 if branch_imports.import_annotations.count != 2',
        'return 71 if branch_imports.import_annotations[0].owner != "__from_member" or branch_imports.import_annotations[0].name != "visible"',
        'return 72 if branch_imports.import_annotations[1].name != "__binding_wildcard_import" or branch_imports.import_annotations[1].owner != "ActiveWildcard"',
        'return 77 if not branch_imports.static_import_uncertain',
        'arithmetic_static_condition: Ast::Expr = Ast::Expr.Binary(Ast::Expr.Binary(Ast::Expr.IntLit(1, alias_branch_at), TokenKind.Plus, Ast::Expr.IntLit(1, alias_branch_at), alias_branch_at), TokenKind.EqEq, Ast::Expr.IntLit(2, alias_branch_at), alias_branch_at)',
        'return 73 if not folded_static_condition.known or folded_static_condition.value != 1 or not folded_static_condition.backend_folds',
        'Ast::EnumAnnotation{owner: "__static_if_branch", name: "__const_static_branch", detail_name: "SOURCE_FLAG", line: 106, module: "", offset: 106, identity_id: 0}',
        'Ast::EnumAnnotation{owner: "__static_if_branch", name: "__const_static_branch", detail_name: "SOURCE_FLAG", line: 107, module: "", offset: 107, identity_id: 1}',
        'static_const_names: ["SOURCE_FLAG", "SOURCE_FLAG"]',
        'static_const_lines: [106, 107]',
        'static_const_offsets: [106, 107]',
        'return 76 if not source_const_condition.known or source_const_condition.value != 1 or not source_const_condition.backend_folds',
    ):
        if probe not in alias_atom:
            raise SystemExit(f"authority coverage atom is missing static-import branch-selection probe {probe}")
    alias_fixture = ALIAS_FIXTURE.read_text()
    alias_smoke = ALIAS_SMOKE.read_text()
    if not (
        alias_fixture.index("using Backend::Parent as ParentAlias") <
        alias_fixture.index("using ParentAlias as CapabilityScope") <
        alias_fixture.index("def caller()") <
        alias_fixture.index("can CapabilityScope::Cap.Read")
    ) or "using Backend::Alternate as CapabilityScope" in alias_fixture:
        raise SystemExit("positive qualified permission alias fixture must retain only the chained canonical target")
    if 'run_positive "qualified_permission_using_alias.elisa"' not in alias_smoke:
        raise SystemExit("qualified permission alias fixture is not bound to the Stage1 effect smoke")
    late_alias_conflict_fixture = ALIAS_LATE_CONFLICT_FIXTURE.read_text()
    if not (
        late_alias_conflict_fixture.index("using Backend::Parent as ParentAlias") <
        late_alias_conflict_fixture.index("using ParentAlias as CapabilityScope") <
        late_alias_conflict_fixture.index("def caller()") <
        late_alias_conflict_fixture.index("can CapabilityScope::Cap.Read") <
        late_alias_conflict_fixture.rindex("using Backend::Alternate as CapabilityScope")
    ) or 'run_negative "qualified_permission_late_alias_conflict.neg.elisa" \'conflicting alias: "CapabilityScope" already aliases module "Backend.Parent", cannot also alias "Backend.Alternate"\'' not in alias_smoke:
        raise SystemExit("late alias conflict must be isolated in its own negative fixture and assert the exact conflicting target")
    if not all(fragment in alias_smoke for fragment in (
            'late_permission_alias_log="$WORK/qualified_permission_late_alias_conflict.neg.log"',
            "grep -cF 'conflicting alias:' \"$late_permission_alias_log\") == 1",
            "requires can[Backend::Parent::Cap.Read]",
    )):
        raise SystemExit("late alias conflict smoke must reject extra conflicts and missing facts for the earlier canonical permission owner")
    alias_conflict_source = ALIAS_CONFLICT_CHECKER.read_text()
    alias_conflict_checker = compact(function_section(alias_conflict_source, "check_module_alias_conflicts"))
    alias_target_source = compact(function_section(alias_conflict_source, "ic_module_alias_canonical_target"))
    alias_diagnostic_source = ALIAS_CONFLICT_DIAGNOSTICS.read_text()
    if not all(fragment in alias_conflict_checker for fragment in (
            "forcurrent_aliasintable.definite_import_annotations",
            "is_winner<-falseifnotorder.knownororder.precedes",
            "semantic_possible_import_alias_precedes(possible,winner,table)",
            "semantic_possible_import_alias_precedes(winner,current_alias,table)",
            "current_target.target",
            "winner_target.target",
            "DiagnosticKind.ConflictingModuleAlias")) or \
            "table.binding_import_annotations" not in alias_target_source or \
            "DiagnosticKind.ConflictingModuleAlias" not in alias_diagnostic_source or \
            "push_dot_module_path(buffer,diagnostic.expected)" not in compact(alias_diagnostic_source) or \
            "push_dot_module_path(buffer,diagnostic.actual)" not in compact(alias_diagnostic_source):
        raise SystemExit("module alias conflict diagnostics must compare definite canonical targets by registration order and format dotted owners")
    same_target_alias_fixture = SAME_TARGET_ALIAS_FIXTURE.read_text()
    if same_target_alias_fixture.count("using Target as Shared") != 2 or 'run_positive "global_authority_same_target_aliases.elisa"' not in alias_smoke:
        raise SystemExit("same-target alias repetitions must remain a positive Stage1 control")
    if 'run_positive "global_authority_nested_alias_scope.elisa"' not in alias_smoke:
        raise SystemExit("nested aliases must remain a positive lexical-scope control")
    nested_alias_fixture = NESTED_ALIAS_SCOPE_FIXTURE.read_text()
    if not all(fragment in nested_alias_fixture for fragment in (
            "    using NestedTarget as Shared",
            "\nusing RootTarget as Shared",
            "can NestedTarget::slot.Read:",
            "Parent::call_with_nested_grant()",
            "RootTarget::needs_read()",
    )):
        raise SystemExit("nested alias control must exercise both lexical permission targets")
    static_branch_alias_fixture = STATIC_BRANCH_ALIAS_FIXTURE.read_text()
    static_nested_alias = static_branch_alias_fixture.find("using NestedTarget as Shared")
    static_direct_alias = static_branch_alias_fixture.find("using RootTarget as Shared")
    if "static if true:" not in static_branch_alias_fixture or static_nested_alias < 0 or static_direct_alias < 0 or static_nested_alias >= static_direct_alias or "Shared::slot" not in static_branch_alias_fixture:
        raise SystemExit("static-branch alias fixture no longer covers Core's direct-registration-before-active-branch order")
    if 'run_negative "global_authority_static_branch_alias_conflict.elisa" \'conflicting alias: "Shared" already aliases module "RootTarget", cannot also alias "NestedTarget"\'' not in alias_smoke:
        raise SystemExit("static-branch alias fixture is not bound to the Core first-registration diagnostic")
    if not all(probe in alias_smoke for probe in (
            "grep -cF 'conflicting alias:' \"$static_alias_log\") == 1",
            "requires can[RootTarget::slot.Read]",
            'run_negative "global_authority_static_branch_alias_conflict.elisa"')):
        raise SystemExit("static-branch alias smoke must reject extra conflict or wrong-target authority diagnostics")
    active_static_alias_fixture = ACTIVE_STATIC_ALIAS_FIXTURE.read_text()
    if not all(fragment in active_static_alias_fixture for fragment in (
            "static if false:",
            "using InactiveTarget as Shared",
            "static else:",
            "using ActiveTarget as Shared",
            "can Shared::slot.Read:",
            "ActiveTarget::needs_read()")) or 'run_positive "global_authority_active_static_alias.elisa"' not in alias_smoke:
        raise SystemExit("active-static alias control must prove inactive arms do not shadow the selected permission target")

    row_edges = compact(function_section((ROOT / "src/semantic/check_global_authority_rows.elisa").read_text(), "ga_edge_rows"))
    row_filter_check = compact(function_section((ROOT / "src/semantic/check_global_authority_rows.elisa").read_text(), "ga_edge_ref_suppressed"))
    if "row_edge_filter_offsets.push(state.firewall_offsets[index])" not in row_edges or \
            "state.row_edge_filter_offsets[filter]" not in row_filter_check:
        raise SystemExit("call-graph firewall snapshots drop their source offsets")

    policy_body = compact(function_section(policy_text, "pattern_binding_origin"))
    expected_policy = compact("""
def pattern_binding_origin(contains_reference: bool, source_origin: usize) -> usize:
    ensure result == (
        NO_ORIGIN if not contains_reference else
        (source_origin if source_origin != NO_ORIGIN else UNKNOWN_ALIAS)
    )
    return NO_ORIGIN if not contains_reference
    return source_origin if source_origin != NO_ORIGIN
    return UNKNOWN_ALIAS
""")
    if policy_body != expected_policy:
        raise SystemExit("production binder-origin policy changed from its exact origin-preservation rule")
    join_body = compact(function_section(policy_text, "join_reference_origins"))
    expected_join = compact("""
def join_reference_origins(left: usize, right: usize) -> usize:
    ensure result == (
        right if left == NO_ORIGIN else
        (left if right == NO_ORIGIN else
            (left if left == right else UNKNOWN_ALIAS))
    )
    return right if left == NO_ORIGIN
    return left if:
        right == NO_ORIGIN
        left == right
    return UNKNOWN_ALIAS
""")
    if join_body != expected_join:
        raise SystemExit("production reference-origin join changed from its exact conservative lattice rule")
    opaque_body = compact(function_section(policy_text, "opaque_expression_origin"))
    expected_opaque = compact("""
def opaque_expression_origin(type_known: bool, contains_reference: bool) -> usize:
    ensure result == (UNKNOWN_ALIAS if not type_known or contains_reference else NO_ORIGIN)
    return UNKNOWN_ALIAS if:
        not type_known
        contains_reference
    return NO_ORIGIN
""")
    if opaque_body != expected_opaque:
        raise SystemExit("opaque-expression origin policy must preserve unknown or reference-bearing values")
    constructor_body = compact(function_section(policy_text, "constructor_origin"))
    expected_constructor = compact("""
def constructor_origin(summary: usize, reference_fields_complete: bool) -> usize:
    ensure result == (summary if reference_fields_complete else UNKNOWN_ALIAS)
    return summary if reference_fields_complete
    return UNKNOWN_ALIAS
""")
    if constructor_body != expected_constructor:
        raise SystemExit("incomplete reference-bearing constructors must discard partial origin summaries")
    permission_body = compact(function_section(policy_text, "unknown_alias_permission"))
    expected_permission = compact('''
def unknown_alias_permission(write: bool) -> sview:
    ensure result == ("Global.Write" if write else "Global.Read")
    return "Global.Write" if write else "Global.Read"
''')
    if permission_body != expected_permission:
        raise SystemExit("production unknown-alias permission mapping changed from its exact read/write rule")
    conservative_origin_body = compact(function_section(policy_text, "requires_unknown_alias_permission"))
    expected_conservative_origin = compact('''
def requires_unknown_alias_permission(origin: usize) -> bool:
    ensure result == (origin == NO_ORIGIN or origin == UNKNOWN_ALIAS)
    return origin == NO_ORIGIN or origin == UNKNOWN_ALIAS
''')
    if conservative_origin_body != expected_conservative_origin:
        raise SystemExit("missing and unknown origins must use the exact fail-closed access classification")

    policy_include = 'include "./global_authority_origin_policy.elisa"'
    authority_include = 'include "./check_global_authority.elisa"'
    if policy_include not in semantic_text or authority_include not in semantic_text or \
            semantic_text.index(policy_include) > semantic_text.index(authority_include):
        raise SystemExit("semantic facade must load the proved origin policy before global authority")

    pattern_metadata = compact(function_section(authority_text, "ga_pattern_binding_metadata"))
    metadata_steps = (
        "is_reference: bool = ga_type_id_is_reference(binding_type_id, table) or (binding_type_id == 0 and whole_value and ga_expression_is_reference(subject, state, 0))",
        "contains_reference: mutable bool = ga_type_id_contains_reference(binding_type_id, table) or is_reference",
        "source_origin: usize = ga_reference_origin(subject, state, 0) if contains_reference else GLOBAL_AUTHORITY_NONE",
        "global_origin: mutable usize = SemanticGlobalAuthorityOrigin::pattern_binding_origin(contains_reference, source_origin)",
        "global_origin <- GLOBAL_AUTHORITY_LOCAL_ALIAS if contains_reference and source_origin == GLOBAL_AUTHORITY_NONE",
        "return (type_expression, global_origin, type_scope)",
    )
    metadata_positions = [pattern_metadata.find(compact(fragment)) for fragment in metadata_steps]
    if any(position < 0 for position in metadata_positions) or metadata_positions != sorted(metadata_positions):
        raise SystemExit("match-pattern binding no longer forwards its type and source origin through the proved policy")
    if "iftype_expressionisbinding_type_expression:contains_reference<-contains_referenceorga_type_expression_contains_reference(binding_type_expression,state,0)" not in pattern_metadata:
        raise SystemExit("match binders must classify nested references in named aggregate types")
    if "return(type_expression,GLOBAL_AUTHORITY_NONE)" in pattern_metadata or \
            "return(type_expression,GLOBAL_AUTHORITY_UNKNOWN_ALIAS)" in pattern_metadata:
        raise SystemExit("match-pattern origin bypasses the proved policy with an unconditional fallback")

    expression_walk = compact(function_section(authority_text, "ga_expression_inner"))
    statement_walk = compact(function_section(authority_text, "ga_statements_inner"))
    if "ga_type_id_contains_reference(binding_type_id,table)" not in expression_walk or \
            "iterable_origin:usize=ga_reference_origin(iterable,state,0)" not in expression_walk or \
            "SemanticGlobalAuthorityOrigin::pattern_binding_origin(binding_has_references,iterable_origin)" not in expression_walk or \
            "SemanticGlobalAuthorityOrigin::pattern_binding_origin(extra_binding_has_references[extra_index],iterable_origin)" not in expression_walk or \
            "ga_iteration_binding_type_expression(iterable,binding_type_id" not in expression_walk:
        raise SystemExit("comprehension binders must preserve each item type and reference-origin summary")
    if "ga_type_id_contains_reference(binding_type_id,table)" not in statement_walk or \
            "iterable_origin:usize=ga_reference_origin(iterable,state,0)" not in statement_walk or \
            "binding_reference_flags.push(binding_has_references)" not in statement_walk or \
            "SemanticGlobalAuthorityOrigin::pattern_binding_origin(binding_reference_flags[binding_index],iterable_origin)" not in statement_walk or \
            "ga_iteration_binding_type_expression(iterable,binding_type_id" not in statement_walk:
        raise SystemExit("loop binders must preserve each item type and reference-origin summary")
    arms_body = compact(function_section(authority_text, "ga_arms_inner"))
    if "state.local_global_origins.push(metadata.global_origin)" not in arms_body:
        raise SystemExit("match-arm binders no longer retain the proved origin metadata")

    access_body = compact(function_section(authority_text, "ga_access"))
    if "elifSemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(alias_origin):table<-ga_access_unknown_alias(Ast::expr_pos(expression),write,state,table)canGlobal{Read,Write}" not in access_body:
        raise SystemExit("unknown binder origins no longer route accesses through conservative authority requirements")
    if "ifga_expression_is_reference(expression,state,0):ifalias_origin<state.globals.count:" not in access_body:
        raise SystemExit("aggregate origin summaries must not be mistaken for direct global accesses")
    rebind_body = compact(function_section(authority_text, "ga_statements_inner"))
    if "origin:usize=ga_update_reference_origin(target,value,state)" not in rebind_body or \
            "iforigin<state.globals.count:table<-ga_access_slot(origin,Ast::expr_pos(value),true,false,state,table)canGlobal{Read,Write}" not in rebind_body:
        raise SystemExit("reference rebinds must retain their new origin and charge writes to exact global roots")
    rebind_origin = compact(function_section(authority_text, "ga_update_reference_origin"))
    if "source_origin:usize=ga_reference_rebind_origin(value,state,0)" not in rebind_origin or \
            "state.local_global_origins[local_index]<-ga_join_origins(state,previous_origin,source_origin)" not in rebind_origin or \
            "returnstate.local_global_origins[local_index]" not in rebind_origin or \
            "returnGLOBAL_AUTHORITY_UNKNOWN_ALIASifleft==GLOBAL_AUTHORITY_UNKNOWN_ALIASorright==GLOBAL_AUTHORITY_UNKNOWN_ALIAS" not in compact(function_section(authority_text, "ga_join_origins")):
        raise SystemExit("reference rebinds must preserve unresolved aliases for conservative checks at later access")
    write_place_body = compact(function_section(authority_text, "ga_write_place_inner"))
    if "ifga_expression_is_reference(expression,state,0):table<-ga_access(expression,true,state,table)canGlobal{Read,Write}" not in write_place_body:
        raise SystemExit("writes through typed aggregate reference fields must consult their preserved origin")
    origin_walk = compact(function_section(authority_text, "ga_reference_origin"))
    for fragment in (
        "Expr.Array(elements,_)|Expr.Tuple(elements,_)|Expr.SetLit(elements,_) ",
        "ga_join_origins(state,origin,element_origin)",
        "ga_join_origins(state,origin,key_origin)",
        "ga_join_origins(state,origin,value_origin)",
    ):
        if compact(fragment) not in origin_walk:
            raise SystemExit("aggregate reference-origin summaries no longer join all contained value origins")
    join_origins = compact(function_section(authority_text, "ga_join_origins"))
    for fragment in (
        "joined:usize=SemanticGlobalAuthorityOrigin::join_reference_origins(left,right)",
        "returnjoinedifjoined!=GLOBAL_AUTHORITY_UNKNOWN_ALIAS",
        "returnGLOBAL_AUTHORITY_UNKNOWN_ALIASifleft==GLOBAL_AUTHORITY_UNKNOWN_ALIASorright==GLOBAL_AUTHORITY_UNKNOWN_ALIAS",
        "returnGLOBAL_AUTHORITY_UNKNOWN_ALIASifleft<state.globals.countorright<state.globals.count",
        "returnGLOBAL_AUTHORITY_LOCAL_ALIAS",
    ):
        if fragment not in join_origins:
            raise SystemExit("authority origin joins must keep known global and unknown aliases conservative")
    local_address = compact(function_section(authority_text, "ga_local_address_origin"))
    for fragment in (
        "returnga_local_origin(local_index,state)ifnotprojected",
        "returnga_local_origin(local_index,state)ifnotga_reference_type(root_type,state,0)",
    ):
        if fragment not in local_address:
            raise SystemExit("direct borrows of local storage must preserve the encoded local-root identity")
    local_origin = compact(function_section(authority_text, "ga_local_origin"))
    local_origin_guard = compact("""
return GLOBAL_AUTHORITY_UNKNOWN_ALIAS if:
    identity >= GLOBAL_AUTHORITY_LOCAL_ALIAS or state.globals.count >= GLOBAL_AUTHORITY_LOCAL_ALIAS
    identity >= GLOBAL_AUTHORITY_LOCAL_ALIAS - state.globals.count
""")
    if "identity:usize=state.local_origin_ids[local_index]" not in local_origin or \
            local_origin_guard not in local_origin or \
            "returnstate.globals.count+identity" not in local_origin:
        raise SystemExit("encoded local roots must stay below the reserved alias ceiling and fail closed on overflow")
    push_local_origin = compact(function_section(authority_text, "ga_push_local_origin_id"))
    if "state.local_origin_ids.push(GLOBAL_AUTHORITY_LOCAL_ALIAS)" not in push_local_origin or \
            "state.next_local_origin_id<GLOBAL_AUTHORITY_LOCAL_ALIAS-state.globals.count" not in push_local_origin:
        raise SystemExit("local-origin allocation must reserve its ceiling for fail-closed overflow")
    opaque_origin = compact(function_section(authority_text, "ga_expression_reference_origin"))
    if "SemanticGlobalAuthorityOrigin::opaque_expression_origin(true,ga_type_expression_contains_reference(annotation,state,depth+1))" not in opaque_origin or \
            "SemanticGlobalAuthorityOrigin::opaque_expression_origin(false,false)" not in opaque_origin:
        raise SystemExit("opaque expression origins must use the proved fail-closed policy")
    if "ga_expression_reference_origin(expression,state,depth+1)" not in origin_walk:
        raise SystemExit("opaque or reference-bearing values must not disappear from aggregate origin summaries")
    if "SemanticGlobalAuthorityOrigin::constructor_origin(origin,false)" not in origin_walk or \
            "SemanticGlobalAuthorityOrigin::constructor_origin(origin,true)" not in origin_walk:
        raise SystemExit("struct constructor summaries must pass through the proved field-coverage rule")
    constructor_coverage = compact(function_section(authority_text, "ga_construct_omits_reference_field"))
    for fragment in (
        "returntrueifowner>=state.struct_names.count",
        "continueifstate.field_owners[field_index]!=state.struct_names[owner]orstate.field_scopes[field_index]!=state.struct_scopes[owner]",
        'returntrueifinitializer.name==""andnotinitializer.is_copy_base',
        "found<-trueifinitializer.name==state.field_names[field_index]",
        "returntrueifnotfound",
    ):
        if fragment not in constructor_coverage:
            raise SystemExit("constructor completeness must fail closed on omitted or unresolved reference fields")
    collection = compact(function_section(authority_text, "ga_collect"))
    for fragment in (
        "Decl.Enum(name: name, variants: variants, _):",
        "state.enum_variant_owners.push(name)",
        "state.enum_variant_payload_starts.push(state.enum_variant_payload_types.count)",
        "state.enum_variant_payload_counts.push(variant.fields.count)",
        "state.enum_variant_payload_types.push(variant.fields[field_index])",
        "state.enum_variant_payload_names.push(variant.field_names[field_index]iffield_index<variant.field_names.countelsesview(\"\",0,0))",
    ):
        if compact(fragment) not in collection:
            raise SystemExit("enum constructor origin summaries must bind to declared lexical payload layouts")
    variant_slot = compact(function_section(authority_text, "ga_enum_variant_slot"))
    if "ga_resolve_indexed(ga_type_head(owner_expression),ga_type_scope(owner_expression,state),ga_type_qualified(owner_expression),state.enum_names,state.enum_scopes,state.enum_heads,state.enum_next,state)" not in variant_slot or \
            "state.enum_variant_owners[variant_slot]==state.enum_names[enum_slot]" not in variant_slot or \
            "state.enum_variant_scopes[variant_slot]==state.enum_scopes[enum_slot]" not in variant_slot or \
            "state.enum_variant_names[variant_slot]==variant_name" not in variant_slot or \
            "ga_local_slot(owner_name,state)<state.locals.count" not in variant_slot:
        raise SystemExit("enum constructor recognition must require its resolved owner and exact variant")
    variant_origin = compact(function_section(authority_text, "ga_enum_constructor_origin"))
    for fragment in (
        "arguments.count!=state.enum_variant_payload_counts[variant_slot]",
        "SemanticGlobalAuthorityOrigin::constructor_origin(GLOBAL_AUTHORITY_NONE,false)",
        "payload_count>state.enum_variant_payload_names.count-payload_start",
        "forargument_indexin0..<arguments.count:",
        "forpayload_indexinpayload_start..<payload_start+payload_count:",
        "found<-trueifstate.enum_variant_payload_names[payload_index]==label",
        "returnSemanticGlobalAuthorityOrigin::constructor_origin(GLOBAL_AUTHORITY_NONE,false)ifnotfound",
        "ga_reference_origin(argument,state,depth+1)",
        "ga_join_origins(state,origin,argument_origin)",
        "SemanticGlobalAuthorityOrigin::constructor_origin(origin,true)",
    ):
        if fragment not in variant_origin:
            raise SystemExit("enum payload origin summaries must join the exact constructor arguments and fail closed")
    if 'Expr.Call(callee,arguments,labels,_):returnGLOBAL_AUTHORITY_NONEifident_name_of(callee)=="raise"' not in origin_walk or \
            "variant_slot:usize=ga_enum_variant_slot(callee,state)" not in origin_walk or \
            "returnga_enum_constructor_origin(variant_slot,arguments,labels,state,depth+1)ifvariant_slot<state.enum_variant_names.count" not in origin_walk:
        raise SystemExit("only resolved enum constructors may expose their payload origins")
    type_expression_classifier = compact(function_section(authority_types_text, "ga_type_expression_contains_reference"))
    if "returntrueifga_reference_type(resolved,state,depth+1)" not in type_expression_classifier or \
            "owner:usize=ga_known_struct(resolved,state.module_scope,state,depth+1)" not in type_expression_classifier or \
            "returntrueif:state.field_scopes[index]!=state.module_scopega_type_expression_contains_reference(state.field_types[index],state,depth+1)" not in type_expression_classifier or \
            "ga_type_expression_contains_reference(state.enum_variant_payload_types[payload_index],state,depth+1)" not in type_expression_classifier:
        raise SystemExit("reference classification must recurse through named aggregate and enum payload fields")
    contains_refs = compact(function_section(authority_text, "ga_type_id_contains_reference"))
    if "kind!=SemTypeKind.Optionalandkind!=SemTypeKind.Tupleandkind!=SemTypeKind.Container" not in contains_refs or \
            "ga_type_id_contains_reference(interned_elem(type_id,element_index,table),table,depth+1)" not in contains_refs:
        raise SystemExit("binder reference detection must recurse through tuples and container element types")
    tuple_annotation = compact(function_section(authority_types_text, "ga_tuple_field_type"))
    if 'annotation.owner=="__tuple_label"andannotation.name==field' not in tuple_annotation:
        raise SystemExit("named-tuple field annotations must be available to the global-authority type walk")
