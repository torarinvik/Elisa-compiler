"""Source-bind and admit the try-site enclosing-function predecessor proof."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not args.source_only)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
SOURCE_FILES = [
    ROOT / "src/semantic/check_try_fallible.elisa",
    ROOT / "src/semantic/check_try_fallible/using_aliases.elisa",
    ROOT / "src/semantic/check_try_fallible/callable_rows.elisa",
    ROOT / "src/semantic/check_try_fallible/direct_raises.elisa",
    ROOT / "src/semantic/check_try_fallible/noncall_scan.elisa",
    ROOT / "src/semantic/check_try_fallible/block_sources.elisa",
    ROOT / "src/semantic/check_try_fallible/fallback_casts.elisa",
]
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
PIPELINE_FILES = [
    ROOT / "src/semantic/semantic_api.elisa",
    ROOT / "src/semantic/semantic_api/full_pipeline.elisa",
]
PARSER_ARGUMENT_SOURCE = ROOT / "src/parser/parser_expr_query.elisa"
PARSER_FUNCTION_SOURCE = ROOT / "src/parser/parser_types_function.elisa"
PARSER_DECLARATION_SOURCE = ROOT / "src/parser/parser_decl.elisa"
PARSER_VISIBILITY_SOURCE = ROOT / "src/parser/parser_decl_module.elisa"
PARSER_CATCH_SOURCE = ROOT / "src/parser/parser_stmt_pattern_arms.elisa"
PARSER_NOMINAL_SOURCES = [
    ROOT / "src/parser/parser_types_aggregate.elisa",
    ROOT / "src/parser/parser_export_surface.elisa",
    ROOT / "src/parser/parser_types.elisa",
]
POSITIVE = HERE / "try_enclosing_function_index.elisa"
NEGATIVE = HERE / "try_enclosing_function_index_rejected.elisa"
QUALIFIED_LEAF_FIXTURE = ROOT / "test/repro/try_qualified_module_leaf_collision.elisa"
NESTED_GLOBAL_ALIAS_FIXTURE = ROOT / "test/repro/try_nested_global_using_alias.elisa"
ZERO_OFFSET_ENCLOSING_FIXTURE = ROOT / "test/repro/try_zero_offset_enclosing_function_identity.elisa"
LINE_ZERO_NONERROR_FIXTURE = ROOT / "test/repro/try_nonerror_enclosing_line_zero.elisa"
FIRST_CLASS_AMBIGUOUS_FAMILY_FIXTURE = ROOT / "test/repro/try_first_class_ambiguous_error_family.elisa"
FIRST_CLASS_INACTIVE_DUPLICATE_FAMILY_FIXTURE = ROOT / "test/repro/try_first_class_inactive_duplicate_error_family.elisa"
TRY_SMOKE = ROOT / "test/parity/try_fallible_smoke.sh"
PRIVATE_OVERLOAD_FIXTURE = ROOT / "test/repro/try_overload_private_winner_visibility.elisa"
PRIVATE_OVERLOAD_SMOKE = ROOT / "test/parity/try_overload_private_winner_visibility_smoke.sh"
PROOF_PROCESS_TIMEOUT_SECONDS = 60

POSITION_CONSTANTS = {
    "FALLIBLE_FUNCTION_NO_OFFSET": ("u32", "4294967295"),
    "FALLIBLE_FUNCTION_NO_LINE": ("u32", "0"),
    "FALLIBLE_FUNCTION_FIRST_POSITION": ("usize", "0"),
    "FALLIBLE_FUNCTION_POSITION_STEP": ("usize", "1"),
    "FALLIBLE_FUNCTION_SEARCH_DIVISOR": ("usize", "2"),
}
POSITIVE_NAMES = {
    "try_offsets_are_valid",
    "try_offsets_are_nondecreasing",
    "try_predecessor_is_last",
    "try_linear_predecessor",
    "try_binary_predecessor",
    "last_predecessor_results_are_unique",
    "sorted_binary_predecessor_equals_linear_reference",
    "duplicate_offsets_select_the_last_qualifying_position",
    "zero_offset_is_a_real_position",
    "unsorted_offsets_keep_zero_in_linear_fallback",
    "sorted_binary_predecessor_preserves_parallel_line_mapping",
    "empty_index_reports_no_predecessor",
    "sorted_index_without_a_predecessor_reports_fallback_case",
}
NEGATIVE_NAMES = {
    "false_claim_duplicate_offsets_select_the_first_position",
    "false_claim_duplicate_offsets_keep_the_first_line",
    "false_claim_empty_index_has_a_predecessor",
    "false_claim_no_predecessor_has_a_position",
}


def strip_line_comment(line: str) -> str:
    """Remove # comments while preserving # bytes inside quoted literals."""
    quote = None
    escaped = False
    for index, char in enumerate(line):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == "#":
            return line[:index]
    return line


def normalize_code_line(code: str) -> str:
    output = []
    quote = None
    escaped = False
    pending_space = False
    for char in code.strip():
        if quote is not None:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ('"', "'"):
            if pending_space and output:
                output.append(" ")
            pending_space = False
            quote = char
            output.append(char)
        elif char.isspace():
            pending_space = True
        else:
            if pending_space and output:
                output.append(" ")
            pending_space = False
            output.append(char)
    return "".join(output)


def compact_code(text: str) -> tuple[tuple[int, str], ...]:
    code_lines = []
    for line in text.splitlines():
        uncommented = strip_line_comment(line)
        if uncommented.strip():
            expanded = uncommented.expandtabs(4)
            indent = len(expanded) - len(expanded.lstrip())
            code_lines.append((indent, normalize_code_line(expanded.lstrip())))
    if not code_lines:
        return ()
    base_indent = min(indent for indent, _ in code_lines)
    return tuple((indent - base_indent, code) for indent, code in code_lines)


def compact(text: str) -> str:
    return "\n".join(" " * indent + code for indent, code in compact_code(text))


def compact_inline(text: str) -> str:
    return " ".join(compact(text).split())


def contains_contiguous_block(source: str, block: str) -> bool:
    source_lines = compact_code(source)
    expected_lines = compact_code(block)
    for start in range(len(source_lines) - len(expected_lines) + 1):
        candidate = source_lines[start:start + len(expected_lines)]
        base_indent = candidate[0][0]
        if tuple((indent - base_indent, code) for indent, code in candidate) == expected_lines:
            return True
    return False


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}(?:\[[^\n]*\])?\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*(?:\[[^\n]*\])?\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def constant_definitions(source: str) -> dict[str, tuple[str, str]]:
    return {
        name: (type_name, value)
        for name, type_name, value in re.findall(
            r"(?m)^\s*const ([A-Z][A-Z0-9_]*): ([A-Za-z0-9_]+) = ([^#\n]+)", source
        )
    }


source_text = "\n".join(path.read_text() for path in SOURCE_FILES)
semantic_text = SEMANTIC.read_text()
pipeline_text = "\n".join(path.read_text() for path in PIPELINE_FILES)
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
qualified_leaf_fixture = QUALIFIED_LEAF_FIXTURE.read_text()
nested_global_alias_fixture = NESTED_GLOBAL_ALIAS_FIXTURE.read_text()
zero_offset_enclosing_fixture = ZERO_OFFSET_ENCLOSING_FIXTURE.read_text()
line_zero_nonerror_fixture = LINE_ZERO_NONERROR_FIXTURE.read_text()
first_class_ambiguous_family_fixture = FIRST_CLASS_AMBIGUOUS_FAMILY_FIXTURE.read_text()
first_class_inactive_duplicate_family_fixture = FIRST_CLASS_INACTIVE_DUPLICATE_FAMILY_FIXTURE.read_text()
try_smoke = TRY_SMOKE.read_text()
private_overload_fixture = PRIVATE_OVERLOAD_FIXTURE.read_text()
private_overload_smoke = PRIVATE_OVERLOAD_SMOKE.read_text()

if not __debug__:
    raise SystemExit("run without Python -O")
if not args.source_only and not MANIFEST.is_file():
    raise SystemExit(f"missing proof build manifest: {MANIFEST}")
source_constants = constant_definitions(source_text)
if not source_constants:
    raise SystemExit("could not read production position constants")
for name, definition in POSITION_CONSTANTS.items():
    if source_constants.get(name) != definition:
        raise SystemExit(f"production try-position constant changed: {name}")
proof_constants = constant_definitions(positive_text)
for proof_name, source_name in (
    ("TRY_ENCLOSING_NO_OFFSET", "FALLIBLE_FUNCTION_NO_OFFSET"),
    ("TRY_ENCLOSING_FIRST_POSITION", "FALLIBLE_FUNCTION_FIRST_POSITION"),
    ("TRY_ENCLOSING_POSITION_STEP", "FALLIBLE_FUNCTION_POSITION_STEP"),
    ("TRY_ENCLOSING_BINARY_DIVISOR", "FALLIBLE_FUNCTION_SEARCH_DIVISOR"),
):
    if proof_constants.get(proof_name) != source_constants.get(source_name):
        raise SystemExit(f"proof and production try-position constants differ: {proof_name} / {source_name}")

expected_linear = """
def enclosing_try_function(table: SymbolTable&, try_line: u32, try_offset: u32) -> (line: u32, offset: u32):
    best_line: mutable u32 = FALLIBLE_FUNCTION_NO_LINE
    best_offset_line: mutable u32 = FALLIBLE_FUNCTION_NO_LINE
    best_offset: mutable u32 = 0
    best_offset_found: mutable bool = false
    for symbol in table.symbols |best_line, best_offset_line, best_offset, best_offset_found|:
        if symbol.kind == SymbolKind.Func:
            best_line <- symbol.line if symbol.line <= try_line and symbol.line >= best_line
            if try_offset != FALLIBLE_FUNCTION_NO_OFFSET and symbol.offset != FALLIBLE_FUNCTION_NO_OFFSET and symbol.offset <= try_offset and (not best_offset_found or symbol.offset >= best_offset):
                best_offset <- symbol.offset
                best_offset_line <- symbol.line
                best_offset_found <- true
    return (best_offset_line, best_offset) if best_offset_found
    return (best_line, FALLIBLE_FUNCTION_NO_OFFSET)
"""
expected_builder = """
def fallible_function_position_index_build(index: mutable FallibleFunctionPositionIndex&, table: SymbolTable&) -> void:
    can Memory.Allocate, Abort.Panic:
        positions: mutable darray[FallibleFunctionPosition] = []
        offsets_ordered: mutable bool = true
        saw_previous: mutable bool = false
        previous_offset: mutable u32 = 0
        for symbol in table.symbols |positions, offsets_ordered, saw_previous, previous_offset|:
            if symbol.kind == SymbolKind.Func and symbol.offset != FALLIBLE_FUNCTION_NO_OFFSET:
                offsets_ordered <- false if saw_previous and symbol.offset < previous_offset
                positions <- positions.push(FallibleFunctionPosition{offset: symbol.offset, line: symbol.line})
                previous_offset <- symbol.offset
                saw_previous <- true
        index.positions <- positions
        index.offsets_ordered <- offsets_ordered
        index.ready <- true
"""
expected_indexed = """
def enclosing_try_function_indexed(index: mutable FallibleFunctionPositionIndex&, table: SymbolTable&, try_line: u32, try_offset: u32) -> (line: u32, offset: u32):
    can Memory.Allocate, Abort.Panic:
        if not index.ready:
            fallible_function_position_index_build(index, table)
        if try_offset != FALLIBLE_FUNCTION_NO_OFFSET and index.offsets_ordered:
            low: mutable usize = FALLIBLE_FUNCTION_FIRST_POSITION
            high: mutable usize = index.positions.count
            while low < high |low, high, index, try_offset|:
                middle: usize = low + (high - low) / FALLIBLE_FUNCTION_SEARCH_DIVISOR
                if index.positions[middle].offset <= try_offset:
                    low <- middle + FALLIBLE_FUNCTION_POSITION_STEP
                else:
                    high <- middle
            if low > FALLIBLE_FUNCTION_FIRST_POSITION:
                position: FallibleFunctionPosition = index.positions[low - FALLIBLE_FUNCTION_POSITION_STEP]
                return (position.line, position.offset)
        return enclosing_try_function(table, try_line, try_offset)
"""
for name, expected in (
    ("enclosing_try_function", expected_linear),
    ("fallible_function_position_index_build", expected_builder),
    ("enclosing_try_function_indexed", expected_indexed),
):
    if compact(function_section(source_text, name)) != compact(expected):
        raise SystemExit(f"production {name} changed without updating the source-bound proof")

exact_zero_contracts = {
    "try_enclosing_function_decl_id": (
        "enclosing.offset != FALLIBLE_FUNCTION_NO_OFFSET and symbol.offset != enclosing.offset",
        "matches <- matches + 1.usize()",
    ),
    "try_enclosing_return_occurrence": (
        "function_offset != FALLIBLE_FUNCTION_NO_OFFSET and marker.offset != function_offset",
    ),
    "fallible_function_module_index_add": (
        "annotation.offset != FALLIBLE_FUNCTION_NO_OFFSET",
        "index.by_offset <- index.by_offset.put(annotation.offset.u64(), row)",
        "index.by_line <- index.by_line.put(line_key, CALLABLE_ERROR_ROW_NONE)",
        "index.unknown_offset_by_line",
    ),
    "fallible_fn_module_indexed": (
        "declaration_offset == FALLIBLE_FUNCTION_NO_OFFSET",
        "index.by_offset.get(declaration_offset.u64())",
        "return module_annotations[offset_row.usize()].name if offset_row != CALLABLE_ERROR_ROW_NONE and module_annotations[offset_row.usize()].line == declaration_line",
        "row != CALLABLE_ERROR_ROW_NONE",
    ),
    "fallible_fn_module": (
        "declaration_offset != FALLIBLE_FUNCTION_NO_OFFSET and module_annotation.offset == declaration_offset",
        "fallback_module <- module_annotation.name",
        "return fallback_module if fallback_count == 1.usize()",
    ),
    "fallible_fn_module_known": (
        "module_annotation.offset == declaration_offset",
        "declaration_offset != FALLIBLE_FUNCTION_NO_OFFSET",
        "return fallback_count == 1.usize()",
    ),
    "try_error_set_index_build": (
        "annotation.offset != FALLIBLE_FUNCTION_NO_OFFSET",
        "index.by_offset_heads <- index.by_offset_heads.put(offset_key, row_id)",
        "index.unknown_offset_line_heads",
    ),
    "try_error_set_destinations": (
        "declaration_offset == FALLIBLE_FUNCTION_NO_OFFSET",
        "candidate.offset == declaration_offset",
        "if destinations.count == 0.usize():",
    ),
    "try_error_family_path_for_declaration": (
        "declaration_offset != FALLIBLE_FUNCTION_NO_OFFSET and family_annotation.offset != declaration_offset",
    ),
    "try_error_family_refs_match": (
        "source.declaration_offset != FALLIBLE_FUNCTION_NO_OFFSET and destination.declaration_offset != FALLIBLE_FUNCTION_NO_OFFSET",
        "try_error_family_name_has_unique_module(file, annotations, source.family, expected_module_known, expected_module, table)",
    ),
    "try_error_set_decl_is_static_inactive": (
        'name_row.owner != "__lsp_decl_name" or name_row.name != declaration.name or name_row.line != declaration.line',
        "name_row.pos.offset != declaration.offset",
        "name_row_count != 1.usize()",
        "try_overload_nominal_type_declaration_is_static_inactive(file, annotations, declaration.name, declaration.module, declaration.line, declaration_keyword_offset, table)",
    ),
    "try_error_family_name_has_unique_module": (
        'declaration.owner != "__error_set_decl" or declaration.name != family',
        "try_error_set_decl_is_static_inactive(file, annotations, declaration, table)",
        "declaration.module != selected_module",
        "module_found and (not expected_module_known or selected_module == expected_module)",
    ),
    "try_error_family_subset_status": (
        "family.declaration_offset == FALLIBLE_FUNCTION_NO_OFFSET or family.family_path == \"\"",
    ),
    "try_error_family_has_empty_subset": (
        "family.declaration_offset == FALLIBLE_FUNCTION_NO_OFFSET or family.family_path == \"\"",
    ),
    "callable_function_declaration_visible": (
        "declaration_offset != FALLIBLE_FUNCTION_NO_OFFSET and annotation.offset != FALLIBLE_FUNCTION_NO_OFFSET",
        "annotation.offset == declaration_offset",
        "annotation.offset == FALLIBLE_FUNCTION_NO_OFFSET",
    ),
    "callable_symbol_accepts_arity": (
        "if symbol.offset == declaration_offset:",
        "declaration_offset == FALLIBLE_FUNCTION_NO_OFFSET or symbol.offset == FALLIBLE_FUNCTION_NO_OFFSET",
    ),
    "try_noncall_parameter_error_family": (
        "function_pos.offset != FALLIBLE_FUNCTION_NO_OFFSET and enclosing.offset != FALLIBLE_FUNCTION_NO_OFFSET",
        "function_pos.offset < enclosing.offset",
    ),
    "check_try_propagation_row": (
        "enclosing.offset != FALLIBLE_FUNCTION_NO_OFFSET and family_annotation.offset != FALLIBLE_FUNCTION_NO_OFFSET",
        "family_annotation.offset == enclosing.offset",
        "function_line != 0 or enclosing.offset != FALLIBLE_FUNCTION_NO_OFFSET",
    ),
    "try_parameter_error_family": (
        "parameter_found: mutable bool = false",
        "return (false, \"\") if not parameter_found",
    ),
    "try_noncall_static_effect_candidate_may_raise": (
        "operation_matches != 1.usize() or operation_name == \"\"",
        "operation_offset <- operation_row.offset",
    ),
    "try_fallback_extern_declaration_line": (
        "-> (found: bool, line: u32, offset: u32)",
        "function_count <- function_count + 1.usize()",
        "return (true, declaration_line, declaration_offset) if function_count == 1.usize()",
        "return (false, 0, 0)",
    ),
    "try_fallback_extern_return_info": (
        "declaration: (found: bool, line: u32, offset: u32) = try_fallback_extern_declaration_line(table, name)",
        "return info if not declaration.found",
    ),
}
for name, fragments in exact_zero_contracts.items():
    body = compact_inline(function_section(source_text, name))
    if any(compact_inline(fragment) not in body for fragment in fragments):
        raise SystemExit(f"Try source selector must treat byte offset zero as exact and reserve the sentinel for missing positions: {name}")
if "declaration_line != 0" in compact_inline(function_section(source_text, "try_error_family_refs_match")):
    raise SystemExit("Try family identity must not treat logical line zero as missing provenance")

rows_function = function_section(source_text, "check_try_fallible_rows")
expected_dispatch = """
row_enclosing: mutable (line: u32, offset: u32) = (0, FALLIBLE_FUNCTION_NO_OFFSET)
if try_site_count > 1:
    row_enclosing <- enclosing_try_function_indexed(function_positions, table, annotation.line, annotation.offset)
else:
    row_enclosing <- enclosing_try_function(table, annotation.line, annotation.offset)
row_module: sview = fallible_fn_module_indexed(module_index, module_annotations, row_enclosing.offset, row_enclosing.line)
"""
if not contains_contiguous_block(rows_function, expected_dispatch):
    raise SystemExit("try rows must use indexed enclosing-function lookup only for multiple try sites and feed its result into module scope resolution")
if compact_inline(rows_function).count("enclosing_try_function_indexed(") != 1 or \
        compact_inline(rows_function).count("enclosing_try_function(") != 1:
    raise SystemExit("try rows must retain exactly one indexed and one linear enclosing-function dispatch arm")
propagation_call = "table <- check_try_propagation_row(file, annotation, row_enclosing, row_module, row_qualifier, annotations, try_named_arguments, argument_type_ids, receiver_ref_mutability_known, receiver_ref_mutable, error_set_annotations, error_set_family_paths, error_set_index, propagation_site_count, module_index, module_annotations, error_index, table, row_arity.known, row_arity.value, first_class_error_family, noncall_lambda_error_family, noncall_inside_lambda)"
if compact_inline(propagation_call) not in compact_inline(rows_function):
    raise SystemExit("resolved enclosing function must flow into try-propagation diagnostics")

argument_types = compact_inline(function_section(source_text, "try_call_argument_type_ids"))
if not all(fragment in argument_types for fragment in (
        'marker.owner != "__try_callee_argument_position"',
        "ownership_binding_at_position(table, caller, argument_position)",
        "declared.binding_id.owner.value != binding.binding_id.owner.value",
        "declared.binding_id.serial != binding.binding_id.serial",
        'marker.owner != "__try_callee_argument_direct_call"',
        "ownership_binding_at_position(table, caller, nested_call_position)",
        "callable_try_static_binding_uncertain(annotations, nested_call_name, caller_module, \"\", table)",
        "callable_row_in_scope_indexed(module_index, module_annotations, annotations, nested_call_name, symbol.offset, symbol.line, caller_module, \"\", table)",
        "symbol.return_type_id",
        "call_return_function_offset: mutable u32 = 0",
        "call_return_function_offset <- symbol.offset",
        "type_id_contains_function_generic(call_return_type_id, call_return_function_line, call_return_function_offset, table)",
        "type_id_contains_region(call_return_type_id, table)",
        "call_return_conflict",
        "argument_type_firm or argument_type_ambiguous")):
    raise SystemExit("Try argument types must use exact bindings or one visible unshadowed concrete call result, and fail closed on unresolved imports, generic or region schemes")
imported_argument_fixture = (ROOT / "test/repro/try_overload_imported_argument_type_id.elisa").read_text()
if not all(fragment in imported_argument_fixture for fragment in (
        "module Helpers:",
        "def make_flag() -> bool",
        "module Consumer:",
        "from Helpers import make_flag",
        "def choose(value: bool)",
        "def choose(value: i64)",
        "def caller() -> i64 error[Consumer::IntegerFault]",
        "def caller_correct_family() -> i64 error[Consumer::BoolFault]",
        "return try choose(make_flag())")):
    raise SystemExit("Try imported-call argument coverage must bind receiver overload ranking to one visible imported function's concrete return type")
imported_argument_smoke = (ROOT / "test/parity/try_overload_imported_argument_type_id_smoke.sh").read_text()
if not all(fragment in imported_argument_smoke for fragment in (
        "try_overload_imported_argument_type_id.elisa",
        "expected_rows=$'L24'",
        "cannot propagate BoolFault from a function returning IntegerFault",
        "grep -q '^D 1$'")):
    raise SystemExit("Try imported-call parity smoke must reject the wrong ErrorSet and preserve the correct-family control")
generic_parameter = compact_inline(function_section(source_text, "try_overload_type_is_generic_parameter"))
if not all(fragment in generic_parameter for fragment in (
        'annotation.name == "__generic_param_identity"',
        "annotation.detail_line == declaration_symbol.line",
        "annotation.offset == declaration_symbol.offset",
        "annotation.module == declaration_symbol.module_owner")):
    raise SystemExit("Try overload ranking must identify generic parameters by their exact declaration identity")
type_selection = compact_inline(function_section(source_text, "callable_symbol_type_selected_candidate"))
if not all(fragment in type_selection for fragment in (
        'argument.owner == "__try_callee_named_arg"',
        "actual_receiver_type_id: u32 = argument_type_ids[0]",
        "try_overload_type_is_firm_in_module(file, actual_receiver_type_id, enclosing_module, annotations, table)",
        "callable_name_has_ufcs_overload_set_in_scope(module_index, module_annotations, annotations, name, enclosing_module, callee_qualifier, try_named_arguments, try_offset, table)",
        "callable_row_in_ufcs_candidate_set_indexed(module_index, module_annotations, annotations, name, symbol.offset, symbol.line, enclosing_module, callee_qualifier, table)",
        "continue if not receiver.found and not callable_symbol_has_parameter_rows(table, symbol) and symbol.arity_min == 0 and (symbol.arity_max == 0 or symbol.arity_max == 4294967295)",
        "try_overload_receiver_pattern_matches(file, receiver.type_id, actual_receiver_type_id, symbol.id, enclosing_module, annotations, table, 0)",
        "if actual_receiver_is_ref and not formal_receiver_is_ref and not try_overload_type_is_generic_parameter(receiver.type_id, symbol.id, annotations, table):",
        "return invalid if actual_receiver_base_kind == SemTypeKind.Int or actual_receiver_base_kind == SemTypeKind.Float or actual_receiver_base_kind == SemTypeKind.Bool",
        "continue if receiver.mutable_ref and not receiver_ref_mutable",
        "rank_score: usize = rank.score + 1.usize() if formal_receiver_is_ref and actual_receiver_is_ref and receiver.mutable_ref == receiver_ref_mutable else rank.score",
        "if best_count == 0.usize() or rank_score > best_rank:",
        "elif rank_score == best_rank:",
        "return selected if best_count == 1.usize()")):
    raise SystemExit("Try overload selection must use the known first argument, Core-compatible receiver ranking, and a unique top rank")
if "for actual_type_id in argument_type_ids" in type_selection or "argument_type_ids[parameter_index]" in type_selection:
    raise SystemExit("Later argument types must not affect Core's first-receiver overload selection")
raw_receiver_overload_set = compact_inline(function_section(source_text, "callable_name_has_ufcs_overload_set_candidate"))
ranked_receiver_overload_gate = compact_inline(function_section(source_text, "callable_name_has_ufcs_overload_set_in_scope"))
if not all(fragment in raw_receiver_overload_set for fragment in (
        "callable_row_in_ufcs_candidate_set_indexed",
        "other.kind == SymbolKind.Func and other.name == name and other.module_owner == symbol.module_owner",
        "candidate_count >= 2.usize()")) or not all(fragment in ranked_receiver_overload_gate for fragment in (
        "callable_try_call_forwards_arguments(annotations, try_offset)",
        'argument.owner == "__try_callee_named_arg"',
        "return callable_name_has_ufcs_overload_set_candidate")):
    raise SystemExit("Try must distinguish Core's raw overload set from the call shapes eligible for receiver ranking")
receiver_arity = compact_inline(function_section(source_text, "callable_symbol_core_accepts_receiver_arity"))
if not all(fragment in receiver_arity for fragment in (
        "symbol.arity_max == 4294967295",
        "table.function_param_has_default[row]",
        "return symbol.arity_max == arity")):
    raise SystemExit("Try receiver candidate filtering must mirror Core's variadic, defaulted, and fixed-arity rules")
if "declaration_id.value == symbol.id.value" not in compact_inline(function_section(source_text, "callable_symbol_has_parameter_rows")):
    raise SystemExit("Try overload ranking must distinguish an actual zero-parameter function from incomplete formal metadata")
visible_overloads = compact_inline(function_section(source_text, "callable_name_has_ufcs_overload_set_in_scope"))
visible_overload_candidates = compact_inline(function_section(source_text, "callable_name_has_ufcs_overload_set_candidate"))
if not all(fragment in visible_overloads for fragment in (
        "callable_try_call_forwards_arguments(annotations, try_offset)",
        'argument.owner == "__try_callee_named_arg"',
        "callable_name_has_ufcs_overload_set_candidate(module_index, module_annotations, annotations, name, enclosing_module, callee_qualifier, table)")) or not all(fragment in visible_overload_candidates for fragment in (
        "callable_row_in_ufcs_candidate_set_indexed",
        "other.module_owner == symbol.module_owner",
        "candidate_count >= 2.usize()")):
    raise SystemExit("Try receiver ranking must detect Core overload sets across all visible module candidates")
candidate_set = compact_inline(function_section(source_text, "callable_row_in_ufcs_candidate_set_indexed"))
if not all(fragment in candidate_set for fragment in (
        'if callee_qualifier != "": return false if not try_error_alias_module_visible(annotations, candidate_module, enclosing_module) return callable_qualified_module_matches_candidate(annotations, candidate_module, enclosing_module, callee_qualifier, name, table)',
        "candidate_module == scope_module and callable_named_declaration_in_module",
        "callable_wildcard_imported_row_in_scope(annotations, table, name, candidate_module, scope_module)",
        "return callable_program_selective_import_row(annotations, name, candidate_module)")):
    raise SystemExit("Try receiver ranking must retain both lexical and imported functions in Core's visible candidate set")
candidate_local = candidate_set.find("candidate_module == scope_module and callable_named_declaration_in_module")
candidate_parent_walk = candidate_set.find("scope_module <- try_noncall_module_parent(scope_module)")
candidate_wildcard = candidate_set.find("callable_wildcard_imported_row_in_scope")
candidate_selective = candidate_set.find("return callable_program_selective_import_row(annotations, name, candidate_module)")
if min(candidate_local, candidate_parent_walk, candidate_wildcard, candidate_selective) < 0 or not (
        candidate_local < candidate_parent_walk < candidate_wildcard < candidate_selective):
    raise SystemExit("Try receiver lookup must scan all lexical declarations before wildcard imports and selective aliases")
wildcard_imported_row = compact_inline(function_section(source_text, "callable_wildcard_imported_row_in_scope"))
if 'binding.name == "__binding_wildcard_import" and binding.owner == candidate_module and binding.module == scope_module' not in wildcard_imported_row:
    raise SystemExit("Try wildcard imports must remain tied to their lexical using scope")
ordinary_row = compact_inline(function_section(source_text, "callable_row_in_scope_indexed"))
qualified_module_match = compact_inline(function_section(source_text, "callable_qualified_module_matches_candidate"))
if not all(fragment in qualified_module_match for fragment in (
        "callable_module_path_matches_suffix(symbol.module_owner, scope_module, callee_qualifier)",
        "callable_function_declaration_visible(annotations, name, symbol.module_owner, symbol.line, symbol.offset, enclosing_module)",
        "semantic_possible_import_alias_head_target(alias_head, enclosing_module, before_offset, table)",
        "semantic_possible_import_alias_target_prefix(symbol.module_owner, alias.raw_target, alias.scope, alias.offset, table)",
        "candidate_module == callee_qualifier and callable_named_visible_declaration_in_module(table, annotations, name, candidate_module, enclosing_module)")) or "module_last_segment(candidate_module)" in qualified_module_match:
    raise SystemExit("Try qualified overload ranking must use exact lexical modules, the shared global alias winner, and an exact root path")
if 'return false if not try_error_alias_module_visible(annotations, candidate_module, enclosing_module) return false if not callable_function_declaration_visible(annotations, name, candidate_module, declaration_line, declaration_offset, enclosing_module) return callable_qualified_module_matches_candidate(annotations, candidate_module, enclosing_module, callee_qualifier, name, table)' not in ordinary_row:
    raise SystemExit("Try ordinary qualified lookup must reject private modules and exact private members while sharing the path matcher")
linear_scope = compact_inline(function_section(source_text, "callable_row_in_scope"))
if "callable_qualified_module_matches_candidate(annotations, candidate_module, enclosing_module, callee_qualifier, name, table)" not in linear_scope or "module_last_segment(candidate_module)" in linear_scope:
    raise SystemExit("Try linear family lookup must use the same exact qualified-module matcher")
global_alias_lookup = compact_inline(function_section(source_text, "callable_using_alias_visible_target_global"))
if not all(fragment in global_alias_lookup for fragment in (
        "semantic_possible_import_alias_head_target(alias_name, enclosing_module, 4294967295, table)",
        "return (2.usize(), \"\", \"\") if not alias.known",
        "return (1.usize(), alias.target, alias.scope) if alias.found")):
    raise SystemExit("Try must use the shared analyzer-wide alias winner and keep unresolved alias contenders unknown")
cached_alias_chain = compact_inline(function_section(source_text, "callable_using_alias_target_chain_known"))
if not all(fragment in cached_alias_chain for fragment in (
        "semantic_possible_import_alias_head_target(alias_head, alias_scope, before_offset, table)",
        "return false if not alias.known",
        "return callable_using_alias_target_chain_known(alias.raw_target, alias.scope, alias.offset, table, depth + 1.u32())")):
    raise SystemExit("Try cached aliases must validate target chains at each declaration cutoff")
static_alias_binding = compact_inline(function_section(source_text, "callable_try_static_binding_uncertain"))
if not all(fragment in static_alias_binding for fragment in (
        'unresolved.name == "__using_alias" and callee_qualifier != "" and unresolved.detail_name == alias_head',
        "semantic_possible_import_alias_head_target(alias_head, enclosing_module, 4294967295, table)",
        "continue if selected_alias.known and selected_alias.found return true")) or "try_noncall_module_is_ancestor(unresolved.module, enclosing_module)" in static_alias_binding:
    raise SystemExit("Try static alias uncertainty must follow the analyzer-wide alias winner rather than caller ancestry")
if not all(fragment in qualified_leaf_fixture for fragment in (
        "module OuterB:", "def fail() -> i64 error[F]:", "module OuterA:",
        "def fail() -> i64 error[E]:", "module Caller:", "return try Common::fail()")) or not all(fragment in try_smoke for fragment in (
        "try_qualified_module_leaf_collision.elisa", "cannot propagate E from a function returning F")):
    raise SystemExit("Try smoke must bind the duplicate-leaf fixture where Common resolves only to the caller's OuterA ancestor")
if not all(fragment in nested_global_alias_fixture for fragment in (
        "module AliasHome:", "module Provider:", "using Provider as Shared", "def good() -> i64 error[E]:", "return try Shared::load()")) or not all(fragment in try_smoke for fragment in (
        "try_nested_global_using_alias.elisa", "root call could not resolve a module alias declared in a nested module")):
    raise SystemExit("Try smoke must bind a root call through a module alias declared inside a nested module")
if not zero_offset_enclosing_fixture.startswith("def caller() -> i64 error[E]:\n") or not all(fragment in zero_offset_enclosing_fixture for fragment in (
        "return try load()", "def load() -> i64 error[E]:",
        "#line 1 zero-offset-enclosing.elisa", "def sibling() -> i64 error[F]:")) or not all(fragment in try_smoke for fragment in (
        "try_zero_offset_enclosing_function_identity.elisa", "^D 0$",
        "same-#line sibling displaced the byte-zero caller")):
    raise SystemExit("Try smoke must bind a byte-zero enclosing function against a same-line sibling with a different error family")
if "#line 0 try-line-zero.elisa\ndef caller() -> i64:" not in line_zero_nonerror_fixture or not all(fragment in line_zero_nonerror_fixture for fragment in (
        "def load() -> i64 error[E]:", "return try load()")) or not all(fragment in try_smoke for fragment in (
        "try_nonerror_enclosing_line_zero.elisa", "try without else requires the current function to return an error union")):
    raise SystemExit("Try smoke must retain the #line 0 non-error caller regression")
if not all(fragment in first_class_ambiguous_family_fixture for fragment in (
        "module Provider:", "error Fault:", "module Caller:", "from Caller import Fault",
        "#line 0 try-family-ref-provenance.elisa", "error[Provider::Fault]", "return try value")) or not all(fragment in try_smoke for fragment in (
        "try_first_class_ambiguous_error_family.elisa", "^D 1$",
        "cannot propagate Fault from a function returning Fault")):
    raise SystemExit("Try family provenance must reject a line-zero name-only match when duplicate ErrorSet owners exist")
if not all(fragment in first_class_inactive_duplicate_family_fixture for fragment in (
        "module Provider:", "error Fault:", "static if false:", "module InactiveCaller:",
        "error Fault:", "from Provider import Fault", "#line 0 try-family-inactive-owner.elisa",
        "error[Provider::Fault]", "return try value")) or not all(fragment in try_smoke for fragment in (
        "try_first_class_inactive_duplicate_error_family.elisa", "^D 0$")):
    raise SystemExit("Try family uniqueness must ignore a duplicate ErrorSet only when its static branch is proven inactive")
ordinary_local = ordinary_row.find("if callable_named_visible_declaration_in_module(table, annotations, name, scope_module, enclosing_module): return candidate_module == scope_module")
ordinary_parent_walk = ordinary_row.find("scope_module <- try_noncall_module_parent(scope_module)")
ordinary_wildcard = ordinary_row.find("wildcard: (found: bool, matches: bool) = callable_first_wildcard_imported_row")
ordinary_selective = ordinary_row.find("return callable_program_selective_import_row_visible(annotations, name, candidate_module, enclosing_module)")
if min(ordinary_local, ordinary_parent_walk, ordinary_wildcard, ordinary_selective) < 0 or not (
        ordinary_local < ordinary_parent_walk < ordinary_wildcard < ordinary_selective):
    raise SystemExit("Try ordinary lookup must scan every visible lexical parent before wildcard imports and selective aliases")
visible_lexical_declaration = compact_inline(function_section(source_text, "callable_named_visible_declaration_in_module"))
if not all(fragment in visible_lexical_declaration for fragment in (
        "callable_function_declaration_visible(annotations, name, module, symbol.line, symbol.offset, enclosing_module)",
        "symbol.kind != SymbolKind.Func or symbol.name != name or symbol.module_owner != module")):
    raise SystemExit("Try lexical lookup must skip inaccessible declarations instead of letting them shadow visible imports")
callable_declaration_visibility = compact_inline(function_section(source_text, "callable_function_declaration_visible"))
if not all(fragment in callable_declaration_visibility for fragment in (
        "try_error_alias_module_visible(annotations, candidate_module, lexical_module)",
        'annotation.owner != "__section_private" and annotation.owner != "__section_public"',
        "annotation.offset == declaration_offset",
        "annotation.line == declaration_line",
        "return try_noncall_module_is_ancestor(candidate_module, lexical_module) if exact_private",
        "return true if exact_public",
        "return false if legacy_private_marker")):
    raise SystemExit("Try callable visibility must match private/public markers to the exact declaration and module path")
first_wildcard = compact_inline(function_section(source_text, "callable_first_wildcard_imported_row"))
if not all(fragment in first_wildcard for fragment in (
        'binding.name != "__binding_wildcard_import"',
        "try_noncall_module_is_ancestor(binding.module, enclosing_module)",
        "callable_named_visible_declaration_in_module(table, annotations, name, binding.owner, enclosing_module)",
        "ambiguous_imports <- true if selected_found and selected_target != binding.owner",
        "selected_scope_length: mutable usize = enclosing_module.len + 1.usize()",
        "binding.module.len < selected_scope_length",
        "selected_target <- binding.owner",
        "return (true, false) if ambiguous_imports",
        "return (selected_found, selected_target == candidate_module)")):
    raise SystemExit("Try ordinary wildcard lookup must preserve Core's outer-to-inner order and private visibility")
program_selective_import = compact_inline(function_section(source_text, "callable_program_selective_import_row"))
if not all(fragment in program_selective_import for fragment in (
        'binding.owner != "__from_member" or binding.name != name',
        'source.owner != "__from_src" or source.module != binding.module or source.line != binding.line or source.offset != binding.offset',
        'return candidate_module == source.name if binding.module == ""',
        "return callable_module_path_matches_suffix(candidate_module, binding.module, source.name)")):
    raise SystemExit("Try selective imports must match Core's raw source path relative to the importing namespace")
program_selective_import_visible = compact_inline(function_section(source_text, "callable_program_selective_import_row_visible"))
if not all(fragment in program_selective_import_visible for fragment in (
        "path_matches and callable_named_visible_declaration_in_module(table, annotations, name, candidate_module, enclosing_module)")):
    raise SystemExit("Try ordinary selective imports must reject private target modules and members")
noncall_import_builder = compact_inline(function_section(source_text, "try_noncall_binding_at_site"))
if not all(fragment in noncall_import_builder for fragment in (
        "already_imported_name: mutable bool = false",
        "environment.callable_imported_member_names[index] == import_annotation.name",
        "try_noncall_module_path(import_annotation.module, source_annotation.name, table)",
        "if imported_module != \"\" and not already_imported_name",
        "environment.callable_imported_member_names.push(import_annotation.name)")):
    raise SystemExit("Try non-call cached facts must retain only Core's first selective import for each bare name")
noncall_module_path = compact_inline(function_section(source_text, "try_noncall_module_path"))
if not all(fragment in noncall_module_path for fragment in (
        'return child if parent == ""',
        "already_parent_qualified: mutable bool",
        "child.len > parent.len + 1.usize()",
        "child[parent.len + 1.usize()] == 58",
        "return child if already_parent_qualified")):
    raise SystemExit("Try module path joins must preserve already-qualified declaration children while keeping relative joins")
noncall_assignment_facts = compact_inline(function_section(source_text, "try_noncall_assignment_source_facts"))
if 'return (call_facts.family, call_facts.return_nonfallible and call_facts.family == "") if call_facts.known' not in noncall_assignment_facts:
    raise SystemExit("Try non-call assignment facts must preserve known infallible callable returns")
cached_lookup = compact_inline(function_section(source_text, "try_noncall_callable_cached_facts"))
cached_local = cached_lookup.find("local_matches: mutable usize = 0")
cached_parent_walk = cached_lookup.find("scope_module <- try_noncall_module_parent(scope_module)")
cached_wildcard = cached_lookup.find("for import_index in 0..<environment.callable_wildcard_import_modules.count")
cached_scope_rank = cached_lookup.find("import_scope.len < selected_import_scope_length")
cached_selective = cached_lookup.find("for import_index in 0..<environment.callable_imported_member_names.count")
if min(cached_local, cached_parent_walk, cached_wildcard, cached_scope_rank, cached_selective) < 0 or not (
        cached_local < cached_parent_walk < cached_wildcard < cached_scope_rank < cached_selective):
    raise SystemExit("Try cached lookup must scan all lexical declarations, then outer-to-inner wildcards, then selective aliases")
if not all(fragment in cached_lookup for fragment in (
        "wildcard_ambiguous: mutable bool = false",
        "wildcard_ambiguous <- true if first_visible_import_module != \"\" and first_visible_import_module != environment.callable_wildcard_import_modules[import_index]",
        'return (false, "", false, false, false, true, "", 0.usize()) if wildcard_ambiguous')):
    raise SystemExit("Try cached lookup must fail closed when distinct visible wildcard targets make a bare name ambiguous")
cached_fact_builder = compact_inline(function_section(source_text, "try_noncall_callable_facts_add"))
if not all(fragment in cached_fact_builder for fragment in (
        "callable_visible: bool = callable_function_declaration_visible(annotations, name, current_module, function_position.line, function_position.offset, environment.current_module)",
        "environment.callable_names.push(name)",
        "environment.callable_visible.push(callable_visible)",
        "environment.callable_facts_known.push(family_rows <= 1.usize())",
        "environment.callable_first_param_type_names.push(first_param_type_name)",
        "environment.callable_first_param_generic.push(first_param_is_generic)",
        "environment.callable_max_param_counts.push(params.count)",
        "environment.callable_has_default_params.push(has_default_param)",
        "environment.callable_variadic.push(variadic)")):
    raise SystemExit("Try cached facts must retain visibility separately from known family facts")
if cached_lookup.count("environment.callable_visible[index]") < 4:
    raise SystemExit("Try cached local, wildcard, selective, and qualified lookup must filter inaccessible candidates")
cached_hidden_rank = compact_inline(function_section(source_text, "try_noncall_cached_hidden_candidate_blocks"))
if not all(fragment in cached_hidden_rank for fragment in (
        "not environment.callable_visible[index]",
        "environment.callable_max_param_counts[index] != arguments.count",
        "try_noncall_cached_argument_type_name(arguments[selected_argument_index], params)",
        "try_noncall_cached_argument_type_name(arguments[hidden_argument_index], params)",
        "try_noncall_cached_callable_in_ufcs_set(callee_name, environment.callable_modules[index], callee_qualifier, callee, environment)",
        "try_noncall_cached_receiver_type_matches(hidden_type, actual_type)",
        "actual_type == \"int\" and try_noncall_cached_integer_type(hidden_type) and try_noncall_cached_integer_type(selected_type)",
        "if selected_generic: return true")):
    raise SystemExit("Try cached family inference must fail closed when a viable hidden overload can win, while using known argument types to rule out incompatible private siblings")
cached_candidate_set = compact_inline(function_section(source_text, "try_noncall_cached_callable_in_ufcs_set"))
if not all(fragment in cached_candidate_set for fragment in (
        "try_noncall_module_is_ancestor(candidate_module, environment.current_module)",
        "try_noncall_module_is_ancestor(environment.callable_wildcard_import_scopes[import_index], environment.current_module)",
        "environment.callable_imported_member_names[import_index] != callee_name",
        "try_noncall_qualified_module_matches(callee, candidate_module, callee_name, environment, true)")):
    raise SystemExit("Try cached hidden-candidate checks must cover Core's lexical, wildcard, selective, and qualified receiver candidate modules")
cached_module_match = compact_inline(function_section(source_text, "try_noncall_qualified_module_matches"))
cached_qualifier_path = compact_inline(function_section(source_text, "try_noncall_qualifier_path_matches_module"))
cached_alias_target = compact_inline(function_section(source_text, "try_noncall_visible_using_alias_target"))
if not all(fragment in cached_module_match for fragment in (
        "include_hidden: bool",
        "try_noncall_qualifier_path_matches_module(qualifier, environment.callable_modules[index], scope_module)",
        "not include_hidden and not environment.callable_visible[index]",
        "try_noncall_callable_matches_using_alias(callee, alias_index, environment.callable_modules[index], environment)",
        "try_noncall_qualifier_path_matches_module(qualifier, module_path, \"\")")) or "module_path == name if lexical_scope == \"\"" not in cached_qualifier_path or "module_last_segment(module_path)" in cached_qualifier_path or "environment.using_alias_known[index]" not in cached_alias_target:
    raise SystemExit("Try cached qualified lookup must bind lexical module identity, the global alias target, and exact root spelling")
if "try_noncall_qualified_module_matches(callee, candidate_module, callee_name, environment, true)" not in cached_candidate_set or "try_noncall_qualified_module_matches(callee, environment.callable_modules[index], callee_name, environment, false)" not in cached_lookup or not all(fragment in private_overload_fixture for fragment in (
        "def qualified_private_winner_direct", "def qualified_private_winner_cached", "private:", "return try Provider::origin(value)")) or "try_overload_private_winner_visibility.elisa" not in private_overload_smoke:
    raise SystemExit("Try must match hidden qualified candidates in blocker mode while skipping them in ordinary cached lookup, with private winner coverage")
cached_lookup_signature = compact_inline(function_section(source_text, "try_noncall_callable_cached_facts"))
if "arguments: darray[Ast::Expr]&" not in cached_lookup_signature or "try_noncall_cached_hidden_candidate_blocks(callable_index, callee_name, callee_qualifier, callee, arguments, argument_names, params, environment)" not in cached_lookup_signature or "try_noncall_callable_cached_facts(callee_name, callee_qualifier, callee, environment)" in source_text:
    raise SystemExit("Every Try cached callable lookup must receive call arguments and caller parameter types before returning ErrorSet facts")
cached_static_binding = compact_inline(function_section(source_text, "try_noncall_static_binding_may_affect_call"))
if not all(fragment in cached_static_binding for fragment in (
        'unresolved.name == "__from_member"',
        'unresolved.name == "__binding_wildcard_import"',
        'unresolved.name == "__using_alias"',
        "try_noncall_visible_using_alias_target(environment, alias_head)",
        "continue if resolved_alias.known",
        "return true if any callable_index in 0..<environment.callable_names.count where environment.callable_names[callable_index] == callee_name and environment.callable_visible[callable_index]")) or "continue if not try_noncall_module_is_ancestor(unresolved.module, environment.current_module)" in cached_static_binding or not all(fragment in cached_lookup_signature for fragment in (
        "try_noncall_static_binding_may_affect_call(callee_name, callee_qualifier, callee, environment)",
        'return (false, "", false, false, false, true, "", 0.usize())')):
    raise SystemExit("Try cached callable facts must fail closed only when an unresolved static import or alias can reach a same-name candidate")
if cached_lookup_signature.find("try_noncall_static_binding_may_affect_call") > cached_lookup_signature.find("match_count: mutable usize"):
    raise SystemExit("Try must reject an unresolved static candidate before selecting cached callable facts")
static_alias_path_uncertain = compact_inline(function_section(source_text, "callable_static_alias_path_uncertain"))
if not all(fragment in static_alias_path_uncertain for fragment in (
        "semantic_possible_import_alias_head_target(segments[0], current_scope, before_offset, table)",
        'unresolved.owner != "__try_unresolved_static_binding" or unresolved.name != "__using_alias" or unresolved.detail_name != segments[0]',
        "possible_alias.module != unresolved.module or possible_alias.line != unresolved.line or possible_alias.offset != unresolved.offset",
        "semantic_possible_import_alias_precedes_position(possible_alias, current_scope, before_offset, table)",
        "visible_alias.raw_target",
        "before_offset <- visible_alias.offset",
        "return segments.count > 0.usize()")):
    raise SystemExit("Try direct callable lookup must keep uncertainty when an alias target path crosses a visible or unresolved alias head")
if not all(fragment in noncall_import_builder for fragment in (
        "environment.unresolved_static_bindings.push(unresolved)",
        "environment.unresolved_static_binding_targets.push(target_module)",
        "try_noncall_module_path(unresolved.module, source.name, table)",
        "try_noncall_module_path(unresolved.module, alias_target.owner, table)",
        'candidate_alias.name == "__using_alias" and candidate_alias.detail_name == target_head',
        "callable_using_alias_visible_target_global(annotations, unresolved.module, target_head, table)",
        "visible_target_alias.count == 0.usize() and not unresolved_target_alias",
        "environment.using_alias_known.push(alias_target.count == 1.usize() and alias_chain_known)",
        "callable_using_alias_target_chain_known(alias_selection.raw_target, alias_selection.scope, alias_selection.offset, table)",
        'candidate_alias.name == "__using_alias" and candidate_alias.detail_name == target_head')):
    raise SystemExit("Try non-call environments must retain unresolved marker targets through branch clones")
cached_env_clone = compact_inline(function_section(source_text, "try_noncall_family_clone"))
if not all(fragment in cached_env_clone for fragment in (
        "clone.callable_first_param_type_names.extend(environment.callable_first_param_type_names)",
        "clone.callable_first_param_generic.extend(environment.callable_first_param_generic)",
        "clone.callable_max_param_counts.extend(environment.callable_max_param_counts)",
        "clone.callable_has_default_params.extend(environment.callable_has_default_params)",
        "clone.callable_variadic.extend(environment.callable_variadic)",
        "clone.using_alias_known.extend(environment.using_alias_known)",
        "clone.unresolved_static_bindings.extend(environment.unresolved_static_bindings)",
        "clone.unresolved_static_binding_targets.extend(environment.unresolved_static_binding_targets)")):
    raise SystemExit("Try branch clones must preserve cached overload signature facts")
selected_receiver_acceptance = compact_inline(function_section(source_text, "callable_symbol_accepts_arity"))
if not all(fragment in selected_receiver_acceptance for fragment in (
        "accepts_call <- false if selected_type_candidate.value != INVALID_DECL_ID_VALUE and symbol.id.value != selected_type_candidate.value",
        "symbol.id.value == selected_type_candidate.value and not callable_function_declaration_visible")):
    raise SystemExit("Try family selection must reject a private receiver winner and its public overload siblings")
selected_receiver_count = compact_inline(function_section(source_text, "callable_symbol_arity_candidate_count"))
if not all(fragment in selected_receiver_count for fragment in (
        "selected_type_candidate.value.usize() >= table.symbols.count",
        "return 1.usize() if callable_function_declaration_visible",
        "return 0.usize()")):
    raise SystemExit("Try receiver candidate counting must keep private winners out of accessible family selection")
private_selected_fallibility = compact_inline(function_section(source_text, "callable_error_indexed_returns_error"))
if not all(fragment in private_selected_fallibility for fragment in (
        "selected_type_candidate: DeclId = callable_symbol_type_selected_candidate",
        "selected_private_winner: bool = selected_symbol.line == annotation.line",
        "not callable_function_declaration_visible(annotations, name, candidate_module, annotation.line, annotation.offset, enclosing_module)",
        "return true if selected_private_winner",
        "forwarded_private_candidate: bool = callable_row_in_ufcs_candidate_set_indexed",
        "unresolved_private_candidate: bool = callable_overload_declaration_is_inaccessible_arity_candidate",
        "return true if unresolved_private_candidate")):
    raise SystemExit("Try must suppress cascading TryRequiresFallible diagnostics for exact or unresolved private winners without exposing their ErrorSets")
private_family_ref = compact_inline(function_section(source_text, "callable_error_indexed_family_ref"))
if not all(fragment in private_family_ref for fragment in (
        "callable_row_visible_for_try_call(module_index, module_annotations, annotations, name, annotation.offset, annotation.line",
        "callable_symbol_accepts_arity(table, annotations, try_named_arguments, argument_type_ids",
        "return TryErrorFamilyRef{family: \"\"")) or "selected_private_winner" in private_family_ref:
    raise SystemExit("Try's private-winner suppression must not expose an inaccessible ErrorSet to propagation checks")
private_family_refs = compact_inline(function_section(source_text, "callable_error_indexed_family_refs"))
if not all(fragment in private_family_refs for fragment in (
        "visible: bool = callable_row_visible_for_try_call",
        "and callable_symbol_accepts_arity(table, annotations, try_named_arguments, argument_type_ids",
        "if visible")):
    raise SystemExit("Try composite family collection must apply the same visibility filter before selecting a propagation family")
unresolved_private_candidate = compact_inline(function_section(source_text, "callable_overload_declaration_is_inaccessible_arity_candidate"))
if not all(fragment in unresolved_private_candidate for fragment in (
        "callable_name_has_ufcs_overload_set_in_scope",
        "callable_row_in_ufcs_candidate_set_indexed",
        "callable_symbol_core_accepts_receiver_arity",
        "callable_symbol_accepts_named_arguments",
        "or callable_function_declaration_visible",
        "try_overload_receiver_pattern_matches(file, receiver.type_id, argument_type_ids[0]",
        "try_overload_type_shared_ambiguous_match_state(file, receiver.type_id, argument_type_ids[0]",
        "receiver_ref_mutability_known",
        "receiver.mutable_ref and not receiver_ref_mutable")):
    raise SystemExit("Try unresolved private-candidate checks must model Core's overload set, receiver compatibility, and reference mutability")
unresolved_private_guard = compact_inline(function_section(source_text, "callable_overload_has_inaccessible_arity_candidate"))
if "callable_overload_declaration_is_inaccessible_arity_candidate" not in unresolved_private_guard:
    raise SystemExit("Try must identify inaccessible receiver candidates before unresolved family fallback")
if "callable_overload_has_inaccessible_arity_candidate" not in selected_receiver_acceptance or "callable_overload_has_inaccessible_arity_candidate" not in selected_receiver_count:
    raise SystemExit("Try unresolved receiver selection must fail closed for ErrorSet family lookup when a private candidate remains")
forwarded_family_guard = compact_inline(function_section(source_text, "callable_symbol_accepts_arity"))
forwarded_candidate_count = compact_inline(function_section(source_text, "callable_symbol_arity_candidate_count"))
if not all(fragment in forwarded_family_guard for fragment in (
        "callable_try_call_forwards_arguments(annotations, try_offset)",
        "callable_name_has_ufcs_overload_set_candidate")) or not all(fragment in forwarded_candidate_count for fragment in (
        "callable_try_call_forwards_arguments(annotations, try_offset)",
        "callable_name_has_ufcs_overload_set_candidate")):
    raise SystemExit("Try forwarded calls must not propagate an arbitrary sibling ErrorSet, while singleton lookup remains available")
cached_source_facts = compact_inline(function_section(source_text, "try_noncall_callable_source_facts"))
if 'return (false, "", false, false, false) if cached_facts.ambiguous or callee_qualifier != ""' not in cached_source_facts:
    raise SystemExit("Try cached source inference must not borrow a family from an ambiguous wildcard lookup")
legacy_fallback = cached_source_facts.find("legacy_facts: (known: bool, family: sview @source) = try_noncall_callable_error_family(callee_name, annotations)")
hidden_name_blocker = cached_source_facts.find("return (false, \"\", false, false, false) if any name in environment.callable_names where name == callee_name")
if hidden_name_blocker < 0 or legacy_fallback < 0 or hidden_name_blocker > legacy_fallback:
    raise SystemExit("Try cached hidden-name metadata must block the unscoped legacy ErrorSet fallback")
receiver_match = compact_inline(function_section(source_text, "try_overload_receiver_pattern_matches"))
if not all(fragment in receiver_match for fragment in (
        "try_overload_type_is_generic_parameter(formal_type_id, declaration, annotations, table)",
        "return (true, true) if formal_type_id == actual_type_id",
        'interned_name(actual_type_id, table) == "int"',
        'formal_kind == SemTypeKind.Char and actual_kind == SemTypeKind.Int and interned_name(actual_type_id, table) == "int"',
        "type_ids_compatible(formal_type_id, actual_type_id, table)",
        "element_position in 0..<element_count.usize()")):
    raise SystemExit("Receiver matching must support exact generic parameters, compatible concrete types, and structural receiver shapes")
cached_integer_type = compact_inline(function_section(source_text, "try_noncall_cached_integer_type"))
cached_builtin_type = compact_inline(function_section(source_text, "try_noncall_cached_builtin_type"))
if '"char"' not in cached_integer_type or '"uintptr"' not in cached_integer_type or '"char"' not in cached_builtin_type or '"uintptr"' not in cached_builtin_type:
    raise SystemExit("Try cached receiver ranking must treat char and uintptr as integral storage for an untyped int actual")
primitive_type_facts = compact_inline(function_section(source_text, "try_noncall_type_name_facts"))
primitive_integer_facts = primitive_type_facts.split("integer: bool =", 1)
if len(primitive_integer_facts) != 2 or '"char"' not in primitive_integer_facts[0] or '"uintptr"' not in primitive_integer_facts[1] or "known_nonfallible: bool = numeric" not in primitive_integer_facts[1]:
    raise SystemExit("Try non-call primitive facts must keep char numeric and uintptr integral and known non-fallible")
receiver_specificity = compact_inline(function_section(source_text, "try_overload_receiver_specificity"))
if not all(fragment in receiver_specificity for fragment in (
        "return (true, 0.usize()) if try_overload_type_is_generic_parameter(type_id, declaration, annotations, table)",
        "score <- score + element_score.score",
        "return (true, 1.usize())")):
    raise SystemExit("Receiver specificity must rank generic leaves below concrete leaves and add structural specificity")
receiver_type = compact_inline(function_section(source_text, "callable_symbol_receiver_type"))
if "table.function_param_mutable_ref[row]" not in receiver_type or "mutable_ref_known: bool" not in receiver_type:
    raise SystemExit("Receiver ranking must retain the selected formal reference mutability")
if "declared.writable_borrow" not in argument_types or "receiver_ref_mutability_known" not in argument_types:
    raise SystemExit("Try receiver ranking must retain exact binding reference mutability when available")
if not all(fragment in argument_types for fragment in (
        "receiver_ref_mutability_seen: bool = receiver_ref_mutability_known",
        "if not receiver_ref_mutability_seen:",
        "receiver_ref_mutability_resolved: bool = receiver_ref_mutability_known",
        "not receiver_ref_mutability_resolved")):
    raise SystemExit("Try receiver mutability reads must snapshot the mutable output reference before boolean negation")
firm_type = compact_inline(function_section(source_text, "try_overload_type_is_firm"))
if not all(fragment in firm_type for fragment in (
        "try_overload_type_is_generic_parameter(type_id, declaration, annotations, table)",
        "try_overload_nominal_type_owner(file, name, declaration, annotations, table)",
        "return identity.found")):
    raise SystemExit("Try firm named receiver types must resolve one nominal owner in the declaration's lexical scope")
module_firm_type = compact_inline(function_section(source_text, "try_overload_type_is_firm_in_module"))
if not all(fragment in module_firm_type for fragment in (
        "depth > 64",
        "try_overload_nominal_type_owner_for_module(file, name, lexical_module, annotations, table)",
        "try_overload_type_is_firm_in_module(file, interned_elem(type_id, element_position.u32(), table), lexical_module, annotations, table, depth + 1)")):
    raise SystemExit("Try receiver ranking must resolve named actual types in the call-site module, including nested type shapes")
type_visibility = compact_inline(function_section(source_text, "try_overload_type_declaration_visible"))
if not all(fragment in type_visibility for fragment in (
        "try_error_alias_module_visible(annotations, declaration_module, lexical_module)",
        "type_symbol_is_alias",
        "try_noncall_type_alias_declaration_is_static_inactive(file, annotations, name, declaration_module, declaration_line, declaration_offset, table)",
        "try_overload_nominal_type_declaration_is_static_inactive(file, annotations, name, declaration_module, declaration_line, declaration_offset, table)",
        'annotation.owner != "__section_private"',
        "exact_offset",
        "try_noncall_module_is_ancestor(declaration_module, lexical_module)")):
    raise SystemExit("Try nominal owner lookup must filter inaccessible modules and declaration-specific private type markers")
nominal_static_activity = compact_inline(function_section(source_text, "try_overload_nominal_type_declaration_is_static_inactive"))
nominal_type_classifier = compact_inline(function_section(source_text, "try_overload_type_symbol_is_nominal"))
if not all(fragment in nominal_type_classifier for fragment in (
        "symbol.kind == SymbolKind.Struct",
        "symbol.kind == SymbolKind.Enum",
        "symbol.kind == SymbolKind.Alias",
        "symbol.kind == SymbolKind.Extern and symbol.opaque_extern_type")):
    raise SystemExit("Try nominal owner lookup must classify structs, enums, aliases, and opaque extern types")
if not all(fragment in nominal_static_activity for fragment in (
        'marker.owner != "__static_if_branch"',
        'marker.name != "__nominal_type_static_branch"',
        "marker.detail_name != name",
        "marker.module != declaration_module",
        "marker.line != declaration_line",
        "marker.offset != declaration_offset",
        "continue if marker.identity_id == 4294967295",
        "pma_static_if_row_selection(file, marker.identity_id.usize(), declaration_module, table)",
        "return true if branch.known and not branch.selected")):
    raise SystemExit("Try nominal owner lookup must exclude only exact, proven-inactive non-alias type declarations")
error_set_static_activity = compact_inline(function_section(source_text, "try_error_set_decl_is_static_inactive"))
if not all(fragment in error_set_static_activity for fragment in (
        'name_row.owner != "__lsp_decl_name"',
        "name_row.line != declaration.line",
        "name_row.pos.offset != declaration.offset",
        "name_row_count != 1.usize()",
        "try_overload_nominal_type_declaration_is_static_inactive(file, annotations, declaration.name, declaration.module, declaration.line, declaration_keyword_offset, table)")) or not all(fragment in nominal_static_activity for fragment in (
        "continue if marker.identity_id == 4294967295",
        "return true if branch.known and not branch.selected")):
    raise SystemExit("Try family uniqueness must ignore only exact, proven-inactive ErrorSets and retain unknown branch owners")
type_owner_module = compact_inline(function_section(source_text, "try_overload_type_owner_in_module"))
if not all(fragment in type_owner_module for fragment in (
        "try_overload_type_symbol_is_nominal(symbol)",
        "try_overload_type_declaration_visible(file, annotations, symbol.kind == SymbolKind.Alias, name, declaration_module, symbol.line, symbol.offset, lexical_module, table)",
        "return (count > 0.usize(), false, declaration_module)")):
    raise SystemExit("Try nominal owner lookup must recognize a visible owner within one module and leave duplicate declarations to Core")
nominal_type_identity = compact_inline(function_section(source_text, "try_overload_nominal_type_owner_for_module"))
if not all(fragment in nominal_type_identity for fragment in (
        "try_overload_type_owner_in_module(file, name, scope_module, lexical_module, annotations, table)",
        "return local if local.found or local.ambiguous",
        "scope_module <- try_noncall_module_parent(scope_module)",
        'binding.owner != "__from_member"',
        'source.owner != "__from_src"',
        "callable_import_module_matches_target(symbol.module_owner, binding.module, source.name)",
        'binding.name != "__binding_wildcard_import"',
        "binding.module.len > wildcard_scope_length",
        "try_overload_type_declaration_visible(file, annotations, symbol.kind == SymbolKind.Alias, name, symbol.module_owner, symbol.line, symbol.offset, lexical_module, table)")):
    raise SystemExit("Try nominal identity must follow local and ancestor declarations, selective imports, then the nearest visible wildcard import")
nominal_type_owner = compact_inline(function_section(source_text, "try_overload_nominal_type_owner"))
if not all(fragment in nominal_type_owner for fragment in (
        "table.symbols[declaration.value.usize()].module_owner",
        "try_overload_nominal_type_owner_for_module(file, name, table.symbols[declaration.value.usize()].module_owner, annotations, table)")):
    raise SystemExit("Try formal nominal identities must be resolved from the owning declaration's module")
ambiguous_type_identity = compact_inline(function_section(source_text, "try_overload_type_has_ambiguous_nominal_identity"))
if not all(fragment in ambiguous_type_identity for fragment in (
        "try_overload_type_is_generic_parameter(type_id, declaration, annotations, table)",
        "try_overload_nominal_type_owner(file, name, declaration, annotations, table)",
        "identity.ambiguous",
        "interned_elem(type_id, element_position.u32(), table)")):
    raise SystemExit("Try ambiguous nominal receiver detection must preserve generic identity and recurse through structural types")
if not all(fragment in receiver_match for fragment in (
        "try_overload_nominal_type_owner(file, name, declaration, annotations, table)",
        "try_overload_nominal_type_owner_for_module(file, name, actual_module, annotations, table)",
        "formal_identity.ambiguous or actual_identity.ambiguous",
        "formal_identity.owner == actual_identity.owner")):
    raise SystemExit("Try named receiver matching must compare lexical nominal owners and fail closed on ambiguity")
argument_types = compact_inline(function_section(source_text, "try_call_argument_type_ids"))
if "try_overload_type_has_ambiguous_nominal_identity(file, argument_type_id, caller, annotations, table, 0)" not in argument_types or "argument_type_firm or argument_type_ambiguous" not in argument_types:
    raise SystemExit("Try argument typing must preserve ambiguous nominal identity for candidate lookup to fail closed")
shared_ambiguous_match = compact_inline(function_section(source_text, "try_overload_type_shared_ambiguous_match_state"))
if not all(fragment in shared_ambiguous_match for fragment in (
        "try_overload_nominal_type_owner_for_module(file, name, actual_module, annotations, table)",
        "try_overload_nominal_type_owner(file, name, formal_declaration, annotations, table)",
        "actual_identity.owner != formal_identity.owner",
        'formal_kind == SemTypeKind.Int and actual_kind == SemTypeKind.Int and interned_name(actual_type_id, table) == "int"',
        'formal_kind == SemTypeKind.Char and actual_kind == SemTypeKind.Int and interned_name(actual_type_id, table) == "int"',
        "element_count != interned_elem_count(formal_type_id, table)",
        "has_ambiguous_element <- true if element_state.ambiguous")):
    raise SystemExit("Try ambiguity overlap must include Core's int-to-integer and int-to-char receiver coercions, distinguish known different owners, and recurse through structural shapes")
ambiguous_receiver_candidate = compact_inline(function_section(source_text, "callable_overload_has_ambiguous_nominal_receiver_candidate"))
if not all(fragment in ambiguous_receiver_candidate for fragment in (
        "callable_name_has_ufcs_overload_set_in_scope(module_index, module_annotations, annotations, name, enclosing_module, callee_qualifier, try_named_arguments, try_offset, table)",
        "callable_row_in_ufcs_candidate_set_indexed(module_index, module_annotations, annotations, name, symbol.offset, symbol.line, enclosing_module, callee_qualifier, table)",
        "callable_symbol_core_accepts_receiver_arity(table, symbol, arity)",
        "callable_symbol_receiver_type(table, symbol)",
        "try_overload_type_shared_ambiguous_match_state(file, receiver.type_id, argument_type_ids[0], symbol.id, enclosing_module, annotations, table, 0)",
        "ambiguous_match.potential_match and ambiguous_match.ambiguous")):
    raise SystemExit("Try ambiguity rejection must be limited to a visible, arity-eligible receiver candidate with a shared ambiguous nominal spelling")
if "return false if callable_overload_has_ambiguous_nominal_receiver_candidate" not in selected_receiver_acceptance or "return 0.usize() if callable_overload_has_ambiguous_nominal_receiver_candidate" not in selected_receiver_count:
    raise SystemExit("Try candidate fallback must not reselect a visible concrete overload after nominal receiver identity becomes ambiguous")
parser_source = PARSER_ARGUMENT_SOURCE.read_text()
if 'owner: "__try_callee_argument_position"' not in parser_source or "pos: Ast::expr_pos(arguments[index])" not in parser_source:
    raise SystemExit("Try calls must retain each actual argument's exact AST position for resolved type lookup")
parser_nominal_text = [path.read_text() for path in PARSER_NOMINAL_SOURCES]
if parser_nominal_text[0].count('record_static_if_branch_rows("__nominal_type_static_branch", name_text, token)') != 2 or \
        'record_static_if_branch_rows("__nominal_type_static_branch", target_name, token)' not in parser_nominal_text[1] or \
        'record_static_if_branch_rows("__nominal_type_static_branch", name, token)' not in parser_nominal_text[1]:
    raise SystemExit("Try nominal lookup must receive exact static-branch markers for structs, enums, opaque externs, and exported types")
error_set_parser = compact_inline(function_section(parser_nominal_text[2], "error_type_declaration"))
declaration_name_parser = compact_inline(function_section(PARSER_DECLARATION_SOURCE.read_text(), "record_lsp_declaration_name"))
if not all(fragment in error_set_parser for fragment in (
        "record_lsp_declaration_name(error_set_name, token, name_token, name_token)",
        'record_static_if_branch_rows("__nominal_type_static_branch", error_set_name, token)',
        'owner: "__error_set_decl", name: error_set_name, module: parser.current_module, line: name_token.line, offset: name_token.start')) or not all(fragment in declaration_name_parser for fragment in (
        "offset: declaration_token.start",
        "offset: first_name_token.start")):
    raise SystemExit("Try ErrorSet activity lookup must join the name-token declaration row to the exact keyword-position branch marker")
parser_try_expression = compact_inline(function_section(parser_source, "get_expression"))
parser_call_arity = compact_inline(function_section(parser_source, "try_expression_call_arity"))
parser_try_arguments = compact_inline(function_section(parser_source, "try_expression_record_named_arguments"))
if not all(fragment in parser_try_arguments for fragment in (
        'marker.owner == "__arg_forward"',
        'owner: "__try_callee_argument_forward"',
        'Ast::Expr.Call(callee, _, _, _)',
        'owner: "__try_callee_argument_direct_call"',
        "call_position.offset",
        "offset: try_offset")):
    raise SystemExit("Try parser metadata must carry forwarding state and direct-call identity from each argument to its Try position")
forward_try_selector = compact_inline(function_section(source_text, "callable_try_call_forwards_arguments"))
if 'marker.owner == "__try_callee_argument_forward"' not in forward_try_selector or "return invalid if callable_try_call_forwards_arguments" not in compact_inline(function_section(source_text, "callable_symbol_type_selected_candidate")):
    raise SystemExit("Try receiver overload ranking must be disabled for forwarded argument calls")
if not all(fragment in parser_try_expression for fragment in (
        'owner: "__try_callee_arity"',
        "line: get_token.line",
        "offset: get_token.start",
        "identity_id: call_arity.value",
        "if call_arity.known")) or not all(fragment in parser_call_arity for fragment in (
        "Ast::Expr.Call(_, arguments, _, _)",
        "return (false, 0) if any marker in parser.enum_annotations",
        'marker.owner == "__arg_forward"',
        "return (true, arguments.count.u32())",
        "Ast::Expr.Paren(inner, _)",
        "return parser.try_expression_call_arity(inner)")):
    raise SystemExit("Try calls must retain known positional arity, mark forwarded arity unknown, and recurse through parentheses")
try_projection = compact_inline(function_section(source_text, "fallible_try_projection_add"))
try_arity_lookup = compact_inline(function_section(source_text, "try_callee_arity"))
try_rows = compact_inline(function_section(source_text, "check_try_fallible_rows"))
if not all(fragment in try_projection for fragment in (
        'annotation.owner == "__try_callee_arity"',
        "projection.try_arities.get(annotation.offset.u64())",
        "projection.try_arities <- projection.try_arities.put(annotation.offset.u64(), annotation.identity_id)")) or not all(fragment in try_arity_lookup for fragment in (
        "index.get(try_offset.u64())",
        "return (true, arity)")) or not all(fragment in try_rows for fragment in (
        "try_callee_arity(try_arities, annotation.offset)",
        "row_arity.value",
        "if row_arity.known else []")):
    raise SystemExit("Try overload ranking must consume the parser's call arity by the exact try-site offset")
parser_visibility_source = PARSER_VISIBILITY_SOURCE.read_text()
parser_function_source = PARSER_FUNCTION_SOURCE.read_text()
if not all(fragment in compact_inline(parser_function_source) for fragment in (
        'owner: function_name, name: "__error_return", line: token.line, offset: token.start',
        'owner: "__fn_module", name: parser.current_module, line: token.line, offset: token.start')):
    raise SystemExit("Try byte-zero return and module rows must retain their parser token offsets")
section_marker = compact_inline(function_section(parser_visibility_source, "record_section_member"))
if not all(fragment in section_marker for fragment in (
        '"__section_private" if visibility_name == "private" else "__section_public"',
        "line: member_position.line",
        "offset: member_position.offset",
        "module: owning_module")):
    raise SystemExit("Try declaration visibility requires parser section markers with exact line, offset, and module identity")
parser_catch_source = compact_inline(function_section(PARSER_CATCH_SOURCE.read_text(), "catch_statement"))
if 'owner: "__catch_match", name: "__catch_match", line: catch_token.line, offset: catch_token.start, module: parser.current_module' not in parser_catch_source:
    raise SystemExit("statement-catch markers must preserve module identity alongside exact token line and offset")

family_module = compact_inline(function_section(source_text, "try_error_set_decl_module_for_annotation"))
root_precedence = 'return (true, family_annotation.name, "", false) if not qualified and try_error_set_decl_has_owner(annotations, family_annotation.name, "")'
if root_precedence not in family_module or family_module.index(root_precedence) > family_module.index("for declaration in annotations"):
    raise SystemExit("A bare root error-set declaration must win before Try scans lexical module candidates")
if not all(fragment in family_module for fragment in (
        "(found: bool, uncertain: bool, module: sview @source) = catch_explicit_error_family_module",
        'return (false, family_annotation.name, "", true) if qualified and explicit_module.uncertain',
        'return (false, family_annotation.name, "", true) if not qualified and family_path != "" and not catch_module_path_matches(family_path, family_annotation.name)')):
    raise SystemExit("Try must keep uncertain qualified ErrorSet aliases unknown before considering raw module candidates")
bare_path_guard = 'return (false, family_annotation.name, "", true) if not qualified and family_path != "" and not catch_module_path_matches(family_path, family_annotation.name)'
root_alias_lookup = 'try_error_alias_index(family_annotation.name, "", table)'
if family_module.index(bare_path_guard) > family_module.index(root_precedence) or family_module.index(bare_path_guard) > family_module.index(root_alias_lookup):
    raise SystemExit("Try must reject a malformed nonempty bare ErrorSet path before root declaration or alias lookup")
root_nominal_precedence = 'return (false, family_annotation.name, "", false) if not qualified and function_module_known and try_error_local_nominal_type_shadows_family(annotations, family_annotation.name, function_module, table)'
if root_nominal_precedence not in family_module or family_module.index(root_nominal_precedence) > family_module.index("try_error_alias_index(family_annotation.name, \"\", table)"):
    raise SystemExit("A root nominal type must shadow lexical and imported same-name ErrorSets before alias candidate lookup")
alias_target_path = compact_inline(function_section(source_text, "try_error_alias_target_path"))
if not all(fragment in alias_target_path for fragment in ("Expr.Scope(base, name, _)", "Expr.Paren(inner, _)", "intern_joined_text(bytes, table)")):
    raise SystemExit("Try alias lookup must retain complete qualified and parenthesized AST target paths")
alias_cycle_guard = compact_inline(function_section(source_text, "try_error_alias_declaration_identity"))
if not all(fragment in alias_cycle_guard for fragment in (
        "declaration.declaration_id.value",
        "any prior_id in visited where prior_id == declaration.declaration_id.value",
        "visited <- visited.push(declaration.declaration_id.value)",
        "try_error_alias_target_identity(annotations, declaration.target",
        "_ = visited.pop()")):
    raise SystemExit("Try alias resolution must follow TypeAliasDeclaration targets with declaration-identity cycle protection")
alias_target_identity = compact_inline(function_section(source_text, "try_error_alias_target_identity"))
if not all(fragment in alias_target_identity for fragment in (
        "try_error_alias_module_path_matches(target_path, target_family",
        "try_error_alias_declaration_identity(annotations, selected_alias, table, visited)",
        "try_error_alias_index(target_family, \"\", table)",
        "try_error_alias_imported_at_scope(annotations, target_family",
        "return try_error_alias_declaration_identity(annotations, selected_imported_alias_index, table, visited) if selected_imported_alias_count == 1.usize()",
        "return (true, selected_imported_family, selected_imported_module, false) if selected_imported_count == 1.usize()")):
    raise SystemExit("Try alias targets must resolve qualified chains, root aliases, and selectively imported aliases to canonical ErrorSet identity")
import_path_match = compact_inline(function_section(source_text, "try_error_set_import_path_matches"))
direct_import_visibility = compact_inline(function_section(source_text, "try_error_set_decl_imported_at_scope"))
alias_visibility = compact_inline(function_section(source_text, "try_error_alias_imported_at_scope"))
private_alias_path = compact_inline(function_section(source_text, "try_error_alias_module_visible"))
private_alias_name = compact_inline(function_section(source_text, "try_error_alias_name_visible"))
generic_return_identity = compact_inline(function_section(source_text, "try_noncall_function_return_is_generic"))
generic_return_facts = compact_inline(function_section(source_text, "try_noncall_callable_facts_add"))
if not all(fragment in private_alias_path for fragment in (
        "candidate_module: sview, lexical_module: sview) -> bool",
        "segment: sview = candidate_module[segment_start:segment_end]",
        "owner: sview = candidate_module[0:segment_start - 2.usize()] if segment_start >= 2.usize() else \"\"",
        "private_scope: sview = candidate_module[0:segment_end]")) or "@source" in private_alias_path:
    raise SystemExit("Try private-module visibility must compare temporary path slices without retaining source-region views")
if "current_module: sview @source" not in generic_return_identity or \
        "current_module: sview @source" not in generic_return_facts:
    raise SystemExit("Try generic-return identity must keep its caller-guaranteed source-backed module through its annotation scan")
if "scope_bound and not catch_module_is_ancestor(import_module, function_module)" not in import_path_match:
    raise SystemExit("Try import path matching must distinguish lexical wildcard visibility from program-wide selective imports")
wildcard_scope_filter = 'import_row.module != scope_module or import_row.name != "__binding_wildcard_import"'
if not all(fragment in direct_import_visibility for fragment in (
        "try_error_alias_module_visible(annotations, declaration.module, function_module)",
        wildcard_scope_filter,
        'if scope_module == ""',
        'import_row.owner != "__from_member" or import_row.name != declaration.name',
        "function_module, declaration.module, false)")) or direct_import_visibility.index('if scope_module == ""') < direct_import_visibility.index(wildcard_scope_filter):
    raise SystemExit("Try direct ErrorSet lookup must search lexical wildcard imports before the first program-level selective import")
direct_selective_start = direct_import_visibility.index('if scope_module == ""')
direct_selective_member = direct_import_visibility.index('import_row.owner != "__from_member" or import_row.name != declaration.name', direct_selective_start)
direct_selective_return = direct_import_visibility.index("return try_error_set_import_path_matches", direct_selective_member)
if not all(fragment in alias_visibility for fragment in (
        wildcard_scope_filter,
        'if scope_module == ""',
        'import_row.owner != "__from_member" or import_row.name != name',
        "function_module, declaration_module, false)")) or alias_visibility.index('if scope_module == ""') < alias_visibility.index(wildcard_scope_filter):
    raise SystemExit("Try type-alias lookup must search lexical wildcard imports before the first program-level selective import")
alias_selective_start = alias_visibility.index('if scope_module == ""')
alias_selective_member = alias_visibility.index('import_row.owner != "__from_member" or import_row.name != name', alias_selective_start)
alias_selective_return = alias_visibility.index("return try_error_set_import_path_matches", alias_selective_member)
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
        "module AliasInstallerA:\n    static if UNKNOWN_ALIAS_TARGET:\n        using AliasSafeProvider as RootCollision",
        "module AliasInstallerB:\n    static if UNKNOWN_ALIAS_TARGET:\n        using AliasSafeProvider as RootCollision",
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
if "try_error_alias_name_visible(annotations, name, declaration_module, function_module)" not in alias_visibility or not all(fragment in private_alias_path for fragment in (
        'row.owner == "__section_private"',
        "row.name == segment",
        "catch_module_is_ancestor(private_scope, lexical_module)")) or not all(fragment in private_alias_name for fragment in (
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
may_raise_source = function_section(source_text, "try_noncall_expression_may_raise_catchably_with_annotations")
call_argument_scan = """
Expr.Call(callee, arguments, _, _):
    direct_raise: bool = callee is Expr.Ident("raise", _)
    if not direct_raise:
        return true if try_noncall_expression_may_raise_catchably_with_annotations(callee, annotations, lexical_module)
        return false if try_noncall_expression_aborts_with_annotations(callee, annotations, lexical_module)
    for argument in arguments:
        return true if try_noncall_expression_may_raise_catchably_with_annotations(argument, annotations, lexical_module)
        return false if try_noncall_expression_aborts_with_annotations(argument, annotations, lexical_module)
"""
if not contains_contiguous_block(may_raise_source, call_argument_scan):
    raise SystemExit("Try call catchability must scan ordinary arguments in evaluation order before callable metadata")

main_try_check = function_section(source_text, "check_try_fallible")
static_binding_selection = compact_inline(function_section(source_text, "try_static_binding_branch_selection"))
static_binding_filter = compact_inline(function_section(source_text, "try_static_binding_filtered_annotations"))
if not all(fragment in static_binding_selection for fragment in (
        'marker.owner != "__static_if_branch"',
        'marker.detail_name != marker_detail',
        "pma_static_if_row_selection(file, marker.identity_id.usize(), annotation.module, table)",
        "return (true, true, false) if branch.known and not branch.selected",
        "return (true, false, false) if unresolved")) or not all(fragment in static_binding_filter for fragment in (
        "try_static_binding_branch_selection(annotation, file.enum_annotations, file, table)",
        "if branch.tracked and branch.known and not branch.active:",
        'owner: "__try_unresolved_static_binding"',
        'name: "__using_alias"')):
    raise SystemExit("Try must filter proven-inactive import/alias rows and retain unresolved bindings as conservative sentinels")
unresolved_static_binding = compact_inline(function_section(source_text, "callable_try_static_binding_uncertain"))
if not all(fragment in unresolved_static_binding for fragment in (
        'unresolved.owner != "__try_unresolved_static_binding"',
        'unresolved.name == "__from_member"',
        'unresolved.name == "__binding_wildcard_import"',
        'unresolved.name == "__using_alias"')):
    raise SystemExit("Try callable resolution must decline a family when an unresolved static binding could affect the call")
rows_call = "table <- check_try_fallible_rows(file, file.top_decls, try_annotations, projection.try_named_arguments, projection.try_argument_positions, projection.error_set_annotations, projection.error_set_family_paths, module_index, projection.module_annotations, projection.try_qualifiers, projection.try_arities, error_index, try_site_count, table) can Global{Read,Write} if try_site_count > 0"
if compact_inline(main_try_check).count(compact_inline(rows_call)) != 1:
    raise SystemExit("check_try_fallible must invoke the source-row checker when at least one try site exists")
if 'try_annotations: darray[Ast::EnumAnnotation] = try_static_binding_filtered_annotations(file, table)' not in compact_inline(main_try_check):
    raise SystemExit("check_try_fallible must derive its callable imports from the static-branch-filtered annotation set")

if semantic_text.count('include "./check_try_fallible.elisa"') != 1:
    raise SystemExit("semantic module no longer includes the try-fallibility checker exactly once")
pipeline_function = function_section(pipeline_text, "check_full_into_pipeline")
pipeline_steps = [
    normalize_code_line(line)
    for line in pipeline_function.splitlines()
    if strip_line_comment(line).strip()
]
pipeline_call = normalize_code_line("table <- check_try_fallible(loop_view, table) can Global{Read,Write}")
pipeline_timer = normalize_code_line('PhaseTimer::minor("sem:check_try_fallible") can Global{Read,Write}')
if not any(pipeline_steps[index:index + 2] == [pipeline_call, pipeline_timer]
           for index in range(len(pipeline_steps) - 1)):
    raise SystemExit("semantic pipeline no longer invokes and times check_try_fallible")

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("try enclosing-function proof inventory is incomplete or contains extras")
if 'include "./try_enclosing_function_index.elisa"' not in negative_text:
    raise SystemExit("negative controls no longer include the positive predecessor proof")

positive_shapes = {
    "try_predecessor_is_last": (
        "offsets[index] != TRY_ENCLOSING_NO_OFFSET and offsets[index] <= query",
        "forall later in index + TRY_ENCLOSING_POSITION_STEP..<offsets.count",
        "forall candidate in TRY_ENCLOSING_FIRST_POSITION..<offsets.count",
    ),
    "try_linear_predecessor": (
        "if offsets[index] != TRY_ENCLOSING_NO_OFFSET and offsets[index] <= query:",
        "selected <- index",
        "invariant found implies (",
        "invariant found or (",
        "forall prior in TRY_ENCLOSING_FIRST_POSITION..<index",
        "offsets[prior] == TRY_ENCLOSING_NO_OFFSET or offsets[prior] > query",
        "return (found, selected)",
    ),
    "try_binary_predecessor": (
        "requires try_offsets_are_valid(offsets)",
        "requires try_offsets_are_nondecreasing(offsets)",
        "invariant forall prior in TRY_ENCLOSING_FIRST_POSITION..<low: offsets[prior] <= query",
        "invariant forall later in high..<offsets.count: offsets[later] > query",
        "if offsets[middle] <= query:",
        "low <- middle + TRY_ENCLOSING_POSITION_STEP",
        "high <- middle",
        "return (true, low - TRY_ENCLOSING_POSITION_STEP)",
        "return (false, TRY_ENCLOSING_FIRST_POSITION)",
    ),
    "last_predecessor_results_are_unique": (
        "requires try_predecessor_is_last(offsets, query, left_found, left_index)",
        "requires try_predecessor_is_last(offsets, query, right_found, right_index)",
        "ensure left_found == right_found and left_index == right_index",
        "left_found == right_found and left_index == right_index",
    ),
    "sorted_binary_predecessor_equals_linear_reference": (
        "ensure try_binary_predecessor(offsets, query) == try_linear_predecessor(offsets, query)",
        "linear: (found: bool, index: usize) = try_linear_predecessor(offsets, query)",
        "indexed: (found: bool, index: usize) = try_binary_predecessor(offsets, query)",
        "return last_predecessor_results_are_unique(offsets, query, linear.found, linear.index, indexed.found, indexed.index)",
    ),
    "duplicate_offsets_select_the_last_qualifying_position": (
        "indexed.index == TRY_ENCLOSING_SECOND_POSITION",
    ),
    "zero_offset_is_a_real_position": (
        "offsets: darray[u32] = [0, TRY_ENCLOSING_DUPLICATE_OFFSET]",
        "try_binary_predecessor(offsets, 0)",
        "indexed.found and indexed.index == TRY_ENCLOSING_FIRST_POSITION and indexed == linear",
    ),
    "unsorted_offsets_keep_zero_in_linear_fallback": (
        "offsets: darray[u32] = [TRY_ENCLOSING_DUPLICATE_OFFSET, 0]",
        "try_linear_predecessor(offsets, 0)",
        "linear.found and linear.index == TRY_ENCLOSING_SECOND_POSITION",
    ),
    "try_offsets_are_valid": (
        "forall position in TRY_ENCLOSING_FIRST_POSITION..<offsets.count",
        "offsets[position] != TRY_ENCLOSING_NO_OFFSET",
    ),
    "try_offsets_are_nondecreasing": (
        "forall left in TRY_ENCLOSING_FIRST_POSITION..<offsets.count",
        "forall right in left..<offsets.count: offsets[left] <= offsets[right]",
    ),
    "sorted_binary_predecessor_preserves_parallel_line_mapping": (
        "requires offsets.count == lines.count",
        "requires try_offsets_are_valid(offsets)",
        "requires try_offsets_are_nondecreasing(offsets)",
        "indexed == linear and lines[indexed.index] == lines[linear.index] and offsets[indexed.index] == offsets[linear.index]",
    ),
    "empty_index_reports_no_predecessor": (
        "offsets: darray[u32] = []",
        "not indexed.found and indexed.index == TRY_ENCLOSING_FIRST_POSITION",
    ),
    "sorted_index_without_a_predecessor_reports_fallback_case": (
        "requires try_offsets_are_valid(offsets)",
        "requires try_offsets_are_nondecreasing(offsets)",
        "offsets.count == TRY_ENCLOSING_FIRST_POSITION or offsets[TRY_ENCLOSING_FIRST_POSITION] > query",
        "not indexed.found and indexed.index == TRY_ENCLOSING_FIRST_POSITION and indexed == linear",
    ),
}
for name, fragments in positive_shapes.items():
    body = compact_inline(function_section(positive_text, name))
    if any(compact_inline(fragment) not in body for fragment in fragments):
        raise SystemExit(f"positive predecessor theorem changed its stated contract or algorithm: {name}")
for name in NEGATIVE_NAMES:
    if f"def {name}(" not in negative_text:
        raise SystemExit(f"negative predecessor control missing: {name}")
negative_shapes = {
    "false_claim_duplicate_offsets_select_the_first_position": "indexed.index == TRY_ENCLOSING_FIRST_POSITION",
    "false_claim_duplicate_offsets_keep_the_first_line": "lines[indexed.index] == lines[TRY_ENCLOSING_FIRST_POSITION]",
    "false_claim_empty_index_has_a_predecessor": "return indexed.found",
    "false_claim_no_predecessor_has_a_position": "return indexed.found",
}
for name, fragment in negative_shapes.items():
    if compact_inline(fragment) not in compact_inline(function_section(negative_text, name)):
        raise SystemExit(f"negative predecessor control no longer states its counterclaim: {name}")
for raw_value in ("middle: usize = low + (high - low) / 2", "low <- middle + 1", "low - 1"):
    if raw_value in positive_text:
        raise SystemExit(f"proof model contains a raw position-search value: {raw_value}")

if args.source_only:
    print(json.dumps({"source_bound": True, "theorems": len(POSITIVE_NAMES), "try_source_files": len(SOURCE_FILES), "pipeline_source_files": len(PIPELINE_FILES), "parser_argument_source": 1, "parser_function_source": 1, "parser_visibility_source": 1, "parser_nominal_sources": len(PARSER_NOMINAL_SOURCES)}))
    raise SystemExit(0)

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("try enclosing-function proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != product_manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    *SOURCE_FILES,
    SEMANTIC,
    *PIPELINE_FILES,
    PARSER_ARGUMENT_SOURCE,
    PARSER_FUNCTION_SOURCE,
    PARSER_DECLARATION_SOURCE,
    PARSER_VISIBILITY_SOURCE,
    PARSER_CATCH_SOURCE,
    *PARSER_NOMINAL_SOURCES,
    ZERO_OFFSET_ENCLOSING_FIXTURE,
    TRY_SMOKE,
    ROOT / "test/atoms/try_fallback_source.elisa",
    ROOT / "test/repro/try_overload_private_same_named_module_types.elisa",
    ROOT / "test/parity/try_overload_private_same_named_module_types_smoke.sh",
    ROOT / "test/repro/try_overload_nominal_identity_controls.elisa",
    ROOT / "test/parity/try_overload_nominal_identity_controls_smoke.sh",
    ROOT / "test/repro/try_overload_static_import_family.elisa",
    ROOT / "test/repro/try_overload_static_alias_family.elisa",
    ROOT / "test/repro/try_overload_imported_argument_type_id.elisa",
    LINE_ZERO_NONERROR_FIXTURE,
    FIRST_CLASS_AMBIGUOUS_FAMILY_FIXTURE,
    FIRST_CLASS_INACTIVE_DUPLICATE_FAMILY_FIXTURE,
    ROOT / "test/parity/try_overload_imported_argument_type_id_smoke.sh",
    ROOT / "test/parity/try_overload_static_import_family_smoke.sh",
    ROOT / "test/parity/try_overload_static_alias_family_smoke.sh",
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_PROCESS_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(POSITIVE_NAMES)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_NAMES) + len(NEGATIVE_NAMES)
assert negative["summary"]["proven"] < negative["summary"]["obligations"]
assert {finding["name"] for finding in negative["findings"]} == NEGATIVE_NAMES
assert all(finding["kind"] == "ensure-unproven" for finding in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert require_current_product(BIN, PROVER) == product_manifest
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay or final provenance validation"
print(json.dumps({
    "admitted": True,
    "scope": "the model proves sorted predecessor selection and preserves its parallel line mapping; source gates pin zero-offset, unsorted-index, and no-predecessor fallback wiring to the production linear lookup",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
}, sort_keys=True))
