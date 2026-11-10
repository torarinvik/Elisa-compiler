"""Check try error-family identity, imports, and visibility."""
import re


def check_try_family_visibility(
    facts,
    ROOT,
    compact_inline,
    function_section,
    source_text,
):
    if "current_module: sview @source" not in facts['generic_return_identity'] or \
            "current_module: sview @source" not in facts['generic_return_facts']:
        raise SystemExit("Try generic-return identity must keep its caller-guaranteed source-backed module through its annotation scan")
    if "scope_bound and not catch_module_is_ancestor(import_module, function_module)" not in facts['import_path_match']:
        raise SystemExit("Try import path matching must distinguish lexical wildcard visibility from program-wide selective imports")
    wildcard_scope_filter = 'import_row.module != scope_module or import_row.name != "__binding_wildcard_import"'
    if not all(fragment in facts['direct_import_visibility'] for fragment in (
            "try_error_alias_module_visible(annotations, declaration.module, function_module)",
            wildcard_scope_filter,
            'if scope_module == ""',
            'import_row.owner != "__from_member" or import_row.name != declaration.name',
            "function_module, declaration.module, false)")) or facts['direct_import_visibility'].index('if scope_module == ""') < facts['direct_import_visibility'].index(wildcard_scope_filter):
        raise SystemExit("Try direct ErrorSet lookup must search lexical wildcard imports before the first program-level selective import")
    direct_selective_start = facts['direct_import_visibility'].index('if scope_module == ""')
    direct_selective_member = facts['direct_import_visibility'].index('import_row.owner != "__from_member" or import_row.name != declaration.name', direct_selective_start)
    direct_selective_return = facts['direct_import_visibility'].index("return try_error_set_import_path_matches", direct_selective_member)
    if not all(fragment in facts['alias_visibility'] for fragment in (
            wildcard_scope_filter,
            'if scope_module == ""',
            'import_row.owner != "__from_member" or import_row.name != name',
            "function_module, declaration_module, false)")) or facts['alias_visibility'].index('if scope_module == ""') < facts['alias_visibility'].index(wildcard_scope_filter):
        raise SystemExit("Try type-alias lookup must search lexical wildcard imports before the first program-level selective import")
    alias_selective_start = facts['alias_visibility'].index('if scope_module == ""')
    alias_selective_member = facts['alias_visibility'].index('import_row.owner != "__from_member" or import_row.name != name', alias_selective_start)
    alias_selective_return = facts['alias_visibility'].index("return try_error_set_import_path_matches", alias_selective_member)
    if direct_selective_return < direct_selective_member or alias_selective_return < alias_selective_member:
        raise SystemExit("Try selective import lookup must stop at the first program-level alias target")
    for fixture_name, smoke_name in (
            ("try_bare_variant_sibling_selective_import.elisa", "try_bare_variant_sibling_selective_import_smoke.sh"),
            ("try_bare_variant_sibling_imported_alias.elisa", "try_bare_variant_sibling_imported_alias_smoke.sh"),
            ("try_bare_variant_imported_alias_chain.elisa", "try_bare_variant_imported_alias_chain_smoke.sh"),
            ("try_bare_variant_conflicting_selective_import_first_target.elisa", "try_bare_variant_conflicting_selective_import_first_target_smoke.sh"),
            ("try_bare_variant_duplicate_selective_import.elisa", "try_bare_variant_duplicate_selective_import_smoke.sh"),
            ("try_direct_sibling_selective_import.elisa", "try_direct_sibling_selective_import_smoke.sh"),
            ("try_noncall_cached_sibling_import.elisa", "try_noncall_cached_sibling_import_smoke.sh"),
            ("try_noncall_cached_relative_selective_import.elisa", "try_noncall_cached_relative_selective_import_smoke.sh"),
            ("try_noncall_cached_conflicting_selective_import_first_target.elisa", "try_noncall_cached_conflicting_selective_import_first_target_smoke.sh"),
            ("try_noncall_cached_ancestor_precedes_selective_import.elisa", "try_noncall_cached_ancestor_precedes_selective_import_smoke.sh"),
            ("try_noncall_cached_private_import_visibility.elisa", "try_noncall_cached_private_import_visibility_smoke.sh"),
            ("try_overload_private_winner_visibility.elisa", "try_overload_private_winner_visibility_smoke.sh"),
            ("try_overload_nominal_identity_controls.elisa", "try_overload_nominal_identity_controls_smoke.sh"),
            ("try_wildcard_import_order_outer_before_nested.elisa", "try_wildcard_import_order_outer_before_nested_smoke.sh"),
            ("try_private_outer_using_does_not_shadow_public_inner.elisa", "try_private_outer_using_does_not_shadow_public_inner_smoke.sh"),
            ("try_wildcard_import_does_not_shadow_ancestor.elisa", "try_wildcard_import_does_not_shadow_ancestor_smoke.sh")):
        fixture = ROOT / "test/repro" / fixture_name
        smoke = ROOT / "test/parity" / smoke_name
        if not fixture.is_file() or fixture_name not in smoke.read_text():
            raise SystemExit(f"Try program-selective import coverage must retain its sibling fixture and parity smoke: {fixture_name}")
    wildcard_order_fixture = (ROOT / "test/repro/try_wildcard_import_order_outer_before_nested.elisa").read_text()
    wildcard_order_smoke = (ROOT / "test/parity/try_wildcard_import_order_outer_before_nested_smoke.sh").read_text()
    if not all(fragment in wildcard_order_fixture for fragment in (
            "def direct_caller() -> i64 error[Consumer::Destination]",
            "return try ping()",
            "def cached_caller() -> i64 error[Consumer::Destination]",
            "payload = ping()",
            "return try payload",
            "using OuterApi")) or not all(fragment in wildcard_order_smoke for fragment in (
            'grep -qF \'ambiguous reference "ping"\'',
            "cannot propagate|try requires a fallible expression")):
        raise SystemExit("Try wildcard ambiguity regression must cover both direct and cached outer/nested using callers")
    parent_wildcard_fixture = (ROOT / "test/repro/try_wildcard_import_does_not_shadow_ancestor.elisa").read_text()
    parent_wildcard_smoke = (ROOT / "test/parity/try_wildcard_import_does_not_shadow_ancestor_smoke.sh").read_text()
    if not all(fragment in parent_wildcard_fixture for fragment in (
            "def ping() -> i64 error[Consumer::LocalFault]",
            "module Inner:",
            "using Api",
            "def caller() -> i64 error[Consumer::LocalFault]",
            "return try ping()",
            "def cached_caller() -> i64 error[Consumer::LocalFault]",
            "payload = ping()",
            "return try payload")) or not all(fragment in parent_wildcard_smoke for fragment in (
            "direct-call path",
            "cached assignment path",
            "cached try path")):
        raise SystemExit("Try ancestor-local precedence regression must retain both direct and cached nested-using callers")
    private_outer_fixture = (ROOT / "test/repro/try_private_outer_using_does_not_shadow_public_inner.elisa").read_text()
    root_using = private_outer_fixture.find("using HiddenApi")
    consumer_module = private_outer_fixture.find("module Consumer:")
    inner_module = private_outer_fixture.find("module Inner:", consumer_module)
    visible_module = private_outer_fixture.find("module VisibleApi:", inner_module)
    inner_using = private_outer_fixture.find("using VisibleApi", visible_module)
    if min(root_using, consumer_module, inner_module, visible_module, inner_using) < 0 or not (
            root_using < consumer_module < inner_module < visible_module < inner_using) or not all(fragment in private_outer_fixture for fragment in (
            "def direct_caller() -> i64 error[Consumer::Inner::VisibleApi::VisibleFault]",
            "return try ping()",
            "def cached_caller() -> i64 error[Consumer::Inner::VisibleApi::VisibleFault]",
            "payload = ping()",
            "return try payload")):
        raise SystemExit("Try private-outer/nested-public fixture must preserve root and nested using scope placement for direct and cached calls")
    private_visibility_fixture = (ROOT / "test/repro/try_overload_private_winner_visibility.elisa").read_text()
    private_visibility_smoke = (ROOT / "test/parity/try_overload_private_winner_visibility_smoke.sh").read_text()
    if not all(fragment in private_visibility_fixture for fragment in (
            "def origin[T](value: T) -> i64 error[Provider::GenericFault]",
            "def origin(value: i64) -> i64 error[Provider::ConcreteFault]",
            "def cached_private_winner(value: i64) -> i64 error[Consumer::Destination]",
            "def qualified_private_winner_direct(value: i64) -> i64 error[Consumer::Destination]",
            "return try Provider::origin(value)",
            "def qualified_private_winner_cached(value: i64) -> i64 error[Consumer::Destination]",
            "payload = Provider::origin(value)",
            "def public_winner_direct(value: bool) -> i64 error[Consumer::Destination]",
            "return try origin(value)",
            "def public_winner_cached(value: bool) -> i64 error[Consumer::Destination]",
            "payload = origin(value)",
            "return try payload",
            "def public_qualified_winner_direct(value: bool) -> i64 error[Consumer::Destination]",
            "return try Provider::origin(value)",
            "def public_qualified_winner_cached(value: bool) -> i64 error[Consumer::Destination]",
            "payload = Provider::origin(value)",
            "def typed_width_public_winner_direct(value: i32) -> i64 error[Consumer::Destination]",
            "def typed_width_public_winner_cached(value: i32) -> i64 error[Consumer::Destination]",
            "def char_public_winner_direct(value: char) -> i64 error[Consumer::Destination]",
            "def char_public_winner_cached(value: char) -> i64 error[Consumer::Destination]",
            "def root_callable_private_winner_direct(value: i64) -> i64 error[Consumer::Destination]",
            "def root_callable_private_winner_cached(value: i64) -> i64 error[Consumer::Destination]",
            "def origin(value: bool) -> i64 error[Provider::GenericFault]",
            "def narrow[T](value: T) -> i64 error[CharProvider::GenericFault]",
            "def narrow(value: char) -> i64 error[CharProvider::ConcreteFault]",
            "def address[T](value: T) -> i64 error[CharProvider::GenericFault]",
            "def address(value: uintptr) -> i64 error[CharProvider::ConcreteFault]",
            "def int_char_private_winner_direct(value: int) -> i64 error[Consumer::Destination]",
            "def int_char_private_winner_direct(value: int) -> i64 error[Consumer::Destination]:\n            return try CharProvider::narrow(value)",
            "def int_char_private_winner_cached(value: int) -> i64 error[Consumer::Destination]",
            "def int_char_private_winner_cached(value: int) -> i64 error[Consumer::Destination]:\n            payload = CharProvider::narrow(value)\n            return try payload",
            "def int_uintptr_private_winner_cached(value: int) -> i64 error[Consumer::Destination]",
            "def int_uintptr_private_winner_cached(value: int) -> i64 error[Consumer::Destination]:\n            payload = CharProvider::address(value)\n            return try payload")) or not all(fragment in private_visibility_smoke for fragment in (
            "grep -cF 'cannot propagate'",
            "== 8",
            "grep -cF 'is private to module'",
            "== 9",
            "CharProvider.narrow",
            "CharProvider.address",
            'L32 "Provider.origin" is private to module "Provider"',
            'L35 "Provider.origin" is private to module "Provider"',
            'L67 "Provider.origin" is private to module "Provider"',
            'L70 "Provider.origin" is private to module "Provider"',
            "  L25 \"Provider.origin\" is private to module \"Provider\"",
            "  L28 \"Provider.origin\" is private to module \"Provider\"",
            "root_callable_private_winner_direct",
            "root_callable_private_winner_cached",
            "^  L(39|42|46|49|53|56|60|63) .*is private to module ",
            "if grep -qF 'try requires a fallible expression' <<< \"$stage0_output\"; then",
            "if grep -qF 'try requires a fallible expression' <<< \"$stage1_output\"; then")):
        raise SystemExit("Try private-overload visibility control must preserve direct and cached public generic mismatch diagnostics")
    private_same_named_types_fixture = (ROOT / "test/repro/try_overload_private_same_named_module_types.elisa").read_text()
    private_same_named_types_smoke = (ROOT / "test/parity/try_overload_private_same_named_module_types_smoke.sh").read_text()
    if not all(fragment in private_same_named_types_fixture for fragment in (
            "module NamedProvider:",
            "struct Widget:",
            "def inspect(value: Widget) -> i64:",
            "def inspect[T](value: T) -> i64 error[NamedProvider::GenericFault]",
            "module Consumer:",
            "def direct(value: Widget)",
            "return try NamedProvider::inspect(value)",
            "def cached(value: Widget)",
            "payload = NamedProvider::inspect(value)")) or not all(fragment in private_same_named_types_smoke for fragment in (
            "try_overload_private_same_named_module_types.elisa",
            'is private to module "NamedProvider"',
            "if grep -qF 'try requires a fallible expression' <<< \"$stage0_output\"; then",
            "if grep -qF 'try requires a fallible expression' <<< \"$stage1_output\"; then",
            "== 2")):
        raise SystemExit("Try named-type visibility fixture must reject same-spelled nominal mismatches for direct and cached calls")
    nominal_identity_controls_fixture = (ROOT / "test/repro/try_overload_nominal_identity_controls.elisa").read_text()
    nominal_identity_controls_smoke = (ROOT / "test/parity/try_overload_nominal_identity_controls_smoke.sh").read_text()
    if not all(fragment in nominal_identity_controls_fixture for fragment in (
            "module HiddenTypes:",
            "private:",
            "struct Widget:",
            "module Provider:",
            "error GenericFault:",
            "struct Widget:",
            "def singleton(value: Widget)",
            "def generic_only[T](value: T)",
            "def generic_only(value: bool, marker: i64)",
            "def overloaded(value: Widget)",
            "def overloaded[T](value: T)",
            "def overloaded(value: i64)",
            "from Provider import Widget",
            "def singleton_same_name(value: Widget)",
            "def generic_only_same_name(value: Widget)",
            "def concrete_overload_same_name(value: Widget)",
            "def concrete_overload_wrong_family(value: Widget)",
            "static if false:",
            "type Widget = bool",
            "def inactive_alias_direct(value: Widget) -> i64 error[Provider::Fault]",
            "def inactive_alias_cached(value: Widget) -> i64 error[Provider::Fault]",
            "module InactiveStructShadow:",
            "struct Widget:",
            "module InactiveEnumShadow:",
            "enum Widget:",
            "module InactiveExternShadow:",
            "extern Widget",
            "def direct(value: Widget) -> i64 error[Provider::Fault]",
            "return try Provider::singleton(value)",
            "return try Provider::generic_only(value)",
            "return try Provider::overloaded(value)",
            "payload = Provider::singleton(value)",
            "return try payload")) or not all(fragment in nominal_identity_controls_smoke for fragment in (
            "try_overload_nominal_identity_controls.elisa",
            "wrong-family concrete-overload control",
            "^D 1$",
            "cannot propagate",
            "expected_rows=$'L51'")):
        raise SystemExit("Try nominal identity controls must preserve selected families despite private or statically inactive same-spelled type declarations")
    nested_forward_fixture = (ROOT / "test/repro/try_overload_nested_and_forwarded_calls.elisa").read_text()
    nested_forward_smoke = (ROOT / "test/parity/try_overload_nested_and_forwarded_calls_smoke.sh").read_text()
    if not all(fragment in nested_forward_fixture for fragment in (
            "def choose(value: i64)",
            "def choose(value: bool)",
            "def produce_i64() -> i64",
            "return try choose(produce_i64())",
            "return try choose(..)",
            "return try singleton(..)")) or not all(fragment in nested_forward_smoke for fragment in (
            "try_overload_nested_and_forwarded_calls.elisa",
            "expected_rows=$'L27\\nL36'",
            "grep -q '^D 2$'",
            "try requires a fallible expression")):
        raise SystemExit("Try receiver guards must preserve a known public nested-call winner, fail closed on forwarded overload families, and retain forwarded singleton inference")
    cross_module_private_fixture = (ROOT / "test/repro/try_overload_cross_module_private_cached_winner.elisa").read_text()
    cross_module_private_smoke = (ROOT / "test/parity/try_overload_cross_module_private_cached_winner_smoke.sh").read_text()
    if not all(fragment in cross_module_private_fixture for fragment in (
            "def choose[T](receiver: T) -> i64 error[LibA::GenericFault]",
            "from LibB import choose",
            "def choose(receiver: i64) -> i64 error[AliasInstaller::LibB::ConcreteFault]",
            "using LibA",
            "def private_winner_direct(value: i64)",
            "def private_winner_cached(value: i64)",
            "payload = choose(value)",
            "def public_winner_direct(value: bool)",
            "def public_winner_cached(value: bool)")) or not all(fragment in cross_module_private_smoke for fragment in (
            "try_overload_cross_module_private_cached_winner.elisa",
            "grep -cF 'is private to module'",
            "grep -cF 'try requires a fallible expression'",
            "grep -cF 'cannot propagate'",
            "== 2")):
        raise SystemExit("Try cached winner coverage must include hidden private candidates from a different selective-import module and retain a public generic control")
    static_import_fixture = (ROOT / "test/repro/try_overload_static_import_family.elisa").read_text()
    static_import_smoke = (ROOT / "test/parity/try_overload_static_import_family_smoke.sh").read_text()
    if not all(fragment in static_import_fixture for fragment in (
            "const USE_INACTIVE_PROVIDER: bool = false",
            "static if USE_INACTIVE_PROVIDER:",
            "from InactiveProvider import origin",
            "static else:",
            "from ActiveProvider import origin",
            "error InactiveFault:",
            "error ActiveFault:",
            "def caller(value: bool) -> i64 error[ActiveProvider::ActiveFault]",
            "return try origin(value)")) or not all(fragment in static_import_smoke for fragment in (
            "try_overload_static_import_family.elisa",
            "Stage0 selected the inactive import's ErrorSet",
            "Stage1 selected the inactive import's ErrorSet",
            "cannot propagate")):
        raise SystemExit("Try static-import coverage must select the active static-else provider's ErrorSet over the earlier inactive import")
    if not (static_import_fixture.index("from InactiveProvider import origin") < static_import_fixture.index("from ActiveProvider import origin")):
        raise SystemExit("Try static-import coverage must put the inactive import before the active fallback import")
    static_alias_fixture = (ROOT / "test/repro/try_overload_static_alias_family.elisa").read_text()
    static_alias_smoke = (ROOT / "test/parity/try_overload_static_alias_family_smoke.sh").read_text()
    static_alias_propagation_row = compact_inline(function_section(source_text, "check_try_propagation_row"))
    if not all(fragment in static_alias_fixture for fragment in (
            "const USE_INACTIVE_PROVIDER: bool = false",
            "static if USE_INACTIVE_PROVIDER:",
            "using InactiveProvider as Selected",
            "static else:",
            "using ActiveProvider as BaseProvider",
            "using BaseProvider as Selected",
            "module RootCollision:",
            "error RootFault:",
            "def origin(value: bool) -> i64 error[RootCollision::RootFault]:",
            "module AliasSafeProvider:",
            "def origin(value: bool) -> i64 error[AliasSafeProvider::SafeFault]:",
            "module AliasInstallerA:\n    static if ELISA_TARGET_OS_WASI:\n        using AliasSafeProvider as RootCollision",
            "module AliasInstallerB:\n    static if ELISA_TARGET_OS_WASI:\n        using AliasSafeProvider as RootCollision",
            "def unresolved_alias_cannot_select_root(value: bool) -> i64:",
            "return try RootCollision::origin(value)",
            "error InactiveFault:",
            "error ActiveFault:",
            "def caller(value: bool) -> i64 error[ActiveProvider::ActiveFault]",
            "return try Selected::origin(value)")):
        raise SystemExit("Try static-alias coverage must select the active static-else provider's ErrorSet for a qualified call")
    if not all(fragment in static_alias_fixture for fragment in ("error SafeFault:", "SafeFault")) or 'return if first_class_error_family == "" and annotation.owner != "__noncall" and callable_try_static_binding_uncertain(annotations, annotation.owner, enclosing_module, callee_qualifier, table)' not in static_alias_propagation_row:
        raise SystemExit("Try must suppress family inference at the propagation-row boundary while an unknown alias could select a fallible target")
    if not all(fragment in static_alias_smoke for fragment in (
            "try_overload_static_alias_family.elisa",
            "Stage0 selected the inactive alias provider's ErrorSet",
            "Stage1 selected the inactive alias provider's ErrorSet",
            "cannot propagate")):
        raise SystemExit("Try static-alias smoke must check both compiler stages against the inactive provider's ErrorSet")
    if "try_error_alias_name_visible(annotations, name, declaration_module, function_module)" not in facts['alias_visibility'] or not all(fragment in facts['private_alias_path'] for fragment in (
            'row.owner == "__section_private"',
            "row.name == segment",
            "catch_module_is_ancestor(private_scope, lexical_module)")) or not all(fragment in facts['private_alias_name'] for fragment in (
            "try_error_alias_is_private(annotations, alias_name, alias_module)",
            "catch_module_is_ancestor(alias_module, lexical_module)")):
        raise SystemExit("Try alias candidates must respect private type aliases and private module boundaries")
    alias_ref_resolution = compact_inline(function_section(source_text, "try_error_family_ref_for_annotation"))
    if "family: declaration_module.family" not in alias_ref_resolution or "source_name: family" not in alias_ref_resolution:
        raise SystemExit("Try family references must compare canonical alias identity while retaining source spelling for annotation metadata")
    alias_subset_status = compact_inline(function_section(source_text, "try_error_family_subset_status"))
    if "row.name == family.source_name" not in alias_subset_status:
        raise SystemExit("Try subset markers must continue to match their source alias spelling after canonical family resolution")

    subset_status = compact_inline(function_section(source_text, "try_error_family_subset_status"))
    if not all(fragment in subset_status for fragment in (
            "saw_unrestricted <- true if not candidate_restricted",
            "return (true, saw_restricted and not saw_unrestricted, saw_unrestricted or allowed)",
            "family_count == 0.usize()")):
        raise SystemExit("Try subset coverage must union repeated family rows, with unrestricted rows covering the full family")
    empty_subset = compact_inline(function_section(source_text, "try_error_family_has_empty_subset"))
    if not all(fragment in empty_subset for fragment in (
            'row.owner == "__error_variant_family"',
            'allow.owner == "__error_variant_allow"',
            "return true if not has_matching_allow")):
        raise SystemExit("Try must recognize marker-only empty subsets as malformed metadata")
    family_covers = compact_inline(function_section(source_text, "error_family_covers"))
    if not all(fragment in family_covers for fragment in (
            "try_error_family_has_empty_subset(annotations, source)",
            "try_error_family_has_empty_subset(annotations, destination)")):
        raise SystemExit("Try must suppress propagation cascades from malformed source or destination subsets")
    statement_catch_marker = compact_inline(function_section(source_text, "try_noncall_statement_match_is_catch"))
    if 'marker.owner == "__catch_match" and marker.name == "__catch_match" and marker.line == position.line and marker.offset == position.offset and marker.module == lexical_module' not in statement_catch_marker:
        raise SystemExit("Try catchability must match statement Catch markers by exact source position and lexical module")
    fallback_atom_text = (ROOT / "test/atoms/try_fallback_source.elisa").read_text()
    fallback_atom_text += (ROOT / "test/atoms/try_fallback_noncall_cases.elisa").read_text()
    for helper_name, expected_count in (
            ("try_noncall_expression_directly_raises(", 3),
            ("try_noncall_block_directly_raises(", 4)):
        helper_calls = [line for line in fallback_atom_text.splitlines() if helper_name in line]
        if len(helper_calls) != expected_count or any(
                not re.search(r"(?:no_error_rows|no_annotations), \"\"\)$", line.strip())
                for line in helper_calls):
            raise SystemExit(f"Try fallback atom must pass annotations and lexical module to every {helper_name[:-1]} call")
    direct_raise = compact_inline(function_section(source_text, "try_noncall_expression_directly_raises"))
    if not all(fragment in direct_raise for fragment in (
            "annotations: darray[Ast::EnumAnnotation]&, lexical_module: sview",
            "try_noncall_statement_match_is_catch(position, annotations, lexical_module)",
            "return arms.count > 0 and catch_arms_raise if is_catch",
            "try_noncall_expression_aborts_with_annotations(scrutinee, annotations, lexical_module)")):
        raise SystemExit("Try direct-raise analysis must preserve lexical Catch identity and classify Catch arms separately from ordinary matches")
    direct_raise_block = compact_inline(function_section(source_text, "try_noncall_block_directly_raises"))
    if not all(fragment in direct_raise_block for fragment in (
            "annotations: darray[Ast::EnumAnnotation]&, lexical_module: sview",
            "try_noncall_single_statement_terminates_with_annotations(statement, annotations, lexical_module)",
            "try_noncall_block_terminates_with_annotations(selected_body, annotations, lexical_module)",
            "try_noncall_expression_directly_raises(Ast::Expr.Match(scrutinee, arms, position), annotations, lexical_module)")):
        raise SystemExit("Try direct-raise block recursion must preserve Catch marker annotations and lexical module context")
    direct_raise_arms = compact_inline(function_section(source_text, "try_noncall_match_bool_arms_directly_raise"))
    if not all(fragment in direct_raise_arms for fragment in (
            "annotations: darray[Ast::EnumAnnotation]&, lexical_module: sview",
            "try_noncall_expression_aborts_with_annotations(arm.guard, annotations, lexical_module)",
            "try_noncall_block_directly_raises(arm.body, annotations, lexical_module)")):
        raise SystemExit("Try direct-raise boolean arms must preserve annotations and lexical module context recursively")
    single_statement_termination = compact_inline(function_section(source_text, "try_noncall_single_statement_terminates_with_annotations"))
    if not all(fragment in single_statement_termination for fragment in (
            "try_noncall_statement_match_is_catch(position, annotations, lexical_module)",
            "try_noncall_block_terminates_with_annotations(then_body, annotations, lexical_module)",
            "try_noncall_block_terminates_with_annotations(else_body, annotations, lexical_module)",
            "try_noncall_match_bool_arms_terminate_with_annotations(arms, scrutinee_bool.value, annotations, lexical_module)")):
        raise SystemExit("Try statement termination must use the exact Catch-marker helper")
    block_termination = compact_inline(function_section(source_text, "try_noncall_block_terminates_with_annotations"))
    if "try_noncall_single_statement_terminates_with_annotations(statement, annotations, lexical_module)" not in block_termination:
        raise SystemExit("Try block termination must preserve Catch marker annotations and lexical module context")
    bool_match_termination = compact_inline(function_section(source_text, "try_noncall_match_bool_arms_terminate_with_annotations"))
    if not all(fragment in bool_match_termination for fragment in (
            "try_noncall_expression_aborts_with_annotations(arm.guard, annotations, lexical_module)",
            "try_noncall_block_terminates_with_annotations(arm.body, annotations, lexical_module)")):
        raise SystemExit("Try boolean-match termination must preserve Catch marker annotations and lexical module context")
    block_source_facts = compact_inline(function_section(source_text, "try_noncall_block_source_facts"))
    if "try_noncall_block_terminates_with_annotations(statements, annotations, environment.current_module)" not in block_source_facts:
        raise SystemExit("Try block source facts must use module-aware statement termination")
    assignment_source_facts = compact_inline(function_section(source_text, "try_noncall_assignment_source_facts"))
    if not all(fragment in assignment_source_facts for fragment in (
            "lexical_module: sview = environment.current_module",
            "try_noncall_expression_aborts_with_annotations(condition, annotations, lexical_module)",
            "try_noncall_expression_aborts_with_annotations(then_value, annotations, lexical_module)",
            "try_noncall_expression_aborts_with_annotations(else_value, annotations, lexical_module)",
            "try_noncall_expression_aborts_with_annotations(arm.guard, annotations, lexical_module)",
            "try_noncall_block_terminates_with_annotations(arm.body, annotations, lexical_module)")):
        raise SystemExit("Try assignment source facts must preserve Catch marker annotations and lexical module context through If, Match, and Catch branches")
    statement_catchability = compact_inline(function_section(source_text, "try_noncall_statements_may_raise_catchably_with_annotations"))
    if "try_noncall_statement_match_is_catch(match_position, annotations, lexical_module)" not in statement_catchability:
        raise SystemExit("Try statement catchability must use the exact Catch-marker helper")

    abort_helper = compact_inline(function_section(source_text, "try_noncall_expression_aborts_with_annotations"))
    if not all(fragment in abort_helper for fragment in (
            'lexical_module: sview = ""',
            "try_noncall_expression_aborts_with_annotations(callee, annotations, lexical_module)",
            "try_noncall_expression_aborts_with_annotations(guarded, annotations, lexical_module)",
            "try_noncall_expression_may_raise_catchably_with_annotations(guarded, annotations, lexical_module)",
            "try_noncall_block_terminates_with_annotations(statements, annotations, lexical_module)",
            "try_noncall_catch_error_arms_terminate(arms, annotations, lexical_module)")):
        raise SystemExit("Try abort analysis must preserve lexical module context through nested Catch expressions")
    catch_error_arms = compact_inline(function_section(source_text, "try_noncall_catch_error_arms_terminate"))
    if not all(fragment in catch_error_arms for fragment in (
            "try_noncall_expression_aborts_with_annotations(arm.guard, annotations, lexical_module)",
            "try_noncall_block_terminates_with_annotations(arm.body, annotations, lexical_module)")):
        raise SystemExit("Try Catch-arm termination must preserve annotations and lexical module context")
    may_raise = compact_inline(function_section(source_text, "try_noncall_expression_may_raise_catchably_with_annotations"))
    if "try_noncall_expression_aborts_with_annotations(callee, annotations, lexical_module)" not in may_raise:
        raise SystemExit("Try catchability analysis must pass lexical module context into abort analysis")
