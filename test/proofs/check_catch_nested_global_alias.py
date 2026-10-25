"""Bind Catch family lookup to Stage0's program-wide module alias behavior."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_catch_exhaustive.elisa"
FIXTURE = ROOT / "test/repro/catch_nested_global_alias.elisa"
SMOKE = ROOT / "test/parity/catch_nested_global_alias_smoke.sh"
NESTED_TARGET_FIXTURE = ROOT / "test/repro/catch_nested_alias_target.elisa"
NESTED_TARGET_SMOKE = ROOT / "test/parity/catch_nested_alias_target_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


source = SOURCE.read_text()
alias_lookup = function_source(source, "catch_module_alias_target")
qualifier_lookup = function_source(source, "catch_module_qualifier_alias_target")
alias_order = function_source(source, "catch_module_alias_order")
alias_context_order = function_source(source, "catch_module_alias_order_with_branch_context")
alias_branch_stack = function_source(source, "catch_module_alias_branch_stack")
alias_branch_prefix = function_source(source, "catch_module_alias_branch_stack_prefix")
alias_before = function_source(source, "catch_module_alias_row_is_before")
path_matches = function_source(source, "catch_module_alias_path_matches")
path_suffixes = function_source(source, "catch_module_alias_path_suffixes_match")
fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()
nested_target_fixture = NESTED_TARGET_FIXTURE.read_text()
nested_target_smoke = NESTED_TARGET_SMOKE.read_text()
if "catch_module_is_ancestor(alias.module, lexical_module)" in alias_lookup:
    raise SystemExit("program-wide Catch aliases must not be limited to lexical ancestors of the caller")
if not all(fragment in alias_lookup for fragment in (
        'alias.name != "__using_alias"',
        'target_row.name != "__using_alias_target"',
        "alias.module", "alias.offset",
        "target_count != 1.usize()",
        "candidate_order: (known: bool, precedes: bool) = catch_module_alias_order_with_branch_context(annotations, alias, selected_name, selected_scope, selected_line, selected_offset, selected_is_branch)",
        "candidate_precedes: bool = candidate_order.known and candidate_order.precedes",
        "alias_visibility: (known: bool, before: bool) = catch_module_alias_row_is_before(annotations, alias, lexical_module, declaration_line, declaration_offset)",
        "if not alias_visibility.known:",
        "visibility_uncertain <- true",
        "if visibility_uncertain and not found:",
        "order: (known: bool, precedes: bool) = catch_module_alias_order_with_branch_context(annotations, alias, selected_name, selected_scope, selected_line, selected_offset, selected_is_branch)",
        "alias_order_unknown <- true if not order.known or order.precedes",
        "return (false, true, alias_name, \"\", 0, 0) if ambiguous or selected_unknown or alias_order_unknown")):
    raise SystemExit("Catch alias lookup must pair global aliases with their exact target rows")
if not all(fragment in qualifier_lookup for fragment in (
        "catch_module_alias_target(annotations, alias_name, lexical_module, catch_line, 4294967295)",
        "target_alias_name: sview @source = candidate_path if target_separator == candidate_path.len else candidate_path[0:target_separator]",
        "catch_module_alias_target(annotations, target_alias_name, candidate_scope, candidate_line, candidate_offset)",
        "expanded_suffixes.push(target_suffix)",
        "return (true, false, candidate_path, candidate_scope, suffixes)",
        "candidate_scope",
        "candidate_offset")) or not all(fragment in alias_order for fragment in (
        "candidate_scope == selected_scope",
        "candidate_is_branch and not selected_is_branch",
        "not candidate_is_branch and selected_is_branch",
        "catch_module_is_ancestor(candidate_scope, selected_scope)",
        "catch_module_is_ancestor(selected_scope, candidate_scope)",
        "return (false, false) if candidate_is_branch or selected_is_branch",
        "return (false, false) if candidate_offset == selected_offset",
        "candidate_offset < selected_offset")) or not all(fragment in alias_context_order for fragment in (
        "candidate.module == selected_scope",
        "catch_module_alias_branch_stack(annotations, candidate_name, candidate.module, candidate.line, candidate.offset, candidate_is_branch)",
        "candidate_stack.rows.count < selected_stack.rows.count",
        "candidate_stack.rows.count == selected_stack.rows.count",
        "catch_module_is_ancestor(candidate.module, selected_scope)",
        "catch_module_alias_branch_stack_prefix(candidate_stack.rows, selected_stack.rows)")) or not all(fragment in alias_branch_stack for fragment in (
        'marker.name != "__using_alias_static_branch"',
        "marker.identity_id == 4294967295",
        "is_branch and not found_marker")) or not all(fragment in alias_branch_prefix for fragment in (
        "prefix.count > path.count",
        "prefix[index] != path[index]")) or not all(fragment in alias_before for fragment in (
        "declaration_offset == 4294967295",
        "candidate.module == declaration.module and candidate.line == declaration.line and candidate.offset == declaration.offset",
        "catch_module_alias_order_with_branch_context(annotations, candidate, declaration.owner, declaration.module, declaration.line, declaration.offset, declaration_is_branch)",
        "return (false, false)")) or not all(fragment in alias_order for fragment in (
        "return (false, false) if candidate_is_branch or selected_is_branch",
        "return (true, candidate_offset < selected_offset)")):
    raise SystemExit("Catch alias target chains must retain each alias declaration scope")
if not all(fragment in path_matches for fragment in (
        "if alias_scope != \"\"",
        "catch_module_path_prefix_end(alias_scope, candidate_module)",
        "relative_candidate: sview @source = candidate_module[scope_prefix.offset + 2.usize():candidate_module.len]",
        "catch_module_alias_path_suffixes_match(alias_module, relative_candidate, suffixes)")) or not all(fragment in path_suffixes for fragment in (
        "for suffix in suffixes",
        "suffix_match.found",
        "suffix_offset == candidate_module.len")):
    raise SystemExit("nested alias targets must be resolved relative to their declaration module")
if not all(fragment in fixture for fragment in (
        "module AliasInstaller:",
        "module NestedProvider:",
        "using NestedProvider as NestedGlobal",
        "catch NestedGlobal::load()",
        "AliasInstaller::NestedProvider::Fault.Expected")) or not all(fragment in smoke for fragment in (
        "catch_nested_global_alias.elisa",
        "Fault.Missing",
        "NestedGlobal")):
    raise SystemExit("nested module alias regression must check root-level Catch resolution")
if fixture.index("def catch_via_nested_global_alias") > fixture.index("module AliasInstaller:"):
    raise SystemExit("Catch regression must use the nested global alias before its module appears in source order")
if not all(fragment in nested_target_fixture for fragment in (
        "using Outer as First",
        "using First::Right as Second",
        "catch Second::Nested::load()",
        "Outer::Right::Nested::Fault.Expected")) or "catch_nested_alias_target.elisa" not in nested_target_smoke:
    raise SystemExit("nested alias-target regression must expand an alias in the head of a target path and preserve both suffixes")

print('Catch nested global alias source binding passed')
