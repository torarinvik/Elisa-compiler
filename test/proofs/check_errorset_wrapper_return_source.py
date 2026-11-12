"""Bind EWR canonical family resolution and callable visibility to their source contracts."""
from __future__ import annotations

import argparse
from pathlib import Path
from errorset_callable_visibility_cases import check_callable_visibility_fixtures
import re


parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
parser.parse_args()

ROOT = Path(__file__).resolve().parents[2]
EWR = ROOT / "src/semantic/check_errorset_wrapper_return.elisa"
TRY = ROOT / "src/semantic/check_try_fallible.elisa"
PARSER = ROOT / "src/parser/parser_decl_module.elisa"
FORMATTER = ROOT / "src/driver/emit_fmt_decl.elisa"
VISIBILITY_ATOM = ROOT / "test/atoms/errorset_wrapper_return_visibility.elisa"


def function_source(path: Path, name: str) -> str:
    source = path.read_text()
    if path == EWR:
        source += "\n" + "\n".join(
            (ROOT / "src/semantic" / filename).read_text()
            for filename in (
                "check_errorset_wrapper_visibility.elisa",
                "check_errorset_wrapper_callable.elisa",
                "check_errorset_wrapper_coverage.elisa",
            )
        )
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name} in {path.relative_to(ROOT)}")
    return match.group(0)


resolver = function_source(TRY.with_name("check_try_error_family.elisa"), "try_error_family_ref_for_annotation")
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
import_projection = function_source(EWR, "ewr_import_scope_rows")
wrapper_check = function_source(EWR, "check_errorset_wrapper_return")
if not all(fragment in import_projection for fragment in (
        'annotation.name == "__binding_wildcard_import"',
        'annotation.owner == "__from_member"',
        'annotation.owner == "__from_src"',
)) or "table.ewr_import_rows <- ewr_import_scope_rows(lookup_annotations)" not in wrapper_check:
    raise SystemExit("EWR import projection must retain all callable scope rows from active annotations")
if "ewr_imported_callable_scope(table.ewr_import_rows, name, current_module, caller_module)" not in callable_lookup:
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
        "marker_position_known: bool = annotation.pos.end_offset > annotation.pos.offset",
        "annotation.pos.offset == declaration_offset",
        "annotation.pos.line == declaration_line",
        'annotation.owner == "__section_private"',
        'annotation.owner == "__section_public"',
        "legacy_private_marker")):
    raise SystemExit("EWR callable visibility must use explicit marker positions so byte offset zero is exact")
visibility_atom = VISIBILITY_ATOM.read_text()
if not all(fragment in visibility_atom for fragment in (
        'owner: "__section_private", name: "dispatch", line: 0, module: "Api", pos: zero_private_pos',
        'Ast::Pos{line: 0, column: 1, offset: 0, end_line: 0, end_column: 2, end_offset: 1}',
        'owner: "__section_public", name: "dispatch", line: 0, module: "Api", pos: same_line_public_pos',
        'ewr_callable_name_visible(annotations, "dispatch", "Api", "Client", 0, 0)',
        'ewr_callable_name_visible(annotations, "dispatch", "Api", "Api", 0, 0)',
        'ewr_callable_name_visible(annotations, "dispatch", "Api", "Client", 0, 20)',
        'owner: "__section_private", name: "legacy", line: 0, module: "Api"')):
    raise SystemExit("EWR visibility atom must cover a valid private marker at byte zero, a same-line public sibling, and legacy marker fail-closed behavior")
private_position = function_source(PARSER, "private_member_declaration_position")
section_marker = function_source(PARSER, "record_section_member")
if "Ast::pos_of_token(token)" not in private_position or not all(fragment in section_marker for fragment in (
        '"__section_private" if visibility_name == "private" else "__section_public"',
        "line: member_position.line",
        "offset: member_position.offset",
        "module: owning_module",
        "pos: member_position")):
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
        "ewr_imported_callable_scope(table.ewr_import_rows, name, current_module, caller_module)",
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
        'ewr_callable_concrete_family(file, name, "", false, 0.usize(), [], []',
        'Expr.Call(callee, arguments, argument_names, call_line):',
        'ewr_call_has_argument_forward(annotations, call_line.line, call_line.offset)',
        'ewr_callable_concrete_family(file, callable.name, callable.qualifier, true, arguments.count')):
    raise SystemExit("EWR must distinguish function-value name lookup from a direct call before applying arity-ranked privacy barriers")

wildcard_ambiguity = function_source(ROOT / "src/semantic/check_callable_wildcard_ambiguity.elisa", "callable_wildcard_ambiguous")
if not all(fragment in wildcard_ambiguity for fragment in (
        "ewr_module_is_lexical_ancestor(symbol.module_owner, caller_module)",
        'binding.name != "__binding_wildcard_import"',
        "semantic_import_module_path_matches(symbol.module_owner, binding.owner, binding.module)",
        "pma_static_if_function_branch_selection(file, name, symbol, table, 0)",
        "found and symbol.module_owner != selected_owner")) or not all(fragment in ordinary_binding for fragment in (
        "not receiver_rank_gate and callable_wildcard_ambiguous(file, name, caller_module, table)",
        "return ewr_empty_family_ref()")):
    raise SystemExit("EWR must fail closed for multiple distinct active wildcard targets after lexical lookup")

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

# Decl.Module names in the AST are already fully qualified. Recursive EWR walkers
# must keep that canonical path instead of joining it to the current scope again.
canonical_module_walkers = {
    "ewr_raw_callable_in_module": "ewr_raw_callable_in_module(module_body, name, target_module, nested_module, table)",
    "ewr_raw_callable_matches_import_path": "ewr_raw_callable_matches_import_path(module_body, name, base_module, suffix, nested_module, table)",
    "ewr_callable_binding_in_scope": "ewr_callable_binding_in_scope(module_body, name, qualifier, nested_module, caller_module, annotations, table, binding)",
    "ewr_inaccessible_callable_binding_in_scope": "ewr_inaccessible_callable_binding_in_scope(module_body, name, qualifier, nested_module, caller_module",
    "ewr_visible_callable_overload_set_in_scope": "ewr_visible_callable_overload_set_in_scope(module_body, name, qualifier, nested_module, caller_module, annotations, table)",
    "ewr_infallible_callable_scope": "ewr_infallible_callable_scope(module_body, name, qualifier, nested_module, caller_module",
    "ewr_find_function_parameters": "ewr_find_function_parameters(module_body, family, nested_module, annotations, table)",
}
for helper, recursive_call in canonical_module_walkers.items():
    source = function_source(EWR, helper)
    if not all(fragment in source for fragment in (
            "Decl.Module(module_name, module_body",
            "nested_module: sview @source = module_name",
            recursive_call)) or "try_noncall_module_path(current_module, module_name" in source:
        raise SystemExit(f"{helper} must recurse with the parser's canonical module name")

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

check_callable_visibility_fixtures(
    ROOT,
    EWR,
    PARSER,
    binding_scope,
    fallible_selection,
    function_source,
    inaccessible_binding_scope,
    ordinary_binding,
)
