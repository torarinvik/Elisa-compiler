"""Bind EWR canonical family resolution and callable visibility to their source contracts."""
from __future__ import annotations

import argparse
from pathlib import Path
import re


parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
parser.parse_args()

ROOT = Path(__file__).resolve().parents[2]
EWR = ROOT / "src/semantic/check_errorset_wrapper_return.elisa"
TRY = ROOT / "src/semantic/check_try_fallible.elisa"
PARSER = ROOT / "src/parser/parser_decl_module.elisa"
FORMATTER = ROOT / "src/driver/emit_fmt_decl.elisa"


def function_source(path: Path, name: str) -> str:
    source = path.read_text()
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name} in {path.relative_to(ROOT)}")
    return match.group(0)


resolver = function_source(TRY, "try_error_family_ref_for_annotation")
if "table: mutable SymbolTable&" not in resolver:
    raise SystemExit("canonical Try family resolution must retain its mutable SymbolTable contract")

# These EWR helpers call the canonical resolver directly or pass its mutable table
# through subset and coverage checks. Keep mutability available along the whole chain.
mutable_table_helpers = (
    "ewr_single_captured_family_row",
    "ewr_callable_family",
    "ewr_arg_family",
    "ewr_family_row_matches_ref",
    "ewr_subset_marker_matches_family",
    "ewr_family_path_metadata_valid",
    "ewr_family_is_restricted",
    "ewr_variant_allowed",
    "ewr_family_row_subset_state",
    "ewr_family_subset_state",
    "ewr_family_covers",
    "ewr_family_covers_destination_union",
    "ewr_destination_covers",
    "ewr_first_uncovered_family",
)
for name in mutable_table_helpers:
    source = function_source(EWR, name)
    if not re.search(r"table:\s*mutable SymbolTable&", source.splitlines()[0]):
        raise SystemExit(f"{name} must accept mutable SymbolTable for canonical family resolution")

captured_family = function_source(EWR, "ewr_single_captured_family_row")
if "candidate_path: mutable sview @source" not in captured_family:
    raise SystemExit("EWR captured family path must be mutable before filling the adjacent path row")

import_scope = function_source(EWR, "ewr_imported_callable_scope")
wildcard_lookup = import_scope.find('binding.name == "__binding_wildcard_import"')
wildcard_return = import_scope.find("return (true, scope_length) if visible")
selective_lookup = import_scope.find("callable_program_selective_import_row(annotations, name, candidate_module)")
if min(wildcard_lookup, wildcard_return, selective_lookup) < 0 or not (
    wildcard_lookup < wildcard_return < selective_lookup
):
    raise SystemExit("EWR callable lookup must prefer the nearest lexical wildcard before program-wide selective aliases")

callable_lookup = function_source(EWR, "ewr_infallible_callable_scope")
if "ewr_imported_callable_scope(annotations, name, current_module, caller_module)" not in callable_lookup:
    raise SystemExit("EWR infallible callable selection must use the Core-compatible import scope resolver")
function_arm = callable_lookup.find("Decl.Func(function_name")
extern_arm = callable_lookup.find("Decl.Extern(extern_name")
function_visibility_guard = callable_lookup.find(
    "candidate_visible <- false if candidate_visible and not ewr_callable_name_visible(annotations, name, current_module, caller_module, line.line, line.offset) and not receiver_rank_active",
    function_arm,
)
extern_visibility_guard = callable_lookup.find(
    "candidate_visible <- false if candidate_visible and not ewr_callable_name_visible(annotations, name, current_module, caller_module, position.line, position.offset) and not receiver_rank_active",
    extern_arm,
)
function_rank_update = callable_lookup.find("if candidate_visible:", function_visibility_guard)
extern_rank_update = callable_lookup.find("if candidate_visible and (receiver_rank_active or", extern_visibility_guard)
if min(function_arm, extern_arm, function_visibility_guard, extern_visibility_guard, function_rank_update, extern_rank_update) < 0 or not (
        function_arm < function_visibility_guard < function_rank_update < extern_arm < extern_visibility_guard < extern_rank_update):
    raise SystemExit("EWR infallible Func and Extern candidates must filter private visibility only outside receiver-ranked calls")

callable_visibility = function_source(EWR, "ewr_callable_name_visible")
if not all(fragment in callable_visibility for fragment in (
        "try_error_alias_module_visible(annotations, candidate_module, caller_module)",
        'annotation.name != name or annotation.module != candidate_module',
        '(annotation.owner != "__section_private" and annotation.owner != "__section_public")',
        "annotation.offset == declaration_offset",
        "annotation.line == declaration_line",
        'annotation.owner == "__section_private"',
        'annotation.owner == "__section_public"',
        "legacy_private_marker")):
    raise SystemExit("EWR callable visibility must combine private module paths with declaration-specific section markers")
private_position = function_source(PARSER, "private_member_declaration_position")
section_marker = function_source(PARSER, "record_section_member")
if "Ast::pos_of_token(token)" not in private_position or not all(fragment in section_marker for fragment in (
        '"__section_private" if visibility_name == "private" else "__section_public"',
        "line: member_position.line",
        "offset: member_position.offset",
        "module: owning_module")):
    raise SystemExit("Parser visibility markers must retain each member declaration's source identity")
format_visibility = function_source(FORMATTER, "fmt_section_visibility_of")
if not all(fragment in format_visibility for fragment in (
        "declaration_position: Ast::Pos = Ast::decl_pos(declaration)",
        "annotation.offset == declaration_position.offset",
        "annotation.line == declaration_position.line")):
    raise SystemExit("Formatter visibility lookup must distinguish same-named declarations by exact source position")
visibility_smoke = (ROOT / "test/parity/visibility_section_fmt_smoke.sh").read_text()
if not all(fragment in visibility_smoke for fragment in (
        "def dispatch(value: bool)",
        "def dispatch(value: i64)",
        "Pack::dispatch(true)",
        "Pack::dispatch(1)",
        "grep -c 'is private to module'")):
    raise SystemExit("Formatter regression coverage must round-trip mixed-visibility overloads without hiding the public sibling")
if not all(fragment in callable_lookup for fragment in (
        "ewr_callable_name_visible(annotations, name, current_module, caller_module, line.line, line.offset)",
        "ewr_callable_name_visible(annotations, name, current_module, caller_module, position.line, position.offset)")):
    raise SystemExit("EWR infallible callable candidates must filter private names before shadowing")

local_rank = function_source(EWR, "ewr_local_scope_rank")
wildcard_rank = function_source(EWR, "ewr_wildcard_scope_rank")
if "caller_module.len + caller_module.len + 2.usize() + module.len" not in local_rank:
    raise SystemExit("EWR local bindings must outrank every wildcard visible in the caller module")
if "caller_module.len - module.len + 1.usize()" not in wildcard_rank:
    raise SystemExit("EWR wildcard bindings must preserve Core's inherited-before-local using order")
if "ewr_wildcard_scope_rank(binding.module, caller_module)" not in function_source(EWR, "ewr_imported_callable_scope"):
    raise SystemExit("EWR wildcard ranking must be relative to the caller's lexical chain")

binding_scope = function_source(EWR, "ewr_callable_binding_in_scope")
if not all(fragment in binding_scope for fragment in (
        "Decl.Func(function_name",
        "Decl.Extern(extern_name",
        "ewr_imported_callable_scope(annotations, name, current_module, caller_module)",
        "ewr_callable_binding_consider(binding, candidate_scope_length)",
        "not ewr_callable_name_visible(annotations, name, current_module, caller_module, position.line, position.offset)")):
    raise SystemExit("EWR ordinary binding scan must preserve Core's visible Func/Extern name precedence")

inaccessible_binding_scope = function_source(EWR, "ewr_inaccessible_callable_binding_in_scope")
if not all(fragment in inaccessible_binding_scope for fragment in (
        "Decl.Func(function_name",
        "Decl.Extern(extern_name",
        "candidate_visible and not candidate_accessible",
        "candidate_arity_viable",
        "candidate_match.viable",
        "ewr_callable_binding_consider_ranked(binding, candidate_scope_length, candidate_match.specificity, candidate_match.known)")):
    raise SystemExit("EWR must retain only viable inaccessible callable primaries as ranked gate-off barriers")
inaccessible_func_arm = inaccessible_binding_scope.find("Decl.Func(function_name")
inaccessible_extern_arm = inaccessible_binding_scope.find("Decl.Extern(extern_name")
inaccessible_func_guard = inaccessible_binding_scope.find("candidate_accessible: bool =", inaccessible_func_arm)
inaccessible_func_rank = inaccessible_binding_scope.find("ewr_callable_binding_consider_ranked(", inaccessible_func_guard)
inaccessible_extern_guard = inaccessible_binding_scope.find("candidate_accessible: bool =", inaccessible_extern_arm)
inaccessible_extern_rank = inaccessible_binding_scope.find("ewr_callable_binding_consider_ranked(", inaccessible_extern_guard)
if min(inaccessible_func_arm, inaccessible_extern_arm, inaccessible_func_guard, inaccessible_func_rank, inaccessible_extern_guard, inaccessible_extern_rank) < 0 or not (
        inaccessible_func_arm < inaccessible_func_guard < inaccessible_func_rank < inaccessible_extern_arm < inaccessible_extern_guard < inaccessible_extern_rank):
    raise SystemExit("EWR inaccessible Func and Extern candidates must check visibility before updating private-binding ranks")

ordinary_binding = function_source(EWR, "ewr_callable_family")
if not all(fragment in ordinary_binding for fragment in (
        "ewr_first_visible_callable_binding(all_declarations, name, qualifier, caller_module, annotations, table)",
        "selected_scope_length != name_binding.scope_length",
        'if not receiver_rank_active and call_arity_known and selected.family != "":',
        "ewr_first_inaccessible_callable_binding(all_declarations, name, qualifier, caller_module, call_arity_known, call_arity, call_arguments",
        "inaccessible_binding.scope_length > selected_scope_length",
        "inaccessible_binding.specificity >= selected_specificity",
        "parameter_name_shadow or local_name_shadow")):
    raise SystemExit("EWR must preserve same-scope overloads, decline lower-scope families, and respect viable private primaries")
concrete_expression = function_source(EWR, "ewr_concrete_family_of_expression")
if not all(fragment in concrete_expression for fragment in (
        'Expr.Ident(name, line):',
        'ewr_callable_concrete_family(name, "", false, 0.usize(), [], []',
        'Expr.Call(callee, arguments, argument_names, call_line):',
        'ewr_callable_concrete_family(callable.name, callable.qualifier, true, arguments.count')):
    raise SystemExit("EWR must distinguish function-value name lookup from a direct call before applying arity-ranked privacy barriers")

wildcard_ambiguity = function_source(EWR, "ewr_wildcard_callable_name_is_ambiguous")
if not all(fragment in wildcard_ambiguity for fragment in (
        "ewr_first_visible_callable_binding(declarations, name, \"\", caller_module, annotations, table)",
        "lexical_binding.scope_length > caller_module.len + 1.usize()",
        'binding.name != "__binding_wildcard_import"',
        "ewr_callable_declared_in_module(declarations, name, binding.owner",
        "any target in targets where target == binding.owner",
        "targets.count >= 2.usize()")) or not all(fragment in ordinary_binding for fragment in (
        "not receiver_rank_gate and ewr_wildcard_callable_name_is_ambiguous(all_declarations, name, caller_module, annotations, table)",
        "return ewr_empty_family_ref()")):
    raise SystemExit("EWR must fail closed for multiple distinct wildcard targets after lexical lookup")

# Core applies receiver specificity only when a visible qualified-name overload set
# activates the free-call rewrite. Keep EWR's rank switch conditional on that gate.
rank_gate = function_source(EWR, "ewr_receiver_rank_gate")
if not all(fragment in rank_gate for fragment in (
        'qualifier != ""',
        "call_arity_known",
        "call_arguments.count == 0.usize()",
        'argument_name in call_argument_names where argument_name != ""',
        "ewr_visible_name_has_overload_set(declarations, name, caller_module, annotations, table)")):
    raise SystemExit("EWR receiver ranking must require Core's bare, positional, known-arity overload gate")

visible_overload_set = function_source(EWR, "ewr_visible_name_has_overload_set")
visible_overload_scope = function_source(EWR, "ewr_visible_callable_overload_set_in_scope")
module_callable_count = function_source(EWR, "ewr_callable_count_in_module")
if "ewr_visible_callable_overload_set_in_scope(declarations, name, \"\", caller_module, annotations, table)" not in visible_overload_set:
    raise SystemExit("EWR overload gate must begin from the root scope and inspect qualified namespaces separately")
if not all(fragment in module_callable_count for fragment in (
        "Decl.Func(function_name",
        "Decl.Extern(extern_name",
        "count <- count + 1.usize() if callable and extern_name == name",
        "ewr_callable_count_in_module(scoped_body, name)")) or "Decl.Module" in module_callable_count:
    raise SystemExit("EWR must count overload registrations within one module and aggregate only same-module scopes")
if not all(fragment in visible_overload_scope for fragment in (
        "candidate_is_local or imported_scope.visible",
        "ewr_callable_count_in_module(declarations, name) >= 2.usize()",
        "ewr_visible_callable_overload_set_in_scope(module_body, name, nested_module, caller_module, annotations, table)")):
    raise SystemExit("EWR overload gate must require two registrations under one visible qualified name")

fallible_selection = function_source(EWR, "ewr_callable_family")
if not all(fragment in fallible_selection for fragment in (
        "ewr_receiver_rank_gate(all_declarations, name, qualifier, caller_module",
        "return ewr_empty_family_ref() if not receiver_type.known",
        "ewr_callable_name_visible(annotations, name, candidate_module, caller_module, annotation.line, annotation.offset)",
        "if receiver_rank_active:",
        "elif not selected_scope_known or candidate_scope_length > selected_scope_length")):
    raise SystemExit("EWR fallible lookup must use specificity only under the receiver gate and keep scope ordering outside it")
inaccessible_candidate_rank = (
    "candidate_in_rank_set: bool = candidate_visible",
    "candidate_accessible: bool = ewr_callable_name_visible(annotations, name, candidate_module, caller_module, annotation.line, annotation.offset) if candidate_in_rank_set else false",
    "inaccessible_candidate: bool = candidate_in_rank_set and not candidate_accessible",
    "if receiver_rank_active and inaccessible_candidate and candidate_type_viable:",
    "inaccessible_rank_unknown <- true",
    "inaccessible_specificity >= selected_specificity",
)
if not all(fragment in fallible_selection for fragment in inaccessible_candidate_rank):
    raise SystemExit("EWR must fail closed when an inaccessible viable candidate can win or tie Core's receiver rank")
if "return ewr_empty_family_ref() if receiver_rank_active and inaccessible_rank_unknown" not in fallible_selection:
    raise SystemExit("EWR must decline family inference for an inaccessible receiver candidate with unknown rank")
fallible_specificity_rank = fallible_selection.find("candidate_match.specificity > selected_specificity")
fallible_scope_rank = fallible_selection.find("candidate_scope_length > selected_scope_length")
if fallible_specificity_rank < 0 or fallible_scope_rank < 0 or fallible_scope_rank < fallible_specificity_rank:
    raise SystemExit("EWR fallible receiver specificity branch must precede its lexical-scope fallback")
fallible_equal_rank = "elif candidate_match.specificity == selected_specificity:"
fallible_family_tie = "ambiguous <- true if not ewr_family_refs_match(selected, candidate)"
if fallible_equal_rank not in fallible_selection or fallible_family_tie not in fallible_selection:
    raise SystemExit("EWR must detect distinct ErrorSet families among equal-specificity callable candidates")

infallible_specificity_rank = callable_lookup.find("receiver_rank_active and argument_match.specificity > specificity")
infallible_scope_rank = callable_lookup.find("candidate_scope_length > scope_length")
if infallible_specificity_rank < 0 or infallible_scope_rank < 0 or infallible_scope_rank < infallible_specificity_rank:
    raise SystemExit("EWR infallible receiver specificity branch must precede its lexical-scope fallback")
if "not receiver_rank_active and (candidate_scope_length > scope_length" not in callable_lookup:
    raise SystemExit("EWR infallible selection must preserve lexical scope precedence when Core's overload gate is off")

infallible_shadow = function_source(EWR, "ewr_infallible_callable_shadows")
shadow_specificity_rank = infallible_shadow.find("return specificity >= selected_specificity")
shadow_scope_rank = infallible_shadow.find("return true if scope_length > selected_scope_length")
if shadow_specificity_rank < 0 or shadow_scope_rank < 0 or "if receiver_rank_active:" not in infallible_shadow or shadow_scope_rank < shadow_specificity_rank:
    raise SystemExit("EWR infallible shadow comparison must use receiver specificity only under the Core gate")
shadow_specificity_line = next((line for line in infallible_shadow.splitlines() if "return specificity >= selected_specificity" in line), "")
if "if scope_length == selected_scope_length" in shadow_specificity_line:
    raise SystemExit("EWR active receiver shadow comparison must not scope-gate equal-specificity candidates")
infallible_shadow_call = fallible_selection.find("ewr_infallible_callable_shadows(all_declarations")
known_arity_check = fallible_selection.find("if call_arity_known:", infallible_shadow_call)
later_argument_check = fallible_selection.find("ewr_declaration_later_arguments_compatible", known_arity_check)
if min(infallible_shadow_call, known_arity_check, later_argument_check) < 0 or not (
        infallible_shadow_call < known_arity_check < later_argument_check):
    raise SystemExit("EWR must check known-arity infallible winners before accepting a fallible family")

for fixture_name, smoke_name in (
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
