"""Bind Catch alias family lookup to static-branch filtering source."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_catch_exhaustive.elisa"
PROOF = SOURCE.read_text()
EXTERN_ENUM_SOURCE = (ROOT / "src/parser/parser_extern_enum.elisa").read_text()
DECL_NAME_SOURCE = (ROOT / "src/parser/parser_decl.elisa").read_text()
ENUM_PARSER_SOURCE = (ROOT / "src/parser/parser_types_aggregate.elisa").read_text()
TRY_SOURCE = (ROOT / "src/semantic/check_try_fallible.elisa").read_text()
IMPL_SOURCE = (ROOT / "src/semantic/check_impl_conformance.elisa").read_text()
AMBIGUOUS_VARIANT_SOURCE = (ROOT / "src/semantic/check_ambiguous_error_variant.elisa").read_text()
PATTERN_SOURCE = ROOT / "src/semantic/check_progress_safety/pattern_reachability.elisa"
PATTERN_PROOF = PATTERN_SOURCE.read_text()
FIXTURE = (ROOT / "test/repro/catch_static_alias_branch.elisa").read_text()
FOREIGN_ENUM_INACTIVE_FIXTURE = (ROOT / "test/repro/catch_foreign_enum_all_inactive.elisa").read_text()
FOREIGN_ENUM_UNKNOWN_FIXTURE = (ROOT / "test/repro/catch_foreign_enum_unknown_origin.elisa").read_text()
SMOKE = (ROOT / "test/parity/catch_static_alias_branch_smoke.sh").read_text()
RELATIVE_FIXTURE = (ROOT / "test/repro/catch_relative_alias_target.elisa").read_text()
RELATIVE_SMOKE = (ROOT / "test/parity/catch_relative_alias_target_smoke.sh").read_text()
OUT_OF_SET_SOURCE = (ROOT / "src/semantic/check_catch_out_of_set.elisa").read_text()


def function_source(name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        PROOF,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


def pattern_function_source(name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        PATTERN_PROOF,
    )
    if match is None:
        raise SystemExit(f"missing pattern-reachability source helper {name}")
    return match.group(0)


def try_function_source(name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        TRY_SOURCE,
    )
    if match is None:
        raise SystemExit(f"missing Try source-bound helper {name}")
    return match.group(0)


def impl_function_source(name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        IMPL_SOURCE,
    )
    if match is None:
        raise SystemExit(f"missing impl-conformance source-bound helper {name}")
    return match.group(0)


def ambiguous_variant_function_source(name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        AMBIGUOUS_VARIANT_SOURCE,
    )
    if match is None:
        raise SystemExit(f"missing ambiguous-variant source-bound helper {name}")
    return match.group(0)


def out_of_set_function_source(name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        OUT_OF_SET_SOURCE,
    )
    if match is None:
        raise SystemExit(f"missing out-of-set source-bound helper {name}")
    return match.group(0)


filtering = function_source("catch_active_alias_annotations")
alias_lookup = function_source("catch_module_alias_target")
alias_is_branch = function_source("catch_module_alias_is_static_branch")
alias_unknown_marker = function_source("catch_module_alias_annotation_is_unknown")
alias_marker_name = function_source("catch_module_alias_annotation_name")
alias_order = function_source("catch_module_alias_order")
alias_context_order = function_source("catch_module_alias_order_with_branch_context")
alias_branch_stack = function_source("catch_module_alias_branch_stack")
alias_is_unresolved = function_source("catch_module_alias_is_unresolved")
entry = function_source("check_catch_exhaustive")
pattern_lookup = pattern_function_source("progress_catch_module_path_matches_scoped")
pattern_alias_before = pattern_function_source("progress_catch_module_alias_row_is_before")
pattern_explicit_family = pattern_function_source("progress_catch_explicit_family_module")
qualifier_alias_lookup = function_source("catch_module_qualifier_alias_target")
catch_declaration_lookup = function_source("catch_error_declaration_with_occurrence")
catch_alias_ancestor = function_source("catch_module_alias_path_matches_ancestor")
catch_family_lookup = function_source("catch_explicit_error_family_module")
catch_module_parent = function_source("catch_module_parent_path")
catch_family_candidate = function_source("catch_error_family_module_candidate")
catch_family_module = function_source("catch_error_family_module")
catch_family_for_declaration = function_source("catch_error_family_module_for_declaration")
catch_synthetic_origin_branch = function_source("catch_synthetic_error_set_origin_branch_selection")
catch_error_set_branch = function_source("catch_error_set_declaration_branch_selection")
catch_family_subset = function_source("catch_family_is_subset")
catch_family_rows = function_source("catch_family_row_allows_variant")
catch_family_variant_branch = function_source("catch_error_set_variant_branch_state")
catch_family_missing = function_source("catch_family_first_missing")
catch_variant_row_first = function_source("catch_error_variant_table_row_is_first")
catch_exhaustive_rows = function_source("check_catch_exhaustive_rows")
catch_projection = function_source("catch_active_alias_annotations")
out_error_return = out_of_set_function_source("cos_error_return_declaration")
out_subset_path = out_of_set_function_source("cos_subset_family_path")
out_subset_path_check = out_of_set_function_source("cos_path_is_out_of_subset")
out_pattern_handles = out_of_set_function_source("cos_pattern_handles_tag")
out_pair_handled = out_of_set_function_source("cos_pair_handled")
out_catch_arms = out_of_set_function_source("cos_check_catch_arms")
out_entry = out_of_set_function_source("check_catch_out_of_set")
try_alias_path_lookup = try_function_source("try_error_alias_module_path_matches")
impl_family_lookup = impl_function_source("imc_resolve_error_family_module")
impl_family_matches = impl_function_source("imc_error_family_matches")
impl_family_subset_matches = impl_function_source("imc_error_family_subset_matches")
impl_protocol_family_rows = impl_function_source("imc_protocol_method_errors")
impl_conformance_entry = impl_function_source("check_impl_conformance")
ambiguous_variant_module = ambiguous_variant_function_source("aev_function_module_for_family")
if not all(fragment in filtering for fragment in (
    'annotation.name == "__using_alias"',
    "ewr_static_import_annotation_selection(annotation, file.enum_annotations, file, table)",
    "continue if branch.known and not branch.active",
    'owner: "__catch_unknown_static_alias"',
    "active.push(annotation)",
)):
    raise SystemExit("Catch alias preprocessing must remove inactive aliases and mark unresolved branches")
if not all(fragment in alias_is_branch for fragment in (
    "catch_module_alias_annotation_is_unknown(alias)",
    'marker.name == "__using_alias_static_branch"',
    "marker.detail_name == alias.owner",
)) or not all(fragment in alias_order for fragment in (
    "candidate_scope == selected_scope",
    "candidate_is_branch and not selected_is_branch",
    "not candidate_is_branch and selected_is_branch",
    "catch_module_is_ancestor(candidate_scope, selected_scope)",
    "return (true, true) if not candidate_is_branch",
    "return (false, false) if candidate_is_branch or selected_is_branch",
    "return (false, false) if candidate_offset == selected_offset",
    "candidate_offset < selected_offset",
)) or not all(fragment in alias_context_order for fragment in (
    "candidate_stack.rows.count < selected_stack.rows.count",
    "candidate_stack.rows.count == selected_stack.rows.count",
    "catch_module_is_ancestor(candidate.module, selected_scope)",
    "catch_module_alias_branch_stack_prefix(candidate_stack.rows, selected_stack.rows)",
    "catch_module_alias_is_unresolved(annotations, candidate_name, candidate.module, candidate.line, candidate.offset)",
    "catch_module_alias_is_unresolved(annotations, selected_name, selected_scope, selected_line, selected_offset)",
    "candidate.offset < selected_offset",
    "return (false, false)",
)) or not all(fragment in alias_branch_stack for fragment in (
    'marker.name != "__using_alias_static_branch"',
    "marker.identity_id == 4294967295",
    "is_branch and not found_marker",
)) or not all(fragment in alias_is_unresolved for fragment in (
    "catch_module_alias_annotation_is_unknown(alias)",
    "catch_module_alias_annotation_name(alias) == alias_name",
    "alias.module == alias_scope",
    "alias.line == alias_line",
    "alias.offset == alias_offset",
)) or not all(fragment in alias_lookup for fragment in (
    "catch_module_alias_annotation_is_unknown(alias)",
    "catch_module_alias_annotation_name(alias)",
    "catch_module_alias_order_with_branch_context(annotations, alias, selected_name, selected_scope, selected_line, selected_offset, selected_is_branch)",
    "catch_module_alias_is_static_branch(annotations, alias)",
    "selected_is_branch <- candidate_is_branch",
    'return (false, true, alias_name, "", 0, 0) if ambiguous or selected_unknown or alias_order_unknown',
)) or "catch_active_alias_annotations(file, table)" not in entry:
    raise SystemExit("Catch alias resolution must prefer unconditional registrations, preserve first-in-class order, and keep unresolved winners unknown")
if not all(fragment in alias_unknown_marker for fragment in (
    'alias.owner == "__catch_unknown_static_alias"',
    'alias.owner == "__pma_unknown_static_import" and alias.detail_name == "__using_alias"',
    'alias.owner == "__try_unresolved_static_binding" and alias.name == "__using_alias"')) or not all(fragment in alias_marker_name for fragment in (
    'alias.owner == "__try_unresolved_static_binding" and alias.name == "__using_alias"',
    "return alias.detail_name",
    "catch_module_alias_annotation_is_unknown(alias)",
    "return alias.name")) or not all(fragment in qualifier_alias_lookup for fragment in (
    "catch_module_alias_target(annotations, alias_name, lexical_module, catch_line, 4294967295)",
    "alias_target.uncertain",
    'return (false, true, "", "", suffixes)',
    'return (true, false, candidate_path, candidate_scope, suffixes)')):
    raise SystemExit("qualified alias lookup must normalize Catch, PMA, and Try uncertainty and block raw fallback")
if not all(fragment in catch_declaration_lookup for fragment in (
    "alias_target.uncertain",
    'return (false, callee, 0, 0, 0, 0) if alias_target.uncertain',
    "catch_module_alias_path_matches_ancestor(alias_target.module, alias_target.scope, alias_target.suffixes, candidate_module)')) or not all(fragment in catch_alias_ancestor for fragment in (
    "catch_module_alias_path_matches(alias_module, scope, suffixes, candidate_module)",
    "scope <- catch_module_parent_path(scope)",
    'break if scope == ""')) or not all(fragment in catch_family_lookup for fragment in (
    "qualified_separator: usize = catch_first_module_separator_start(path[0:path_end])",
    'return (false, true, "") if path_end < family.len',
    'return (false, true, "") if not path_has_family',
    "if separator == path.len",
    'return (false, false, family) if catch_module_path_matches(path[0:path_end], family)',
    'return (false, true, "") if not qualified_path',
    "alias_target.uncertain",
    'return (false, true, "") if alias_target.uncertain',
    'return (false, true, "")')):
    raise SystemExit("qualified Catch ErrorSet misses and ambiguous matches must stay blocked")
if catch_family_lookup.index("if separator == path.len") > catch_family_lookup.index('return (false, true, "") if not qualified_path'):
    raise SystemExit("Catch must allow the exact bare-family exception before rejecting malformed unqualified paths")
if not all(fragment in catch_family_candidate for fragment in (
    'declaration.owner != "__error_set_decl" and declaration.owner != "__catch_unknown_error_set_decl"',
    "candidate_module: sview @source = declaration.module",
    "catch_module_alias_path_matches(path_module, path_scope, suffixes, candidate_module)",
    "allow_direct and catch_module_path_matches(path_module, candidate_module)",
    'declaration.owner == "__catch_unknown_error_set_decl"',
    "elif selected_module != candidate_module",
    "ambiguous <- true")) or not all(fragment in catch_module_parent for fragment in (
    "module_path[offset] == 58 and module_path[offset + 1.usize()] == 58",
    "return module_path[0:separator]")) or not all(fragment in catch_family_lookup for fragment in (
    "lexical_scope: mutable sview @source = function_module",
    "catch_error_family_module_candidate(annotations, family, raw_module, lexical_scope, empty_suffixes, false, table)",
    "lexical_scope <- catch_module_parent_path(lexical_scope)",
    "catch_module_qualifier_alias_target(annotations, raw_module, function_module, declaration_line, declaration_offset)",
    "alias_scope: mutable sview @source = alias_target.scope",
    "catch_error_family_module_candidate(annotations, family, alias_target.module, alias_scope, alias_target.suffixes, false, table)",
    "alias_scope <- catch_module_parent_path(alias_scope)",
    'catch_error_family_module_candidate(annotations, family, raw_module, "", empty_suffixes, true, table)')) or not (
        catch_family_lookup.index("catch_error_family_module_candidate(annotations, family, raw_module, lexical_scope") <
        catch_family_lookup.index("catch_module_qualifier_alias_target(annotations, raw_module") <
        catch_family_lookup.index("catch_error_family_module_candidate(annotations, family, alias_target.module") <
        catch_family_lookup.index('catch_error_family_module_candidate(annotations, family, raw_module, "", empty_suffixes, true, table)')):
    raise SystemExit("qualified Catch ErrorSet candidates must search ancestor-relative paths, then aliases, then raw spelling")
if not all(fragment in catch_error_set_branch for fragment in (
    'name_row.owner != "__lsp_decl_name"',
    "name_row.pos.offset != annotation.offset",
    "name_row.line != annotation.line",
    'marker.name != "__nominal_type_static_branch"',
    "marker.detail_name != annotation.name",
    "marker.module != annotation.module",
    "marker.line != annotation.line",
    "marker.offset != declaration_keyword_offset",
    "ewr_static_if_row_selection(file, marker.identity_id.usize(), marker.module, table)",
    "return (true, false) if branch.known and not branch.selected",
    "return (false, false) if found_marker and unknown")) or not all(fragment in catch_projection for fragment in (
    'annotation.owner == "__error_set_decl"',
    "catch_error_set_declaration_branch_selection(annotation, file.enum_annotations, file, table)",
    'owner: "__catch_unknown_error_set_decl"')) or not all(fragment in catch_family_module for fragment in (
    'declaration.owner != "__error_set_decl" and declaration.owner != "__catch_unknown_error_set_decl"',
    "scoped_unknown <- true",
    "return (false, family) if scoped_found and (scoped_ambiguous or scoped_unknown)")) or "return (true, explicit_module.module)" not in catch_family_for_declaration or not all(fragment in catch_family_variant_branch for fragment in (
    "Decl.Module(module_name, body, _)",
    "Decl.Scoped(body, _)",
    'row.owner == "__error_set_decl"',
    "row.pos.offset",
    "catch_error_set_declaration_branch_selection(selected_declaration, annotations, file, table)",
    "uncertain <- true if not branch.known")) or not all(fragment in catch_family_missing for fragment in (
    "catch_error_set_variant_branch_state(file.top_decls",
    "not family_branch.found or family_branch.uncertain or not family_branch.active",
    "variant_branch.found and variant_branch.active and not variant_branch.uncertain",
    "catch_error_variant_table_row_is_first(table, variant_index")) or not all(fragment in catch_variant_row_first for fragment in (
    "table.enum_variant_owner[previous] == family",
    "table.enum_variant_module[previous] == family_module",
    "table.enum_variant_name[previous] == variant")) or "table <- check_catch_exhaustive_rows(annotations, file, table)" not in entry:
    raise SystemExit("Catch ErrorSet lookup must resolve empty families while excluding inactive static declarations and blocking unknown candidates")
if not all(fragment in EXTERN_ENUM_SOURCE for fragment in (
    'owner: "__error_set_synthetic_origin", name: "ForeignEnum", detail_name: enum_name',
    'synthetic_family_emitted: bool = any row in parser.enum_annotations where row.owner == "__error_set_synthetic" and row.name == "ForeignEnum"',
    'if not already_emitted or synthetic_family_emitted:',
    'owner: "__error_set_synthetic", name: "ForeignEnum"',
    "This shared generated family has no source name token of its own.",
    "include the family when any producer is active")) or not all(fragment in catch_synthetic_origin_branch for fragment in (
    'name_row.owner != "__lsp_decl_name"',
    "name_row.name != origin.detail_name",
    "name_row.line != origin.line",
    "name_row.offset != origin.offset",
    "origin_name_rows != 1.usize()",
    'marker.name != "__nominal_type_static_branch"',
    "marker.detail_name != origin.detail_name",
    "marker.module != origin.module",
    "marker.line != origin.line",
    "marker.offset != origin.offset",
    "branch.known and not branch.selected",
    "return (true, true)",
    "return (false, false) if found_marker and unknown")) or not all(fragment in catch_error_set_branch for fragment in (
    'marker.owner != "__error_set_synthetic"',
    "marker.name != annotation.name",
    "marker.module != annotation.module",
    "marker.line != annotation.line",
    "marker.offset != annotation.offset",
    'annotation.owner != "__error_set_decl" or annotation.name != "ForeignEnum" or synthetic_marker_count != 1.usize()',
    'origin.owner != "__error_set_synthetic_origin" or origin.name != annotation.name',
    "origin_count == 0.usize() or unknown_origin",
    "active_origin <- true if origin_branch.known and origin_branch.active",
    "unknown_origin <- true if not origin_branch.known",
    "return (true, true) if active_origin",
    "return (true, false)")) or not all(fragment in catch_family_variant_branch for fragment in (
    'marker.owner != "__error_set_synthetic"',
    "marker.name != name",
    "marker.module != lexical_module",
    "marker.line != declaration_pos.line",
    "marker.offset != declaration_pos.offset",
    "synthetic_marker_count == 1.usize()",
    "name_row_count == 0.usize() and synthetic_marker_count == 1.usize()",
    "name_offset <- declaration_pos.offset",
    'row.owner == "__error_set_decl"')):
    raise SystemExit("the shared generated ForeignEnum family must reduce exact producer branch provenance")
if not (
    EXTERN_ENUM_SOURCE.index("return declaration if is_open or member_names.count == 0") <
    EXTERN_ENUM_SOURCE.index('owner: "__error_set_synthetic_origin", name: "ForeignEnum"') and
    EXTERN_ENUM_SOURCE.index('if not already_emitted or synthetic_family_emitted:') <
    EXTERN_ENUM_SOURCE.index('owner: "__error_set_synthetic_origin", name: "ForeignEnum"') and
    'offset: declaration_token.start, pos: name_pos' in DECL_NAME_SOURCE and
    'parser <- parser.record_lsp_declaration_name(name_text, token, name_token, name_token)' in ENUM_PARSER_SOURCE and
    'parser <- parser.record_static_if_branch_rows("__nominal_type_static_branch", name_text, token)' in ENUM_PARSER_SOURCE
):
    raise SystemExit("synthetic origins must be closed nonempty extern enums joined through declaration-keyword offsets and nominal branch markers")
if not (
    catch_synthetic_origin_branch.index("return (true, false) if branch.known and not branch.selected") <
    catch_synthetic_origin_branch.index("return (false, false) if found_marker and unknown") <
    catch_synthetic_origin_branch.index("return (true, true)") and
    catch_error_set_branch.index("return (true, true) if active_origin") <
    catch_error_set_branch.index("return (false, false) if origin_count == 0.usize() or unknown_origin") <
    catch_error_set_branch.index("return (true, false)")
):
    raise SystemExit("ForeignEnum aggregation must prefer a proven active origin, then preserve uncertainty, then exclude all-inactive origins")
if not all(fragment in FIXTURE for fragment in (
    "DISABLE_FOREIGN_ENUM_SOURCE: bool = false",
    "static if DISABLE_FOREIGN_ENUM_SOURCE:",
    "extern enum DormantDeviceState of i32:",
    "extern enum ActiveDeviceState of i32:",
    "extern foreign_enum_source() -> i64 error[ForeignEnum]",
    "generated_foreign_enum_family_remains_known")) or not all(fragment in SMOKE for fragment in (
    "non-exhaustive catch over ForeignEnum; missing ForeignEnum.OutOfRange",
    '"$foreign_enum_count" != 1')):
    raise SystemExit("Catch static-branch smoke must preserve the generated ForeignEnum family when its first producer is inactive")
if FIXTURE.index("extern enum DormantDeviceState of i32:") > FIXTURE.index("extern enum ActiveDeviceState of i32:"):
    raise SystemExit("the ForeignEnum fixture must keep its inactive producer before the later active producer")
if not all(fragment in FOREIGN_ENUM_INACTIVE_FIXTURE for fragment in (
    "ENABLE_INACTIVE_FOREIGN_ENUM_ORIGIN: bool = false",
    "static if ENABLE_INACTIVE_FOREIGN_ENUM_ORIGIN:",
    "extern enum InactiveDeviceState of i32:",
    "extern inactive_foreign_enum_source() -> i64 error[ForeignEnum]",
    "catch inactive_foreign_enum_source():",
    "all_foreign_enum_origins_inactive")) or not all(fragment in FOREIGN_ENUM_UNKNOWN_FIXTURE for fragment in (
    "static if UNKNOWN_FOREIGN_ENUM_ORIGIN:",
    "extern enum UnknownDeviceState of i32:",
    "extern unknown_foreign_enum_source() -> i64 error[ForeignEnum]",
    "catch unknown_foreign_enum_source():",
    "unknown_foreign_enum_origin_stays_uncertain")) or not all(fragment in SMOKE for fragment in (
    "catch_foreign_enum_all_inactive.elisa",
    "catch_foreign_enum_unknown_origin.elisa",
    "grep -q 'non-exhaustive catch over ForeignEnum' <<< \"$all_inactive_foreign_enum_report\"",
    "grep -q 'non-exhaustive catch over ForeignEnum' <<< \"$unknown_foreign_enum_report\"",
    "whose producers are all inactive",
    "unresolved producer branch")):
    raise SystemExit("Catch smoke must preserve all-inactive and unknown-only synthetic-family regressions")
if not (
    FOREIGN_ENUM_INACTIVE_FIXTURE.index("static if ENABLE_INACTIVE_FOREIGN_ENUM_ORIGIN:") <
    FOREIGN_ENUM_INACTIVE_FIXTURE.index("extern enum InactiveDeviceState of i32:") <
    FOREIGN_ENUM_INACTIVE_FIXTURE.index("extern inactive_foreign_enum_source() -> i64 error[ForeignEnum]") <
    FOREIGN_ENUM_INACTIVE_FIXTURE.index("catch inactive_foreign_enum_source():")
):
    raise SystemExit("all-inactive regression must catch the family produced by its inactive extern enum")
if not (
    FOREIGN_ENUM_UNKNOWN_FIXTURE.index("static if UNKNOWN_FOREIGN_ENUM_ORIGIN:") <
    FOREIGN_ENUM_UNKNOWN_FIXTURE.index("extern enum UnknownDeviceState of i32:") <
    FOREIGN_ENUM_UNKNOWN_FIXTURE.index("extern unknown_foreign_enum_source() -> i64 error[ForeignEnum]") <
    FOREIGN_ENUM_UNKNOWN_FIXTURE.index("catch unknown_foreign_enum_source():")
):
    raise SystemExit("unknown-only regression must catch the family produced by its unresolved extern enum")
if not all(fragment in catch_family_lookup for fragment in (
    "alias_scope: mutable sview @source = alias_target.scope",
    "catch_error_family_module_candidate(annotations, family, alias_target.module, alias_scope, alias_target.suffixes, false, table)",
    "alias_scope <- catch_module_parent_path(alias_scope)",
    'break if alias_scope == ""')) or not all(fragment in RELATIVE_FIXTURE for fragment in (
    "module RootProvider:",
    "module Outer:",
    "using Inner as Local",
    "using RootProvider as RootLocal",
    "error[Local::Fault]",
    "error[RootLocal::Fault]",
    "sibling_alias_family_incomplete",
    "root_alias_family_incomplete",
    "Outer::Inner::Fault.Expected",
    "RootProvider::Fault.Expected")) or not all(fragment in RELATIVE_SMOKE for fragment in (
    "catch_relative_alias_target.elisa",
    "diagnostic_count\" != 3",
    "sibling and root alias targets")):
    raise SystemExit("Catch ErrorSet alias targets must retry ancestor-relative scopes and retain untouched suffixes")
if "return false if declaration_line == 0" in catch_family_subset or not all(fragment in catch_family_subset for fragment in (
    "family_annotation.line != declaration_line",
    "family_annotation.offset != declaration_offset",
    "family_annotation.identity_id != declaration_identity_id",
    "family_annotation.occurrence_offset != occurrence_offset",
    "occurrence_offset == 0 and family_path == \"\" and declaration_offset != 0 and declaration_identity_id != 0",
    "annotation.offset == declaration_offset",
    "annotation.identity_id == declaration_identity_id")) or not all(fragment in catch_family_rows for fragment in (
    "family_annotation.offset != declaration_offset",
    "family_annotation.identity_id != declaration_identity_id")) or not all(fragment in catch_exhaustive_rows for fragment in (
    "family_annotation.offset != function_declaration.offset",
    "family_annotation.identity_id != function_declaration.identity_id")):
    raise SystemExit("Catch subset joins must preserve exact declaration identity when logical line or byte offset is zero")
if not all(fragment in out_error_return for fragment in (
    "module_annotation.offset == annotation.offset",
    "module_annotation.identity_id == annotation.identity_id")) or not all(fragment in out_subset_path for fragment in (
    "family_annotation.offset != declaration_offset",
    "family_annotation.identity_id != declaration_identity_id")) or not all(fragment in out_subset_path_check for fragment in (
    "family_annotation.offset != declaration_offset",
    "family_annotation.identity_id != declaration_identity_id",
    "catch_error_set_variant_branch_state(file.top_decls",
    "not branch.found or not branch.active or branch.uncertain",
    "catch_error_variant_table_row_is_first(table, variant_index")) or not all(fragment in out_pattern_handles for fragment in (
    "catch_path_has_variant(path, function_module",
    "annotations, file, table")) or not all(fragment in out_pair_handled for fragment in (
    "cos_pattern_handles_tag(arm.pattern",
    "family_module, file, table")) or not all(fragment in out_catch_arms for fragment in (
    "subset_family.offset == declaration_offset",
    "subset_family.identity_id == declaration_identity_id",
    "cos_check_pattern_out_of_subset(arm.pattern",
    "return_occurrence_offset, function_module, match_line, file, table",
    "catch_error_set_variant_branch_state(file.top_decls, \"\", sub_families[pair_index], sub_modules[pair_index], sub_variants[pair_index], file.enum_annotations, file, table)",
    "if branch.found and branch.active and not branch.uncertain",
    "cos_pair_handled(arms, annotations",
    "sub_modules[pair_index], file, table")) or not (
    out_catch_arms.index("if branch.found and branch.active and not branch.uncertain") <
    out_catch_arms.index("cos_pair_handled(arms, annotations") <
    out_catch_arms.index("missing_index <- pair_index")) or not all(fragment in out_entry for fragment in (
    "catch_active_alias_annotations(file, table)",
    "cos_walk_declarations(file.top_decls, \"\", annotations, file, table)")):
    raise SystemExit("Catch out-of-set subset rows must join exact parser offsets and identities, including zero")
if not all(fragment in function_source("catch_error_family_module_for_declaration") for fragment in (
    "explicit_module.uncertain",
    'return (false, family) if explicit_module.uncertain')) or not all(fragment in try_alias_path_lookup for fragment in (
    "alias_target.uncertain",
    "return false if alias_target.uncertain")):
    raise SystemExit("Catch, Try, and error-family consumers must not retry raw module matching after an unresolved alias")
if not all(fragment in impl_family_lookup for fragment in (
        "-> (known: bool, path_comparable: bool, module: sview @source)",
        "catch_explicit_error_family_module(raw_path, declaration_line, declaration_offset, declaration_identity_id, function_module.module, family, annotations, table)",
        'return (false, false, family) if explicit.uncertain',
        "return (true, true, explicit.module) if explicit.found",
        "return (resolved.known, true, resolved.module)")) or "path_end >= family.len" in impl_family_lookup or "catch_module_path_matches(path[path_end - family.len:path_end], family)" in impl_family_lookup or impl_family_lookup.index("explicit.uncertain") > impl_family_lookup.index("resolved: (known: bool, module: sview @source) = catch_error_family_module") or not all(fragment in impl_family_matches for fragment in (
        "path_comparable: bool",
        "expected.path_comparable and path_comparable",
        "not expected.module_known and not module_known")) or not all(fragment in impl_family_subset_matches for fragment in (
        "path_comparable: bool",
        "imc_error_family_matches(allowed, family, path, module_known, module, path_comparable)",
        "expected.path_comparable and path_comparable")) or not all(fragment in impl_protocol_family_rows for fragment in (
        "family_module.path_comparable",
        "path_comparable: family_module.path_comparable")) or not all(fragment in impl_conformance_entry for fragment in (
        "family_module.path_comparable",
        "imc_error_family_subset_matches(allowed, annotation.name, path, family_module.known, family_module.module, family_module.path_comparable, subset)")):
    raise SystemExit("impl conformance must preserve qualified alias uncertainty instead of falling back to a raw same-leaf family")
if not all(fragment in ambiguous_variant_module for fragment in (
        "same_offset: bool = declaration.offset == family.offset",
        "same_identity: bool = family.identity_id == 0 or declaration.identity_id == family.identity_id",
        "same_occurrence: bool = declaration.occurrence_offset == family.occurrence_offset",
        "continue if not same_offset or not same_identity or not same_occurrence")):
    raise SystemExit("ambiguous error-variant module lookup must join the exact family declaration and ErrorSet occurrence")
if not all(fragment in pattern_lookup for fragment in (
    "-> (known: bool, matches: bool)",
    "table.possible_import_annotations",
    "table.definite_import_annotations",
    "progress_catch_module_alias_row_is_before(alias, lexical_scope, before_offset, table)",
    "semantic_possible_import_alias_precedes(alias, selected_alias, table)",
    "semantic_possible_import_alias_precedes(possible_alias, selected_alias, table)",
    "target_count != 1.usize()",
    "return (false, false)",
)) or not all(fragment in pattern_explicit_family for fragment in (
    "candidate_match.known",
    "candidate_match.matches",
)) or "semantic_possible_import_alias_precedes_position(candidate, declaration_scope, declaration_offset, table)" not in pattern_alias_before:
    raise SystemExit("Catch progress-family alias resolution must exclude inactive aliases and keep unresolved winners unknown")
if not all(fragment in FIXTURE for fragment in (
    "error Fault:\n    Missing",
    "module EmptyFamilyProvider:\n    public:\n        extern load() -> i64 error[EmptyFamilyProvider::Fault]",
    "def qualified_family_miss_does_not_select_root_fault() -> i64:\n    catch EmptyFamilyProvider::load():\n        value: 0",
    "module Provider:\n    public:\n        error Fault:\n            RootOnly",
    "module RelativeParent:\n    module Provider:\n        public:\n            error Fault:\n                Expected\n                Missing",
    "module Consumer:\n        extern load() -> i64 error[Provider::Fault]",
    "relative_family_path_incomplete",
    "Provider::Fault.Expected",
    "module EmptyScope:\n    module Provider:\n        error Fault:\n    module Consumer:\n        extern load() -> i64 error[Provider::Fault]",
    "relative_empty_family_does_not_select_root_provider",
    "error SubsetFault:\n    Allowed\n    Excluded",
    "const USE_BRANCH_ERROR_SET: bool = true",
    "error BranchFault:\n        Expected\n        Missing",
    "error BranchFault:\n        InactiveOnly",
    "inactive_error_set_variant_does_not_join_family",
    "BranchFault.Expected",
    "const USE_BRANCH_SUBSET: bool = true",
    "error BranchSubsetFault:\n        Allowed",
    "error BranchSubsetFault:\n        Allowed\n        InactiveOnly",
    "restricted_branch_subset() -> i64 error[BranchSubsetFault{Allowed}]",
    "static_subset_deduplicates_active_variant",
    "BranchSubsetFault.Allowed",
    "#line 0 catch-line-zero-subset.elisa",
    "extern restricted_subset() -> i64 error[SubsetFault{Allowed}]",
    "line_zero_subset_is_exhaustive",
    "SubsetFault.Allowed",
    "const USE_ACTIVE_PROVIDER: bool = true",
    "using ActiveProvider as DirectWins",
    "using InactiveProvider as DirectWins",
    "static if USE_ACTIVE_PROVIDER:",
    "using ActiveProvider as Selected",
    "static else:",
    "using InactiveProvider as Selected",
    "static if UNKNOWN_PROVIDER_CHOICE:",
    "using InactiveProvider as Later",
    "static if UNKNOWN_PROVIDER_CHOICE:\n    using InactiveProvider as Later\nstatic else:\n    using InactiveProvider as Later",
    "using ActiveProvider as Later",
    "WrongOnly",
    "catch Selected::load()",
    "catch Later::load()",
    "catch DirectWins::load()",
    "using ActiveProvider as ParentWins",
    "module NestedAliasInstaller:",
    "using InactiveProvider as ParentWins",
    "def parent_direct_alias_precedes_nested_branch()",
    "catch ParentWins::load()",
    "module NestedBranchAlias:",
    "using InactiveProvider as BranchContextWins",
    "using ActiveProvider as BranchContextWins",
    "def parent_branch_block_precedes_nested_module()",
    "catch BranchContextWins::load()",
    "using ActiveProvider as SeparateRootFirstWins",
    "using InactiveProvider as SeparateRootFirstWins",
    "def separate_active_branch_roots_select_first_alias()",
    "catch SeparateRootFirstWins::load()",
    "static if UNKNOWN_PROVIDER_CHOICE:\n    using InactiveProvider as UnknownBranchWinner\nstatic if USE_ACTIVE_PROVIDER:\n    using ActiveProvider as UnknownBranchWinner",
    "using InactiveProvider as UnknownBranchWinner",
    "using ActiveProvider as UnknownBranchWinner",
    "def unresolved_branch_does_not_guess_alias_winner()",
    "catch UnknownBranchWinner::load()",
    "ActiveProvider::Fault.Expected",
    "error[Selected::Fault]",
    "selected_family_incomplete",
    "direct_alias_precedes_branch",
)) or not all(fragment in SMOKE for fragment in (
    "catch_static_alias_branch.elisa",
    "Fault.Missing",
    "diagnostic_count\" != 8",
    "WrongOnly",
    "RootOnly",
    "SubsetFault.Excluded",
    "non-exhaustive catch over BranchFault; missing BranchFault.Missing",
    "BranchFault.InactiveOnly",
    "BranchSubsetFault",
)):
    raise SystemExit("Catch static-alias regression must select active aliases, keep qualified misses from rebinding to root Fault, and let direct aliases precede later active branches")

print("Catch static-alias source binding passed")
