"""Bind unknown-type checks to active static scopes and exact alias identities."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_unknown_type_name.elisa"
PIPELINE = ROOT / "src/semantic/semantic_api/full_pipeline.elisa"
FIXTURE = ROOT / "test/repro/unknown_type_in_inactive_static_scopes.elisa"
SMOKE = ROOT / "test/parity/unknown_type_in_inactive_static_scopes_smoke.sh"
PARSER_DISPATCH = ROOT / "src/parser/parser_decl_dispatch.elisa"
PARSER_LAW = ROOT / "src/parser/parser_decl_law.elisa"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


source = SOURCE.read_text()
scope = function_source(source, "unknown_type_static_scope_is_inactive")
alias_activity = function_source(source, "unknown_type_alias_index_activity")
inactive_alias = function_source(source, "unknown_type_alias_index_is_inactive")
registered_type = function_source(source, "unknown_type_is_registered")
unresolved_type = function_source(source, "unknown_type_is_unresolved")
alias_cycles = function_source(source, "type_alias_cycle_info")
cyclic_lookup = function_source(source, "type_alias_name_is_cyclic")
alias_target = function_source(source, "alias_target_unresolved")
type_annotation = function_source(source, "check_type_annotation")
protocol_state = function_source(source, "is_protocol_state_argument")
interned_elements = function_source(source, "check_interned_elements")
alias_walk = function_source(source, "check_alias_target_declarations")
body_walk = function_source(source, "check_unknown_types_in_body")
declaration_walk = function_source(source, "check_unknown_type_name_in")
entrypoint = function_source(source, "check_unknown_type_name")
alias_entrypoint = function_source(source, "check_alias_target_type")
pipeline = PIPELINE.read_text()
parser_dispatch = PARSER_DISPATCH.read_text()
parser_law = PARSER_LAW.read_text()
if not all(fragment in scope for fragment in (
        "pma_static_if_row_for_position(file, position)",
        "pma_static_if_row_selection(file, branch_row, current_module, table)",
        "branch.known and not branch.selected")):
    raise SystemExit("unknown-type static pruning must use exact positions and skip only proven-inactive rows")
alias_marker = function_source(source, "unknown_type_alias_declaration_activity")
if not all(fragment in alias_marker for fragment in (
        'marker.owner != "__static_if_branch"',
        'marker.name != "__type_alias_static_branch"',
        "marker.detail_name != alias_name",
        "marker.module != alias_module",
        "marker.line != position.line",
        "marker.offset != position.offset",
        "if marker.identity_id == 4294967295:",
        "unknown <- true",
        "continue",
        "pma_static_if_row_selection(file, marker.identity_id.usize(), marker.module, table)",
        "return (true, false) if branch.known and not branch.selected",
        "unknown <- true if not branch.known",
        "return (false, false) if unknown",
        "return (true, true)")):
    raise SystemExit("alias visibility must distinguish active, inactive, and unresolved exact declaration markers")
if not all('record_static_if_branch_rows("__type_alias_static_branch", alias_name, token)' in parser for parser in (parser_dispatch, parser_law)):
    raise SystemExit("type and refine aliases must both emit the exact static-branch identity consumed by unknown-type lookup")
if not all(fragment in alias_activity for fragment in (
        "alias_index >= table.type_alias_declarations.count",
        "return (false, true)",
        "declaration.module_owner != table.type_alias_module[alias_index]",
        "declaration.pos",
        "unknown_type_alias_declaration_activity")) or not all(fragment in inactive_alias for fragment in (
        "activity.known and not activity.active")):
    raise SystemExit("alias branch lookup must preserve unresolved rows while binding markers through exact declarations")
if not all(fragment in registered_type for fragment in (
        "if symbol.kind == SymbolKind.Extern:",
        "symbol.kind == SymbolKind.Alias",
        "declaration_id.value == symbol.id.value",
        "not unknown_type_alias_index_is_inactive(index, file, table)",
        "return true if not alias_found")):
    raise SystemExit("type registration must exclude proven-inactive aliases and preserve unresolved candidates")
if not all(fragment in unresolved_type for fragment in (
        "name.len == 1",
        "is_primitive_type(name)",
        "unknown_type_is_registered(name, file, table)")):
    raise SystemExit("unknown-type resolution must preserve the shared classifier rules while using filtered aliases")
if not all(fragment in alias_cycles for fragment in (
        "continue if not root_activity.known or not root_activity.active",
        "if not candidate_activity.known:",
        "uncertain <- true",
        "matches == 1 and not uncertain")) or not all(fragment in cyclic_lookup for fragment in (
        "if not activity.known:",
        "uncertain <- true",
        "uncertain or matches != 1")):
    raise SystemExit("alias cycle detection must require unique, proven-active paths and suppress unresolved candidates")
if "unknown_type_is_unresolved(type_name, file, table)" not in type_annotation:
    raise SystemExit("bare annotations must use branch-aware type registration")
if "unknown_type_is_registered(name, file, table)" not in alias_target or "unknown_type_is_registered(head, file, table)" not in protocol_state:
    raise SystemExit("alias targets and protocol-state heads must use branch-aware type registration")
if not all(fragment in interned_elements for fragment in (
        "unknown_type_is_unresolved(element_name, file, table)",
        "is_protocol_state_argument(type_id, element_position, element_name, file, table)")):
    raise SystemExit("interned element checks must use the filtered type registry")
if not all(fragment in alias_walk for fragment in (
        "file: Ast::File&",
        "continue if unknown_type_static_scope_is_inactive(file, scoped_line, current_module, table)",
        "nested_module: sview @source = module_name",
        "nested_module, alias_cycles, file, table")):
    raise SystemExit("alias-target checking must carry file/module context and skip inactive scoped declarations")
if not all(fragment in body_walk for fragment in (
        "file: Ast::File&",
        'kind == "static" and unknown_type_static_scope_is_inactive(file, line, current_module, table)',
        "alias_cycles, file, table")):
    raise SystemExit("unknown local-type checking must skip only proven-inactive static statement bodies")
if not all(fragment in declaration_walk for fragment in (
        "file: Ast::File&",
        "continue if unknown_type_static_scope_is_inactive(file, scoped_line, current_module, table)",
        "nested_module: sview @source = module_name",
        "nested_module, alias_cycles, file, table")):
    raise SystemExit("unknown declaration-type checking must skip inactive scopes with lexical module context")
if "check_unknown_type_name(loop_view, table)" not in pipeline or "type_alias_cycle_info(file, table)" not in entrypoint or "type_alias_cycle_info(file, table)" not in alias_entrypoint or "file.top_decls, false, \"\", alias_cycles, file, table" not in entrypoint:
    raise SystemExit("unknown-type entrypoint must pass the loop-view file through the static-scope walk")

fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()
if not all(fragment in fixture for fragment in (
        "static if false:",
        "InactiveAliasTarget",
        "InactiveOnlyAlias",
        "def active_use_of_inactive_alias(value: InactiveOnlyAlias)",
        "type PossibleCycleRoot = PossibleCycleBranch",
        "static if PLATFORM_APPLE:",
        "type PossibleCycleBranch = PossibleCycleRoot",
        "def possible_cycle_use(value: PossibleCycleRoot)",
        "NestedInactiveAliasTarget",
        "NestedActiveAliasTarget",
        "SELECT_INACTIVE",
        "InactiveParameterType",
        "InactiveLocalType",
        "static else:",
        "ActiveAliasTarget",
        "ActiveParameterType",
        "ActiveLocalType")) or not all(fragment in smoke for fragment in (
        "unknown_type_in_inactive_static_scopes.elisa",
        "expected_types=(ActiveAliasTarget ActiveParameterType ActiveLocalType InactiveOnlyAlias NestedActiveAliasTarget)",
        "NestedInactiveAliasTarget",
        "Inactive(AliasTarget|ParameterType|LocalType)",
        "PossibleCycleRoot|PossibleCycleBranch")):
    raise SystemExit("unknown-type static-scope regression must preserve active diagnostics and suppress inactive ones")

print('{"source_bound": true, "inactive_declaration_and_statement_scopes": true, "inactive_alias_registration": true, "inactive_alias_cycles": true}')
