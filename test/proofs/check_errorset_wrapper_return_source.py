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
        "candidate_arity_viable: bool = true",
        "ewr_callable_binding_consider_ranked(binding, candidate_scope_length, 0.usize(), false)")):
    raise SystemExit("EWR must retain inaccessible direct-name primaries as barriers without applying the receiver-rank arity gate")
if "ewr_function_arguments_match" in inaccessible_binding_scope:
    raise SystemExit("EWR inaccessible direct-name barriers must not be filtered or ranked by receiver argument types")
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
        "inaccessible_may_win <- true if inaccessible_binding.scope_length == selected_scope_length and (not inaccessible_binding.match_known or not selected_match_known)",
        "parameter_name_shadow or local_name_shadow")):
    raise SystemExit("EWR must preserve same-scope overloads, decline lower-scope families, and respect viable private primaries")
if "if call_arity_known and receiver_rank_active else (true, true)" not in ordinary_binding:
    raise SystemExit("EWR declaration arity must be a candidate filter only under Core's receiver overload gate")
concrete_expression = function_source(EWR, "ewr_concrete_family_of_expression")
if not all(fragment in concrete_expression for fragment in (
        'Expr.Ident(name, line):',
        'ewr_callable_concrete_family(name, "", false, 0.usize(), [], []',
        'Expr.Call(callee, arguments, argument_names, call_line):',
        'ewr_call_has_argument_forward(annotations, call_line.line, call_line.offset)',
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

# Core applies receiver specificity to positional calls (including qualified names)
# when a visible overload set activates the free-call rewrite. Keep EWR conditional
# on the same call-shape and visibility gate.
rank_gate = function_source(EWR, "ewr_receiver_rank_gate")
if (not all(fragment in rank_gate for fragment in (
        "call_arity_known",
        "call_arguments.count == 0.usize()",
        'has_named_argument: bool = any argument_name in call_argument_names where argument_name != ""',
        "or has_named_argument",
        "has_argument_forward",
        "ewr_visible_name_has_overload_set(declarations, name, qualifier, caller_module, annotations, table)"))
        or 'qualifier != ""' in rank_gate):
    raise SystemExit("EWR receiver ranking must mirror Core's positional, known-arity overload gate for qualified and bare names")

# Core's UFCS rank prefilter retains every defaulted or variadic signature, then
# validates argument ordering/default filling against the chosen winner. Keep that
# coarse gate separate from final call resolution so invalid winners block fallback.
function_arity = function_source(EWR, "ewr_function_accepts_arity")
if not all(fragment in function_arity for fragment in (
        "any parameter in parameters where parameter.has_default",
        'any decorator in decorators where decorator.name == "c_variadic"',
        "return has_variadic or has_default or argument_count == parameters.count")):
    raise SystemExit("EWR Func receiver eligibility must mirror Core's coarse defaulted/variadic arity gate")
declaration_arity = function_source(EWR, "ewr_declaration_accepts_arity")
if "accepts: bool = variadic or argument_count == arity.usize()" not in declaration_arity:
    raise SystemExit("EWR Extern receiver eligibility must retain every variadic signature before final call validation")
if "if call_arity_known and receiver_rank_active else true" not in function_source(EWR, "ewr_infallible_callable_scope"):
    raise SystemExit("EWR infallible arity filtering must run only when Core activates receiver overload ranking")
argument_match = function_source(EWR, "ewr_function_arguments_match")
overflow_branch = argument_match.find("# Coarse arity admission runs before this receiver match.")
if overflow_branch < 0 or "continue" not in argument_match[overflow_branch:overflow_branch + 600]:
    raise SystemExit("EWR receiver matching must keep positional overflow candidates already admitted by Core's coarse gate")
if "if slot == 0.usize():" not in argument_match or "if slot > 0.usize():" in argument_match:
    raise SystemExit("EWR overload ranking must use only argument zero; later type diagnostics cannot replace Core's selected return family")

forward_marker = function_source(EWR, "ewr_call_has_argument_forward")
if not all(fragment in forward_marker for fragment in (
        'row.owner == "__arg_forward"',
        'row.name == "__arg_forward"',
        "row.line == call_line",
        "row.offset == call_offset")):
    raise SystemExit("EWR must bind argument forwarding to the exact call before applying Core's named/forwarded argument rules")
function_resolution = function_source(EWR, "ewr_function_call_arguments_resolvable")
if not all(fragment in function_resolution for fragment in (
        "has_variadic and (has_named or has_argument_forward)",
        "arguments.count > parameters.count",
        "parameters[parameter_index].has_default",
        "caller_parameter.name == parameter_name",
        "local_name == parameter_name")):
    raise SystemExit("EWR final Func resolution must distinguish positional overflow, missing required args, defaults, and supported forwarding")
unknown_named_guard = function_resolution.find("return false if parameter_index < 0")
parameter_slot_cast = function_resolution.find("slot: usize = parameter_index.usize()")
if unknown_named_guard < 0 or parameter_slot_cast < 0 or unknown_named_guard > parameter_slot_cast:
    raise SystemExit("EWR must reject unknown named arguments before converting the parameter index to usize")
extern_resolution = function_source(EWR, "ewr_extern_call_arguments_resolvable")
if not all(fragment in extern_resolution for fragment in (
        "has_argument_forward",
        "argument_name != \"\"",
        "arguments.count > arity.usize()",
        "arguments.count == arity.usize()")):
    raise SystemExit("EWR final Extern resolution must keep positional overflow while rejecting unsupported named/forwarded calls")
infallible_scope = function_source(EWR, "ewr_infallible_callable_scope")
if not all(fragment in infallible_scope for fragment in (
        "if call_arity_known and not receiver_rank_active else true",
        "ewr_function_call_arguments_resolvable(parameters, decorators, call_arguments, call_argument_names, has_argument_forward",
        "ewr_extern_call_arguments_resolvable(arity, call_arguments, call_argument_names, has_argument_forward",
        "ewr_function_arguments_match(parameters, call_arguments, call_argument_names, line.line, line.offset, current_module, annotations, caller_parameters, caller_local_names) if call_arity_known and receiver_rank_active else (false, true, 0.usize())",
        "candidate_type_viable: bool = argument_match.viable if receiver_rank_active else true",
        "receiver_rank_active and argument_match.specificity > specificity",
        "not receiver_rank_active and (candidate_scope_length > scope_length")):
    raise SystemExit("EWR rank-off infallible candidates must resolve call shape without using receiver type viability or specificity")
declaration_resolution = function_source(EWR, "ewr_declaration_call_arguments_resolvable")
if not all(fragment in declaration_resolution for fragment in (
        "Decl.Func(_, parameters",
        "ewr_function_call_arguments_resolvable(parameters, decorators",
        "Decl.Extern(_, _, arity",
        "ewr_extern_call_arguments_resolvable(arity",
        "return nested if nested.found")):
    raise SystemExit("EWR final resolution must identify the selected declaration before deciding whether its ErrorSet is usable")

visible_overload_set = function_source(EWR, "ewr_visible_name_has_overload_set")
visible_overload_scope = function_source(EWR, "ewr_visible_callable_overload_set_in_scope")
module_callable_count = function_source(EWR, "ewr_callable_count_in_module")
if "ewr_visible_callable_overload_set_in_scope(declarations, name, qualifier, \"\", caller_module, annotations, table)" not in visible_overload_set:
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
        "ewr_visible_callable_overload_set_in_scope(module_body, name, qualifier, nested_module, caller_module, annotations, table)")):
    raise SystemExit("EWR overload gate must require two registrations under one visible qualified name")

fallible_selection = function_source(EWR, "ewr_callable_family")
if not all(fragment in fallible_selection for fragment in (
        "ewr_receiver_rank_gate(all_declarations, name, qualifier, caller_module",
        "ewr_declaration_call_match(all_declarations, annotation.line, annotation.offset, candidate_module, call_arguments, call_argument_names, extern_params, annotations, caller_parameters, caller_local_names) if call_arity_known and receiver_rank_active else (false, true, 0.usize())",
        "candidate_type_viable: bool = candidate_match.viable if receiver_rank_active else true",
        "call_argument_names, has_argument_forward, annotations, table)",
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
call_resolution_position = fallible_selection.find("ewr_declaration_call_arguments_resolvable")
selected_return_position = fallible_selection.find("return selected", call_resolution_position)
if call_resolution_position < 0 or selected_return_position < 0 or not call_resolution_position < selected_return_position or "ewr_declaration_later_arguments_compatible" in fallible_selection:
    raise SystemExit("EWR must suppress a selected family only when Core's argument resolver fails, not on later type diagnostics")
fallible_specificity_rank = fallible_selection.find("candidate_match.specificity > selected_specificity")
fallible_scope_rank = fallible_selection.find("candidate_scope_length > selected_scope_length")
if fallible_specificity_rank < 0 or fallible_scope_rank < 0 or fallible_scope_rank < fallible_specificity_rank:
    raise SystemExit("EWR fallible receiver specificity branch must precede its lexical-scope fallback")
fallible_equal_rank = "elif candidate_match.specificity == selected_specificity:"
fallible_family_tie = "ambiguous <- true if not ewr_family_refs_match(selected, candidate)"
if fallible_equal_rank not in fallible_selection or fallible_family_tie not in fallible_selection:
    raise SystemExit("EWR must detect distinct ErrorSet families among equal-specificity callable candidates")
rank_off_same_scope = fallible_selection.find("# With the receiver-rank rewrite disabled, same-scope")
rank_off_branch_end = fallible_selection.find("elif receiver_rank_active:", rank_off_same_scope)
rank_off_branch = fallible_selection[rank_off_same_scope:rank_off_branch_end] if rank_off_same_scope >= 0 and rank_off_branch_end >= 0 else ""
if not rank_off_branch or "candidate_match.specificity > selected_specificity" in rank_off_branch or "ambiguous <- true if not ewr_family_refs_match(selected, candidate)" not in rank_off_branch:
    raise SystemExit("EWR rank-off same-scope fallible declarations must not be selected by receiver specificity")

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
shadow_rank_off_start = infallible_shadow.find("if unknown_found:")
shadow_rank_off = infallible_shadow[shadow_rank_off_start:] if shadow_rank_off_start >= 0 else ""
if (shadow_rank_off_start < 0 or "return true if scope_length == selected_scope_length and is_local == selected_is_local" not in shadow_rank_off
        or "specificity >= selected_specificity" in shadow_rank_off):
    raise SystemExit("EWR rank-off infallible shadowing must follow lexical scope and never receiver specificity")
infallible_shadow_call = fallible_selection.find("ewr_infallible_callable_shadows(all_declarations")
known_arity_check = fallible_selection.find("if call_arity_known:", infallible_shadow_call)
call_resolution_check = fallible_selection.find("ewr_declaration_call_arguments_resolvable", known_arity_check)
if min(infallible_shadow_call, known_arity_check, call_resolution_check) < 0 or not (
        infallible_shadow_call < known_arity_check < call_resolution_check):
    raise SystemExit("EWR must check known-arity infallible winners before accepting a fallible family")

for fixture_name, smoke_name in (
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
static_import_filter = function_source(EWR, "ewr_static_import_annotations")
static_import_selection = function_source(EWR, "ewr_static_import_annotation_selection")
static_branch_selection = function_source(EWR, "ewr_static_import_branch_selection")
static_const_value = function_source(EWR, "ewr_static_if_named_constant_value")
static_condition_value = function_source(EWR, "ewr_static_if_condition_value")
unknown_static_import = function_source(EWR, "ewr_unknown_static_import_affects_call")
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
        "return Maybe::wrap(Maybe::origin())")):
    raise SystemExit("EWR static-alias fixture must contrast an inactive same-name alias with the active family-bearing provider")
if not all(fragment in static_import_selection for fragment in (
        "__from_member_static_branch",
        "__binding_wildcard_import_static_branch",
        "__using_alias_static_branch")) or not all(fragment in static_branch_selection for fragment in (
        "marker.owner != \"__static_if_branch\"",
        "marker.identity_id.usize()",
        "branch.known and not branch.selected",
        "return (false, false) if unknown")):
    raise SystemExit("EWR static import filtering must use each generic parser marker and fail closed for unresolved branch ancestry")
if not all(fragment in static_import_filter for fragment in (
        "continue if branch.known and not branch.active",
        "__ewr_unknown_selective_import",
        "__ewr_unknown_wildcard_import",
        "__ewr_unknown_using_alias")) or not all(fragment in unknown_static_import for fragment in (
        "__ewr_unknown_selective_import",
        "__ewr_unknown_wildcard_import",
        "__ewr_unknown_using_alias")):
    raise SystemExit("EWR must remove proven-inactive imports and retain relevant unresolved imports as conservative lookup barriers")
if not all(fragment in static_const_value for fragment in (
        "table.immutable_const_names",
        "table.immutable_const_rows",
        "SemanticPrivateModuleBoundary::within_module",
        "ewr_static_if_condition_value(table.immutable_const_values[selected_row]")) or not all(fragment in static_condition_value for fragment in (
        "Expr.Ident(name, _):",
        "ewr_static_if_named_constant_value(name, current_module, table")):
    raise SystemExit("EWR must fold visible immutable boolean/integer constants and keep unknown conditions conservative")
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
