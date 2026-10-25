"""Bind global Catch alias lookup to its source helper and regression."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PATTERN = ROOT / "src/semantic/check_progress_safety/pattern_reachability.elisa"
CATCH = ROOT / "src/semantic/check_catch_exhaustive.elisa"
FIXTURE = ROOT / "test/repro/catch_global_nested_alias.elisa"
CHAIN_FIXTURE = ROOT / "test/repro/catch_global_alias_head_later.elisa"
SMOKE = ROOT / "test/parity/catch_global_nested_alias_smoke.sh"


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return compact(match.group(0))


pattern_source = PATTERN.read_text()
catch_source = CATCH.read_text()
pattern_lookup = function_source(pattern_source, "progress_catch_module_path_matches_scoped")
catch_lookup = function_source(catch_source, "catch_module_alias_target")
catch_context_order = function_source(catch_source, "catch_module_alias_order_with_branch_context")
catch_cutoff = function_source(catch_source, "catch_module_alias_row_is_before")
family_module_lookup = function_source(pattern_source, "progress_catch_explicit_family_module")
fixture = FIXTURE.read_text()
chain_fixture = CHAIN_FIXTURE.read_text()
smoke = SMOKE.read_text()

if "named_type_owner_is_lexical(alias.module,lexical_scope)" in pattern_lookup or "named_type_owner_is_lexical(possible_alias.module,lexical_scope)" in pattern_lookup:
    raise SystemExit("Stage0 module aliases are global; Catch path lookup must not discard aliases from other modules")
if not all(fragment in pattern_lookup for fragment in (
    "progress_catch_module_alias_row_is_before(alias,lexical_scope,before_offset,table)",
    "progress_catch_module_alias_row_is_before(possible_alias,lexical_scope,before_offset,table)",
    "semantic_possible_import_alias_precedes(alias,selected_alias,table)",
    "semantic_possible_import_alias_precedes(possible_alias,selected_alias,table)",
    "semantic_possible_import_alias_precedes(other,alias,table)",
    "winner_order:(known:bool,precedes:bool)",
    "notwinner_order.knownorwinner_order.precedes",
    "continueifalias_order.knownandnotalias_order.before",
    "continueifpossible_order.knownandnotpossible_order.before",
    "target_count!=1.usize()",
    "progress_catch_module_path_matches_scoped(alias_target,alias_suffixes,module,table,alias_scope,alias_selected_offset,depth+1.u32())",
)) or "semantic_import_scope_visible(alias.module,lexical_scope)" in pattern_lookup:
    raise SystemExit("Catch progress-family aliases must share global registration order and exact target pairing")
registration_cutoff = function_source(pattern_source, "progress_catch_module_alias_row_is_before")
if "semantic_possible_import_alias_precedes_position(candidate,declaration_scope,declaration_offset,table)" not in registration_cutoff or \
        "4294967295" not in family_module_lookup or "function_module,4294967295,0" not in family_module_lookup:
    raise SystemExit("Catch alias-target cutoffs must follow registration order rather than raw source offsets")
if "catch_module_is_ancestor(alias.module,lexical_module)" in catch_lookup or not all(fragment in catch_context_order for fragment in (
    "catch_module_alias_branch_stack(annotations,candidate_name,candidate.module,candidate.line,candidate.offset,candidate_is_branch)",
    "candidate_stack.rows.count<selected_stack.rows.count",
    "catch_module_alias_branch_stack_prefix(candidate_stack.rows,selected_stack.rows)",
    "return(false,false)",
)) or not all(fragment in catch_cutoff for fragment in (
    "catch_module_alias_order_with_branch_context(annotations,candidate,declaration.owner,declaration.module,declaration.line,declaration.offset,declaration_is_branch)",
    "declaration_offset==4294967295",
)) or not all(fragment in catch_lookup for fragment in (
    "catch_module_alias_row_is_before(annotations,alias,lexical_module,declaration_line,declaration_offset)",
    "catch_module_alias_order_with_branch_context(annotations,alias,selected_name,selected_scope,selected_line,selected_offset,selected_is_branch)",
    "alias_order_unknown<-trueifnotorder.knownororder.precedes",
    "target_count!=1.usize()",
)):
    raise SystemExit("Catch family alias lookup must use the same global conflict and same-scope alias policy")
if not all(fragment in fixture for fragment in (
    "module AliasHome:",
    "using Provider as Shared",
    "error[Shared::Fault]",
    "catch Shared::load()",
    "catch aliased_family_load()",
)) or not all(fragment in smoke for fragment in (
    "catch_global_nested_alias.elisa",
    "grep -q '^D 2$'",
    "missing_count\" == 2",
)):
    raise SystemExit("global nested-alias Catch regression must cover both call and declared-family paths")
if not all(fragment in chain_fixture for fragment in (
    "module AliasInstaller:",
    "module AliasUser:",
    "using First::Nested as Second",
    "using NestedProvider as First",
    "error[Second::Fault]",
    "catch Second::load()",
    "catch aliased_family_load()",
)) or chain_fixture.index("using First::Nested as Second") > chain_fixture.index("using NestedProvider as First") or \
        "catch_global_alias_head_later.elisa" not in smoke or "chain_missing_count\" == 2" not in smoke:
    raise SystemExit("Catch regression must cover a later-text parent alias used through a nested alias chain")

print("global nested-alias Catch source binding passed")
