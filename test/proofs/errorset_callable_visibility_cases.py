"""Check errorset callable visibility and overload regression fixtures."""


def check_callable_visibility_fixtures(
    ROOT,
    EWR,
    PARSER,
    binding_scope,
    fallible_selection,
    function_source,
    inaccessible_binding_scope,
    ordinary_binding,
):
    for fixture_name, smoke_name in (
        ("errorset_wrapper_return_public_sibling_same_line.elisa", "errorset_wrapper_return_public_sibling_same_line_smoke.sh"),
        ("errorset_wrapper_return_overloaded_expr.elisa", "errorset_wrapper_return_overloaded_expr_smoke.sh"),
        ("errorset_wrapper_return_defaulted_overflow_rank.elisa", "errorset_wrapper_return_defaulted_overflow_rank_smoke.sh"),
        ("errorset_wrapper_return_defaulted_underflow_rank.elisa", "errorset_wrapper_return_defaulted_underflow_rank_smoke.sh"),
        ("errorset_wrapper_return_later_argument_mismatch_rank.elisa", "errorset_wrapper_return_later_argument_mismatch_rank_smoke.sh"),
        ("errorset_wrapper_return_singleton_overflow_rank.elisa", "errorset_wrapper_return_singleton_overflow_rank_smoke.sh"),
        ("errorset_wrapper_return_singleton_type_mismatch.elisa", "errorset_wrapper_return_singleton_type_mismatch_smoke.sh"),
        ("errorset_wrapper_return_named_call_infallible_underflow.elisa", "errorset_wrapper_return_named_call_infallible_underflow_smoke.sh"),
        ("errorset_wrapper_return_variadic_arguments.elisa", "errorset_wrapper_return_variadic_arguments_smoke.sh"),
        ("errorset_wrapper_return_variadic_extern.elisa", "errorset_wrapper_return_variadic_extern_smoke.sh"),
        ("errorset_wrapper_return_private_callable.elisa", "errorset_wrapper_return_private_callable_smoke.sh"),
        ("errorset_wrapper_return_private_extern.elisa", "errorset_wrapper_return_private_extern_smoke.sh"),
        ("errorset_wrapper_return_private_import.elisa", "errorset_wrapper_return_private_import_smoke.sh"),
        ("errorset_wrapper_return_private_overload_rank.elisa", "errorset_wrapper_return_private_overload_rank_smoke.sh"),
        ("errorset_wrapper_return_nonviable_local_scope_control.elisa", "errorset_wrapper_return_nonviable_local_scope_control_smoke.sh"),
        ("errorset_wrapper_return_nested_wildcard_scope_control.elisa", "errorset_wrapper_return_nested_wildcard_scope_control_smoke.sh"),
        ("errorset_wrapper_return_cross_module_singleton_specificity.elisa", "errorset_wrapper_return_cross_module_singleton_specificity_smoke.sh"),
        ("errorset_wrapper_return_private_primary_named_args.elisa", "errorset_wrapper_return_private_primary_named_args_smoke.sh"),
        ("errorset_wrapper_return_inherited_wildcard_precedence.elisa", "errorset_wrapper_return_inherited_wildcard_precedence_smoke.sh"),
        ("errorset_wrapper_return_ambiguous_outer_nested_using.elisa", "errorset_wrapper_return_ambiguous_outer_nested_using_smoke.sh"),
        ("errorset_wrapper_return_lexical_singleton_over_imported_singleton.elisa", "errorset_wrapper_return_lexical_singleton_over_imported_singleton_smoke.sh"),
    ):
        fixture = ROOT / "test/repro" / fixture_name
        smoke = ROOT / "test/parity" / smoke_name
        if not fixture.is_file() or not smoke.is_file() or fixture_name not in smoke.read_text():
            raise SystemExit(f"EWR regression coverage must retain its fixture and parity smoke: {fixture_name}")

    same_line_visibility_fixture = (ROOT / "test/repro/errorset_wrapper_return_public_sibling_same_line.elisa").read_text()
    if same_line_visibility_fixture.count("#line 9 ") != 2 or same_line_visibility_fixture.count("def dispatch(") != 2:
        raise SystemExit("EWR visibility regression must place both private and public overload declarations on one #line")

    overloaded_expr_fixture = (ROOT / "test/repro/errorset_wrapper_return_overloaded_expr.elisa").read_text()
    overloaded_expr_smoke = (ROOT / "test/parity/errorset_wrapper_return_overloaded_expr_smoke.sh").read_text()
    if not all(fragment in overloaded_expr_fixture for fragment in (
            "def choose_pair(value: i64, marker: i64) -> i64 error[PairProvider::Fault{Available}]",
            "def choose_pair[T](value: T, marker: bool) -> i64 error[PairProvider::Fault{Busy}]",
            "first_argument_controls_overload() -> i64 error[PairProvider::Fault{Busy}]",
            "return PairProvider::wrap_value_for_family(PairProvider::choose_pair(1, true))")) or not all(fragment in overloaded_expr_smoke for fragment in (
            "expected_rows=$'L20\\nL45'",
            'L45 argument 2 to "PairProvider.choose_pair" expects i64, got bool',
            'stage0_rows" != "$expected_rows"',
            'stage1_rows" != "$expected_rows"')):
        raise SystemExit("Qualified EWR overload coverage must preserve the concrete first-argument ErrorSet through a later argument mismatch and reject its narrower wrapper")
    generic_overload_position = overloaded_expr_fixture.find("def choose_pair[T](value: T, marker: bool)")
    concrete_overload_position = overloaded_expr_fixture.find("def choose_pair(value: i64, marker: i64)")
    if generic_overload_position < 0 or concrete_overload_position <= generic_overload_position:
        raise SystemExit("Qualified EWR coverage must put the generic candidate first so the concrete family depends on Core's first-argument receiver ranking")
    generic_pair_position = overloaded_expr_fixture.find("def choose_pair[T](value: T, marker: bool)")
    concrete_pair_position = overloaded_expr_fixture.find("def choose_pair(value: i64, marker: i64)")
    if generic_pair_position < 0 or concrete_pair_position < 0 or generic_pair_position >= concrete_pair_position:
        raise SystemExit("Qualified EWR coverage must put the generic overload first so the concrete result proves Core receiver ranking")

    private_import_fixture = (ROOT / "test/repro/errorset_wrapper_return_private_import.elisa").read_text()
    private_import_smoke = (ROOT / "test/parity/errorset_wrapper_return_private_import_smoke.sh").read_text()
    if not all(fragment in private_import_fixture for fragment in (
            "private:",
            "def wrap[errorset R](callback: fn() -> i64 error[R])",
            "from Provider import wrap",
            "return wrap(origin)")) or not all(fragment in private_import_smoke for fragment in (
            '"AliasInstaller.Provider.wrap" is private to module "AliasInstaller.Provider"',
            "! grep -q 'cannot propagate'")):
        raise SystemExit("EWR private-import coverage must retain the inaccessible wrapper and suppress a spurious propagation mismatch")

    singleton_fixture = (ROOT / "test/repro/errorset_wrapper_return_lexical_singleton_over_imported_singleton.elisa").read_text()
    singleton_smoke = (ROOT / "test/parity/errorset_wrapper_return_lexical_singleton_over_imported_singleton_smoke.sh").read_text()
    if not all(fragment in singleton_fixture for fragment in (
            "def choose(value: i64)",
            "def choose[T](value: T)",
            "return choose(value)")) or "expected_rows='L19'" not in singleton_smoke:
        raise SystemExit("EWR must retain coverage that a local and imported singleton do not activate cross-module receiver ranking")

    cross_module_singleton_smoke = (ROOT / "test/parity/errorset_wrapper_return_cross_module_singleton_specificity_smoke.sh").read_text()
    if not all(fragment in cross_module_singleton_smoke for fragment in (
            "return Consumer::choose(value)",
            "grep -q '^D 0$' <<< \"$stage1_output\"",
            "! grep -q 'cannot propagate' <<< \"$stage1_output\"")):
        raise SystemExit("EWR singleton scope control must preserve Core's lexical winner and keep Stage1 propagation clean")

    private_rank_fixture = (ROOT / "test/repro/errorset_wrapper_return_private_overload_rank.elisa").read_text()
    private_rank_smoke = (ROOT / "test/parity/errorset_wrapper_return_private_overload_rank_smoke.sh").read_text()
    if not all(fragment in private_rank_fixture for fragment in (
            "private_incompatible_fallible_does_not_block_public_generic(value: bool)",
            "return choose(value)",
            "private_incompatible_infallible_does_not_block_public_generic(value: bool)",
            "return choose_infallible(value)")) or "expected_rows=$'L24\\nL57\\nL60\\nL63'" not in private_rank_smoke:
        raise SystemExit("EWR private-rank coverage must retain viable blockers and incompatible-private public-generic fallbacks")

    private_primary_fixture = (ROOT / "test/repro/errorset_wrapper_return_private_primary_named_args.elisa").read_text()
    private_primary_smoke = (ROOT / "test/parity/errorset_wrapper_return_private_primary_named_args_smoke.sh").read_text()
    if not all(fragment in private_primary_fixture for fragment in (
            "def choose(value: i64)",
            "def choose[T](value: T)",
            "return choose(value: value)",
            "def plain(value: i64) -> i64:",
            "def plain[T](value: T)",
            "return plain(value: value)")) or not all(fragment in private_primary_smoke for fragment in (
            'grep -qF \'"Provider.choose" is private to module "Provider"\' <<< "$stage1_output"',
            'grep -qF \'"Provider.plain" is private to module "Provider"\' <<< "$stage1_output"',
            "grep -q '^D 4$' <<< \"$stage1_output\"",
            "! grep -q 'cannot propagate' <<< \"$stage1_output\"")):
        raise SystemExit("EWR named-argument coverage must retain private fallible and infallible primary barriers")

    private_extern_fixture = (ROOT / "test/repro/errorset_wrapper_return_private_extern.elisa").read_text()
    private_extern_smoke = (ROOT / "test/parity/errorset_wrapper_return_private_extern_smoke.sh").read_text()
    if not all(fragment in private_extern_fixture for fragment in (
            "extern fetch() -> i64",
            "using Provider::fetch",
            "using Hidden",
            "return wrap(fetch)")) or not all(fragment in private_extern_smoke for fragment in (
            "expected_rows='L27'",
            "grep -q '^D 1$' <<< \"$stage1_output\"")):
        raise SystemExit("EWR private-extern coverage must exercise function-value name lookup without a call arity")

    private_import_fixture = (ROOT / "test/repro/errorset_wrapper_return_private_import.elisa").read_text()
    private_import_smoke = (ROOT / "test/parity/errorset_wrapper_return_private_import_smoke.sh").read_text()
    if not all(fragment in private_import_fixture for fragment in (
            "from Provider import origin",
            "from Provider import wrap",
            "return wrap(origin)")) or not all(fragment in private_import_smoke for fragment in (
            '"AliasInstaller.Provider.wrap" is private to module "AliasInstaller.Provider"',
            "! grep -q 'cannot propagate'",
            "errorset_wrapper_return_private_import.elisa")):
        raise SystemExit("EWR private-import coverage must retain inaccessible wrapper lookup without reporting an ErrorSet mismatch")

    defaulted_overflow_fixture = (ROOT / "test/repro/errorset_wrapper_return_defaulted_overflow_rank.elisa").read_text()
    defaulted_overflow_smoke = (ROOT / "test/parity/errorset_wrapper_return_defaulted_overflow_rank_smoke.sh").read_text()
    if not all(fragment in defaulted_overflow_fixture for fragment in (
            "def select(value: i64, marker: i64 = 0)",
            "def select[T](value: T, first: i64, second: i64)",
            "return select(value, 3, 4)")) or not all(fragment in defaulted_overflow_smoke for fragment in (
            "errorset_wrapper_return_defaulted_overflow_rank.elisa",
            "expects .*arguments, got 3",
            "expected_rows=$'L25'")):
        raise SystemExit("EWR overflow coverage must prove a concrete defaulted Core winner keeps its ErrorSet over a generic fallback")

    defaulted_underflow_fixture = (ROOT / "test/repro/errorset_wrapper_return_defaulted_underflow_rank.elisa").read_text()
    defaulted_underflow_smoke = (ROOT / "test/parity/errorset_wrapper_return_defaulted_underflow_rank_smoke.sh").read_text()
    if not all(fragment in defaulted_underflow_fixture for fragment in (
            "def fallible(value: i64, required: bool, optional: bool = false)",
            "def fallible[T](value: T)",
            "return fallible(value)",
            "def infallible(value: i64, required: bool, optional: bool = false)",
            "def infallible[T](value: T)",
            "return infallible(value)",
            "def fixed(value: i64, required: bool)",
            "def fixed[T](value: T)",
            "return fixed(value)")) or not all(fragment in defaulted_underflow_smoke for fragment in (
            "errorset_wrapper_return_defaulted_underflow_rank.elisa",
            "expected_rows=$'L44'",
            "grep -cF 'cannot propagate'")):
        raise SystemExit("EWR underflow coverage must bind fallible and infallible defaulted winner barriers plus the fixed-arity filter control")

    later_mismatch_fixture = (ROOT / "test/repro/errorset_wrapper_return_later_argument_mismatch_rank.elisa").read_text()
    later_mismatch_smoke = (ROOT / "test/parity/errorset_wrapper_return_later_argument_mismatch_rank_smoke.sh").read_text()
    if not all(fragment in later_mismatch_fixture for fragment in (
            "def choose(value: i64, later: bool)",
            "def choose[T](value: T, later: T)",
            "return choose(value, later)")) or not all(fragment in later_mismatch_smoke for fragment in (
            "errorset_wrapper_return_later_argument_mismatch_rank.elisa",
            "argument 2 .*expects bool, got i64",
            "expected_rows=$'L22'")):
        raise SystemExit("EWR later-type coverage must preserve the Core first-argument winner's ErrorSet despite a later argument diagnostic")

    singleton_overflow_fixture = (ROOT / "test/repro/errorset_wrapper_return_singleton_overflow_rank.elisa").read_text()
    singleton_overflow_smoke = (ROOT / "test/parity/errorset_wrapper_return_singleton_overflow_rank_smoke.sh").read_text()
    if not all(fragment in singleton_overflow_fixture for fragment in (
            "def select(value: i64) -> i64 error[Provider::Fault]",
            "return select(value, 3)")) or not all(fragment in singleton_overflow_smoke for fragment in (
            "errorset_wrapper_return_singleton_overflow_rank.elisa",
            "expects 1 arguments, got 2",
            "expected_rows=$'L19'")):
        raise SystemExit("EWR singleton coverage must preserve the unique direct callable's ErrorSet after Core reports positional overflow")

    singleton_type_fixture = (ROOT / "test/repro/errorset_wrapper_return_singleton_type_mismatch.elisa").read_text()
    singleton_type_smoke = (ROOT / "test/parity/errorset_wrapper_return_singleton_type_mismatch_smoke.sh").read_text()
    if not all(fragment in singleton_type_fixture for fragment in (
            "def select(value: i64) -> i64 error[Provider::Fault]",
            "def wrapper(value: bool)",
            "return select(value)")) or not all(fragment in singleton_type_smoke for fragment in (
            "errorset_wrapper_return_singleton_type_mismatch.elisa",
            "argument 1 to .*expects i64, got bool",
            "expected_rows=$'L18'")):
        raise SystemExit("EWR singleton type coverage must retain the directly bound ErrorSet after Core diagnoses the argument type")

    named_infallible_fixture = (ROOT / "test/repro/errorset_wrapper_return_named_call_infallible_underflow.elisa").read_text()
    named_infallible_smoke = (ROOT / "test/parity/errorset_wrapper_return_named_call_infallible_underflow_smoke.sh").read_text()
    if not all(fragment in named_infallible_fixture for fragment in (
            "def choose(value: i64, fallback: i64 = 0)",
            "def choose(value: i64, required: bool)",
            "return choose(value: value)")) or not all(fragment in named_infallible_smoke for fragment in (
            "errorset_wrapper_return_named_call_infallible_underflow.elisa",
            "expected_rows=$'L22'",
            "unresolved infallible sibling")):
        raise SystemExit("EWR named-call coverage must keep a resolvable defaulted fallible winner over an infallible sibling with a missing required argument")

    variadic_arguments_fixture = (ROOT / "test/repro/errorset_wrapper_return_variadic_arguments.elisa").read_text()
    variadic_arguments_smoke = (ROOT / "test/parity/errorset_wrapper_return_variadic_arguments_smoke.sh").read_text()
    if not all(fragment in variadic_arguments_fixture for fragment in (
            "error GenericFault:",
            "def collect(value: i64, ...) -> i64 error[VariadicProvider::SelectedFault]",
            "def collect[T](value: T, marker: i64) -> i64 error[VariadicProvider::GenericFault]",
            "def positional_extra(value: i64, extra: i64) -> i64 error[VariadicProvider::GenericFault]",
            "return collect(value, extra)",
            "return collect(value: value)",
            "return collect(..)")) or not all(fragment in variadic_arguments_smoke for fragment in (
            "errorset_wrapper_return_variadic_arguments.elisa",
            "named arguments and explicit bundle applications are not supported for variadic function",
            "call argument forwarding `..` is not supported for variadic function",
            "expected_rows=$'L24'")):
        raise SystemExit("EWR variadic coverage must rank the concrete positional candidate above a fixed generic sibling and suppress unsupported named/forwarded shapes")

    variadic_extern_fixture = (ROOT / "test/repro/errorset_wrapper_return_variadic_extern.elisa").read_text()
    variadic_extern_smoke = (ROOT / "test/parity/errorset_wrapper_return_variadic_extern_smoke.sh").read_text()
    extern_call_match = function_source(EWR, "ewr_declaration_call_match")
    extern_arguments_match = function_source(EWR, "ewr_extern_arguments_match")
    extern_argument_match = function_source(EWR, "ewr_extern_argument_type_match")
    if not all(fragment in variadic_extern_fixture for fragment in (
            "extern choose(value: i64, ...) -> i64 error[VariadicExternProvider::SelectedFault]",
            "extern choose(value: cstr, marker: i64) -> i64 error[VariadicExternProvider::SiblingFault]",
            "def positional_extra(value: i64, extra: i64) -> i64 error[VariadicExternProvider::SiblingFault]",
            "return choose(value, extra)")) or not all(fragment in extern_call_match for fragment in (
            "Decl.Extern(_, param_start, arity, _, callable, _, _, position)",
            "ewr_extern_arguments_match(param_start, arity, extern_params, arguments, caller_parameters, caller_local_names) if callable and position.line == function_line and position.offset == function_offset")) or not all(fragment in extern_arguments_match for fragment in (
            "parameter_index: usize = param_start.usize()",
            "parameter.type_name",
            "parameter.is_ref or parameter.optional or parameter.mutable_ref",
            "ewr_extern_argument_type_match(arguments[0.usize()]")) or not all(fragment in extern_argument_match for fragment in (
            "return (false, true, 0.usize()) if not is_bare_primitive_type(expected_name)",
            "ewr_actual_primitive_type(argument, caller_parameters, caller_local_names)",
            "if actual.kind == 5:",
            "matches: bool = actual.name == expected_name",
            "return (true, matches, 2.usize() if matches else 0.usize())")):
        raise SystemExit("EWR variadic-extern coverage must rank known primitive receivers and preserve the i64 extern's family over its cstr sibling")
    if not all(fragment in variadic_extern_smoke for fragment in (
            "errorset_wrapper_return_variadic_extern.elisa",
            "expected_rows=$'L20'",
            "cannot propagate.*SelectedFault",
            "i64 variadic extern's ErrorSet")):
        raise SystemExit("EWR variadic-extern parity contract must require the selected i64 extern family at the overflow call")
    if "candidate_match.specificity > selected_specificity" not in fallible_selection or "candidate_type_viable: bool = candidate_match.viable if receiver_rank_active else true" not in fallible_selection:
        raise SystemExit("EWR variadic extern receiver evidence must participate in the existing Core-ranked viable-family winner path")
    callable_family_signature = function_source(EWR, "ewr_callable_family").splitlines()[0]
    entrypoint = function_source(EWR, "check_errorset_wrapper_return")
    if "extern_params: darray[Ast::ExternParam]" not in callable_family_signature or "file.extern_params" not in entrypoint:
        raise SystemExit("EWR must thread the file's extern parameter table into receiver family matching")

    static_alias_fixture = (ROOT / "test/repro/errorset_wrapper_return_static_alias_branch.elisa").read_text()
    static_alias_unknown_fixture = (ROOT / "test/repro/errorset_wrapper_return_static_alias_unknown.elisa").read_text()
    static_const_fixture = (ROOT / "test/repro/errorset_wrapper_return_static_const_branch.elisa").read_text()
    static_const_smoke = (ROOT / "test/parity/errorset_wrapper_return_static_const_branch_smoke.sh").read_text()
    static_import_filter = function_source(EWR, "ewr_static_import_annotations")
    static_import_selection = function_source(EWR, "ewr_static_import_annotation_selection")
    static_branch_selection = function_source(EWR, "ewr_static_import_branch_selection")
    static_const_branch = function_source(EWR, "ewr_static_if_const_branch_selection")
    static_const_value = function_source(EWR, "ewr_static_if_named_constant_value")
    static_condition_value = function_source(EWR, "ewr_static_if_condition_value")
    static_row_selection = function_source(EWR, "ewr_static_if_row_selection")
    static_branch_markers = function_source(PARSER, "record_static_if_branch_markers")
    unknown_static_import = function_source(EWR, "ewr_unknown_static_import_affects_call")
    unknown_alias_winner = function_source(EWR, "ewr_unknown_using_alias_is_definitely_shadowed")
    alias_order = function_source(EWR, "ewr_module_alias_order")
    alias_winner = function_source(EWR, "ewr_definite_module_alias_is_global_winner")
    unknown_alias_head = function_source(EWR, "ewr_qualifier_head_matches")
    unknown_alias_target = function_source(EWR, "ewr_raw_callable_matches_alias_path")
    known_alias_path = function_source(EWR, "ewr_known_module_alias_path_matches_candidate")
    qualified_module_match = function_source(EWR, "ewr_qualified_module_matches")
    qualified_module_rank = function_source(EWR, "ewr_qualified_module_rank")
    qualified_module_path_rank = function_source(EWR, "ewr_qualified_module_path_rank")
    unknown_alias_barrier = unknown_static_import[unknown_static_import.find('marker.owner == "__ewr_unknown_using_alias"'):]
    if "table: SymbolTable&" not in known_alias_path.splitlines()[0]:
        raise SystemExit("EWR global alias ordering requires the symbol table alongside active annotations")
    if not all(fragment in static_alias_fixture for fragment in (
            "const USE_INACTIVE_PROVIDER: bool = false",
            "static if USE_INACTIVE_PROVIDER:",
            "using InactiveProvider as Selected",
            "using ActiveProvider as Selected",
            "return Selected::wrap(Selected::origin())",
            "error[Consumer::WrongFault{Wrong}]")) or not all(fragment in static_alias_unknown_fixture for fragment in (
            "static if UNKNOWN_PROVIDER_CHOICE:",
            "using OtherProvider as Maybe",
            "using CandidateProvider as Maybe",
            "static if UNKNOWN_PROVIDER_CHOICE:\n    using OtherProvider as Maybe\nstatic else:\n    using CandidateProvider as Maybe",
            "return Maybe::wrap(Maybe::origin())",
            "using CandidateProvider as Stable",
            "using OtherProvider as Stable",
            "static if true:",
            "using CandidateProvider as Earlier",
            "using OtherProvider as Earlier",
            "static if true:\n    static if true:",
            "using OtherProvider as NestedBranchWinner",
            "using CandidateProvider as NestedBranchWinner",
            "NestedBranchWinner::wrap(NestedBranchWinner::origin())",
            "module CrossBranchInstaller:",
            "using OtherProvider as CrossScopeBranchWinner",
            "using CandidateProvider as CrossScopeBranchWinner",
            "CrossScopeBranchWinner::wrap(CrossScopeBranchWinner::origin())",
            "def cross_scope_branch_parent_prepass_wins()",
            "module Maybe:",
            "OtherProvider::Maybe::wrap(OtherProvider::Maybe::origin())",
            "module Pick:",
            "module LexicalScope:",
            "LexicalPathFault",
            "def lexical_path_beats_module_alias()",
            "module AliasInstaller:",
            "using LocalProvider as NestedGlobal",
            "module AliasShadowInstaller:",
            "using OtherProvider as RegistrationWinner",
            "using CandidateProvider as RegistrationWinner",
            "using CandidateProvider as Pick",
            "RegistrationWinner::wrap(RegistrationWinner::origin())",
            "Pick::wrap(Pick::origin())",
            "module Detached:",
            "module Same:",
            "return Same::wrap(Same::origin())",
            "NestedGlobal::wrap(NestedGlobal::origin())",
            "def unresolved_alias_call()",
            "def definite_alias_wins()",
            "def earlier_active_branch_alias_wins()",
            "def alias_spelling_in_non_head_segment_does_not_poison()",
            "def nested_global_alias_is_visible()")):
        raise SystemExit("EWR static-alias fixture must cover branch winners, global registration order, nested aliases, and unrelated leaf names")
    if not all(fragment in static_import_selection for fragment in (
            "__from_member_static_branch",
            "__binding_wildcard_import_static_branch",
            "__using_alias_static_branch")) or not all(fragment in static_branch_selection for fragment in (
            "marker.owner != \"__static_if_branch\"",
            "marker.identity_id.usize()",
            "branch.known and not branch.selected",
            "return (false, false) if unknown",
            "ewr_static_if_row_selection(file, marker.identity_id.usize(), module, table)")):
        raise SystemExit("EWR static import filtering must use each generic parser marker and fail closed for unresolved branch ancestry")
    if not all(fragment in static_import_filter for fragment in (
            "continue if branch.known and not branch.active",
            "__ewr_unknown_selective_import",
            "__ewr_unknown_wildcard_import",
            "__ewr_unknown_using_alias")) or not all(fragment in unknown_static_import for fragment in (
            "__ewr_unknown_selective_import",
            "__ewr_unknown_wildcard_import",
            "__ewr_unknown_using_alias",
            "ewr_qualifier_head_matches",
            "ewr_raw_callable_matches_alias_path",
            "ewr_unknown_using_alias_is_definitely_shadowed")) or not all(fragment in unknown_alias_head for fragment in (
            "qualifier[0:wanted.len] != wanted",
            "qualifier[wanted.len + 1.usize()] == 58")) or not all(fragment in unknown_alias_target for fragment in (
            "callable_alias_path_matches_candidate(annotations, alias_module, alias_target, suffix, current_module)",
            "Decl.Func(function_name",
            "Decl.Extern(extern_name")) or not all(fragment in known_alias_path for fragment in (
            'alias.name != "__using_alias"',
            "alias.owner != alias_name",
            "ewr_module_alias_order(earlier_alias, alias, table)",
            "not ordering.known or ordering.left_precedes",
            "table.possible_import_annotations",
            "ewr_module_alias_order(possible_alias, alias, table)",
            "not ordering.known or ordering.left_precedes",
            'target_row.name == "__using_alias_target"',
            "target_count <- target_count + 1.usize()",
            "return false if target_count != 1.usize()",
            "callable_alias_path_matches_candidate(annotations, alias.module, target, suffix, candidate_module)")) or not all(fragment in qualified_module_match for fragment in (
            "ewr_qualified_module_rank(candidate_module, qualifier, caller_module, annotations, table) > 0.usize()")) or "module_last_segment(candidate_module)" in qualified_module_match or not all(fragment in qualified_module_rank for fragment in (
            "ewr_qualified_module_path_rank(candidate_module, qualifier, caller_module)",
            "return lexical_rank if lexical_rank > 0.usize()",
            "return 2.usize() if ewr_known_module_alias_path_matches_candidate(candidate_module, qualifier, annotations, table)",
            "return 1.usize() if candidate_module == qualifier",
            "return 0.usize()")) or not all(fragment in qualified_module_path_rank for fragment in (
            "scope_module: mutable sview = caller_module",
            "return scope_module.len + 3.usize() if callable_module_path_matches_suffix(candidate_module, scope_module, qualifier)",
            "try_noncall_module_parent(scope_module)")) or not all(fragment in unknown_alias_winner for fragment in (
            "table.possible_import_annotations",
            "possible_alias.owner != marker.name",
            "possible_alias.module != marker.module",
            "possible_alias.line != marker.line",
            "possible_alias.offset != marker.offset",
            "table.definite_import_annotations",
            "ewr_module_alias_order(definite_alias, possible_alias, table)",
            "ordering.known and ordering.left_precedes",
            "ewr_definite_module_alias_is_global_winner(definite_alias, table)")) or not all(fragment in alias_winner for fragment in (
            "table.definite_import_annotations",
            "table.possible_import_annotations",
            "ewr_module_alias_order(candidate, alias, table)",
            "not ordering.known or ordering.left_precedes",
            "return true")) or not all(fragment in alias_order for fragment in (
            "return (known: bool, left_precedes: bool)",
            "return semantic_possible_import_alias_precedes(left, right, table)")) or "ewr_module_is_lexical_ancestor(marker.module, caller_module)" in unknown_alias_barrier:
        raise SystemExit("EWR must check only a possible alias head and retain the barrier only when its target may supply the call")
    for alias_rank_source in (binding_scope, inaccessible_binding_scope, function_source(EWR, "ewr_infallible_callable_scope"), ordinary_binding):
        if "ewr_qualified_module_rank(" not in alias_rank_source:
            raise SystemExit("EWR callable selection must preserve Core's lexical, alias, and raw qualified-name candidate order")
    if not all(fragment in static_const_value for fragment in (
            "table.immutable_const_names",
            "table.immutable_const_rows",
            "SemanticPrivateModuleBoundary::within_module",
            "ewr_static_if_const_branch_selection(file, name, symbol, table, depth + 1)",
            "continue if branch.known and not branch.active",
            "found_unknown",
            "ewr_static_if_condition_value(table.immutable_const_values[selected_row]")) or not all(fragment in static_const_branch for fragment in (
            'marker.name != "__const_static_branch"',
            "marker.detail_name != name",
            "marker.identity_id.usize()",
            "ewr_static_if_row_selection(file, marker.identity_id.usize(), symbol.module_owner, table, depth + 1)",
            "branch.known and not branch.selected")) or not all(fragment in static_condition_value for fragment in (
            "Expr.Ident(name, _):",
            "ewr_static_if_named_constant_value(name, current_module, file, table")) or not all(fragment in static_row_selection for fragment in (
            "depth: u32 = 0",
            "depth >= 64",
            "row >= file.static_if_modules.count",
            "condition_module: sview = file.static_if_modules[row]",
            "ewr_static_if_condition_value(file.static_if_conds[row], condition_module, file, table, depth + 1")):
        raise SystemExit("EWR must fold conditions in their recorded lexical modules and keep missing or unknown rows conservative")
    if not all(fragment in static_branch_markers for fragment in (
            "parser.static_if_branch_rows.count.u32() != parser.static_if_depth",
            "identity_id: 4294967295",
            "for branch_identity in parser.static_if_branch_rows",
            "identity_id: branch_identity")):
        raise SystemExit("EWR nested const selection depends on parser markers retaining every enclosing branch row")
    if not all(fragment in static_const_fixture for fragment in (
            "const CHOOSE_A: bool = true",
            "static if false:",
            "static if true:",
            "const CHOOSE_A: bool = false",
            "static if CHOOSE_A:",
            "module App:\n    module ProviderA:",
            "using ProviderA as Pick",
            "using ProviderB as Pick",
            "def caller() -> i64 error[App::ProviderA::FaultA]",
            "return Pick::origin()")) or not all(fragment in static_const_smoke for fragment in (
            "errorset_wrapper_return_static_const_branch.elisa",
            "Stage1 let the inactive nested const select ProviderB",
            "cannot propagate")):
        raise SystemExit("EWR must ignore a deeper inactive const when selecting a static-import callable family")
    if not all(fragment in entrypoint for fragment in (
            "lookup_annotations: mutable darray[Ast::EnumAnnotation] = ewr_static_import_annotations(file, table)",
            "callable_error_index_build(lookup_annotations",
            "ewr_check_declarations(file.top_decls, file.top_decls, file.extern_params, lookup_annotations")) or "ewr_unknown_static_import_affects_call(annotations, all_declarations, name, qualifier, caller_module, table)" not in function_source(EWR, "ewr_callable_family"):
        raise SystemExit("EWR call-family lookup must consume branch-filtered imports and decline when an unresolved branch can supply the queried callable")

    ambiguous_using_fixture = (ROOT / "test/repro/errorset_wrapper_return_ambiguous_outer_nested_using.elisa").read_text()
    ambiguous_using_smoke = (ROOT / "test/parity/errorset_wrapper_return_ambiguous_outer_nested_using_smoke.sh").read_text()
    if not all(fragment in ambiguous_using_fixture for fragment in (
            "using NestedApi",
            "return Wrapper::propagate(origin)",
            "error Destination")) or not all(fragment in ambiguous_using_smoke for fragment in (
            'ambiguous reference "origin"',
            "cannot propagate")):
        raise SystemExit("EWR wildcard ambiguity coverage must retain the third-destination case and reject propagation cascades")

    print("EWR canonical-resolution and callable-visibility source binding passed")
