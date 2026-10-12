"""Source-bind generic table and flattened parameter-pool bounds proofs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
PARAM_SOURCE = ROOT / "src/backend/codegen_packed_meta.elisa"
RETURN_SOURCE = ROOT / "src/backend/codegen_env.elisa"
INFERENCE_SOURCE = ROOT / "src/backend/codegen_generic_inference.elisa"
REGISTRY_SOURCE = ROOT / "src/backend/codegen_template_registry.elisa"
VALUE_INFERENCE_SOURCE = ROOT / "src/backend/codegen_generic_array_inference.elisa"
GENERIC_CALL_SOURCE = ROOT / "src/backend/codegen_generic_call.elisa"
POSITIVE = HERE / "backend_generic_slot_table_bounds.elisa"
NEGATIVE = HERE / "backend_generic_slot_table_bounds_rejected.elisa"
POSITIVE_NAMES = {
    "generic_parameter_row_is_readable",
    "generic_return_row_is_readable",
    "generic_instantiation_row_is_readable",
    "generic_parameter_pool_offset_is_bounded",
    "generic_binding_indices_are_bounded",
    "generic_parameter_metadata_index_is_bounded",
    "generic_callable_parameter_offsets_are_bounded",
    "generic_parallel_row_append_preserves_i64_count_alignment",
}
NEGATIVE_NAMES = {
    "false_claim_name_row_implies_declaration_row",
    "false_claim_name_row_implies_parameter_count_row",
    "false_claim_name_row_implies_error_metadata_row",
    "false_claim_one_past_parameter_is_in_pool",
    "false_claim_one_past_type_argument_is_accessible",
    "false_claim_generic_callable_one_past_parameter_is_inside_pool",
    "false_claim_i64_generic_registration_keeps_rows_aligned_without_error_parameter_append",
}

if not __debug__:
    raise SystemExit("run without Python -O")


def strip_elisa_line_comment(line: str) -> str:
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


def normalized_lines(text: str) -> tuple[tuple[int, str], ...]:
    lines = []
    for line in text.splitlines():
        uncommented = strip_elisa_line_comment(line).expandtabs(4)
        if uncommented.strip():
            indent = len(uncommented) - len(uncommented.lstrip())
            lines.append((indent, normalize_code_line(uncommented.lstrip())))
    if not lines:
        return ()
    base_indent = min(indent for indent, _ in lines)
    return tuple((indent - base_indent, code) for indent, code in lines)


def include_targets(text: str) -> list[str]:
    targets = []
    for line in text.splitlines():
        directive = strip_elisa_line_comment(line).strip()
        match = re.fullmatch(r'include\s+"([^"\n]+)"', directive)
        if match:
            targets.append(match.group(1))
    return targets


if normalize_code_line("return index") == normalize_code_line("returnindex"):
    raise SystemExit("source normalizer collapses a token boundary")
if normalize_code_line(strip_elisa_line_comment('include "#literal" # comment')) != 'include "#literal"':
    raise SystemExit("source normalizer strips a hash inside a string literal")
if normalized_lines("if test:\n    return 1\nreturn 2") == normalized_lines("if test:\nreturn 1\nreturn 2"):
    raise SystemExit("source normalizer discards indentation-sensitive structure")
if include_targets('# include "./fake.elisa"\ninclude "./real.elisa" # comment') != ["./real.elisa"]:
    raise SystemExit("include parser accepts a comment as an active directive")


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def exact_steps(source: str, name: str, steps: tuple[tuple[int, str], ...], label: str) -> None:
    lines = normalized_lines(function_section(source, name))
    cursor = 0
    for indent, code in steps:
        expected = (indent, normalize_code_line(code))
        try:
            cursor = lines.index(expected, cursor) + 1
        except ValueError:
            raise SystemExit(f"{label}: missing or reordered source line: {code}") from None


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def model_lines(name: str) -> tuple[tuple[int, str], ...]:
    return normalized_lines(function_section(POSITIVE.read_text(), name))


def rejected_model_lines(name: str) -> tuple[tuple[int, str], ...]:
    return normalized_lines(function_section(NEGATIVE.read_text(), name))


def require_model(name: str, signature: str, requires: tuple[str, ...], ensures: tuple[str, ...], result: str) -> None:
    lines = model_lines(name)
    expected = [(0, normalize_code_line(signature))]
    expected.extend((4, normalize_code_line(line)) for line in requires)
    expected.extend((4, normalize_code_line(line)) for line in ensures)
    expected.append((4, normalize_code_line(result)))
    cursor = 0
    for line in expected:
        try:
            cursor = lines.index(line, cursor) + 1
        except ValueError:
            raise SystemExit(f"proof model {name} changed its source-bound contract: {line[1]}") from None


parameter_text = PARAM_SOURCE.read_text()
return_text = RETURN_SOURCE.read_text()
inference_text = INFERENCE_SOURCE.read_text()
registry_text = REGISTRY_SOURCE.read_text()
value_inference_text = VALUE_INFERENCE_SOURCE.read_text()
generic_call_text = GENERIC_CALL_SOURCE.read_text()

exact_steps(parameter_text, "instantiation_param_type_at", (
    (8, "unmodeled_type() return if slot >= generics.names.count"),
    (8, "unmodeled_type() return if slot >= generics.decls.count"),
    (8, "match generics.decls[slot]:"),
), "parameter type lookup")
exact_steps(return_text, "generic_return_type_at", (
    (8, "unmodeled_type() return if slot >= generics.names.count"),
    (8, "unmodeled_type() return if slot >= generics.param_count.count"),
    (8, "unmodeled_type() return if slot >= generics.decls.count"),
    (8, "unmodeled_type() return if generics.param_count[slot] != type_args.count"),
    (8, "if generics.decls[slot] is Decl.Func(function_name, params, return_type_opt, body, effects, decorators, line):"),
), "return type lookup")
exact_steps(parameter_text, "instantiate_generic_at_with_error_family", (
    (4, "null return if slot >= generics.names.count"),
    (4, "null return if slot >= generics.decls.count"),
    (4, "null return if slot >= generics.param_count.count"),
    (4, "null return if slot >= generics.is_error.count"),
    (4, "null return if slot >= generics.error_params.count"),
    (4, "base: sview = generics.names[slot]"),
    (4, "match generics.decls[slot]:"),
    (12, "instantiation_is_error: bool = generics.is_error[slot]"),
), "generic instantiation")
exact_steps(inference_text, "push_type_bindings", (
    (4, "return 0 if slot >= generics.names.count or slot >= generics.decls.count"),
    (4, "return 0 if slot >= generics.param_start.count or slot >= generics.param_count.count"),
    (4, "pstart: usize = generics.param_start[slot]"),
    (4, "count: usize = generics.param_count[slot]"),
    (4, "return 0 if pstart > generics.params.count"),
    (4, "return 0 if count > generics.params.count - pstart"),
    (4, "for k in 0..<count |structs, generics, pstart, type_args, bound, count|:"),
    (8, "break if k >= type_args.count"),
    (8, "structs.bindings.binding_names <- structs.bindings.binding_names.push(generics.params[pstart + k])"),
    (8, "structs.bindings.binding_types <- structs.bindings.binding_types.push(copied_type(type_args[k]))"),
), "type binding")
exact_steps(inference_text, "type_param_position", (
    (4, "return -1 if slot >= generics.names.count or slot >= generics.decls.count"),
    (4, "return -1 if slot >= generics.param_start.count or slot >= generics.param_count.count"),
    (4, "pstart: usize = generics.param_start[slot]"),
    (4, "count: usize = generics.param_count[slot]"),
    (4, "return -1 if pstart > generics.params.count"),
    (4, "return -1 if count > generics.params.count - pstart"),
    (4, "for k in 0..<count |generics, pstart, name, count|:"),
    (8, "k.i64() return if generics.params[pstart + k] == name"),
), "type parameter lookup")
exact_steps(value_inference_text, "generic_usize_value_position", (
    (4, "return -1 if slot >= generics.param_start.count or slot >= generics.param_count.count"),
    (4, "return -1 if generics.params.count != generics.param_is_usize_value.count"),
    (4, "start: usize = generics.param_start[slot]"),
    (4, "count: usize = generics.param_count[slot]"),
    (4, "return -1 if start > generics.params.count or count > generics.params.count - start"),
    (4, "for offset in 0..<count |generics, start, name, found|:"),
    (8, "index: usize = start + offset"),
    (8, "if generics.params[index] == name and generics.param_is_usize_value[index]:"),
), "generic usize value parameter lookup")
exact_steps(generic_call_text, "generic_call_function_row_matches", (
    (4, "param_count: usize = structs.function_types.fn_pool_param_count[fn_slot]"),
    (4, "false return if fns.param_count[row_index] != param_count"),
    (4, "expected_start: usize = structs.function_types.fn_pool_param_start[fn_slot]"),
    (4, "row_start: usize = fns.param_start[row_index]"),
    (4, "false return if expected_start > structs.function_types.fn_pool_params.count"),
    (4, "false return if param_count > structs.function_types.fn_pool_params.count - expected_start"),
    (4, "false return if row_start > fns.param_types.count"),
    (4, "false return if param_count > fns.param_types.count - row_start"),
    (4, "for param_offset in 0..<param_count |expected_start, row_start, structs, fns|:"),
    (8, "false return if not value_type_identity_equal(fns.param_types[row_start + param_offset], structs.function_types.fn_pool_params[expected_start + param_offset])"),
), "generic callable signature comparison")

row_models = {
    "generic_parameter_row_is_readable": (
        "def generic_parameter_row_is_readable(slot: usize, name_rows: usize, declaration_rows: usize) -> bool:",
        ("requires slot < name_rows and slot < declaration_rows",),
        ("ensure result == (slot < name_rows and slot < declaration_rows)",),
        "return slot < name_rows and slot < declaration_rows",
        parameter_text,
        "instantiation_param_type_at",
        (("name_rows", "generics.names.count"), ("declaration_rows", "generics.decls.count")),
    ),
    "generic_return_row_is_readable": (
        "def generic_return_row_is_readable(slot: usize, name_rows: usize, declaration_rows: usize, parameter_count_rows: usize) -> bool:",
        ("requires slot < name_rows and slot < declaration_rows and slot < parameter_count_rows",),
        ("ensure result == (slot < name_rows and slot < declaration_rows and slot < parameter_count_rows)",),
        "return slot < name_rows and slot < declaration_rows and slot < parameter_count_rows",
        return_text,
        "generic_return_type_at",
        (("name_rows", "generics.names.count"), ("declaration_rows", "generics.decls.count"),
         ("parameter_count_rows", "generics.param_count.count")),
    ),
    "generic_instantiation_row_is_readable": (
        "def generic_instantiation_row_is_readable(slot: usize, name_rows: usize, declaration_rows: usize, parameter_count_rows: usize, error_rows: usize, error_parameter_rows: usize) -> bool:",
        ("requires slot < name_rows and slot < declaration_rows and slot < parameter_count_rows and slot < error_rows and slot < error_parameter_rows",),
        ("ensure result == (slot < name_rows and slot < declaration_rows and slot < parameter_count_rows and slot < error_rows and slot < error_parameter_rows)",),
        "return slot < name_rows and slot < declaration_rows and slot < parameter_count_rows and slot < error_rows and slot < error_parameter_rows",
        parameter_text,
        "instantiate_generic_at_with_error_family",
        (("name_rows", "generics.names.count"), ("declaration_rows", "generics.decls.count"),
         ("parameter_count_rows", "generics.param_count.count"), ("error_rows", "generics.is_error.count"),
         ("error_parameter_rows", "generics.error_params.count")),
    ),
}

for name, (signature, requires, ensures, result, source, source_function, bindings) in row_models.items():
    require_model(name, signature, requires, ensures, result)
    source_function_lines = normalized_lines(function_section(source, source_function))
    model_function_lines = model_lines(name)
    model_precondition = next((line for _, line in model_function_lines if line.startswith("requires ")), "")
    model_postconditions = " ".join(line for _, line in model_function_lines if line.startswith(("ensure ", "return ")))
    for model_field, source_field in bindings:
        if f"slot < {model_field}" not in model_precondition or f"slot < {model_field}" not in model_postconditions:
            raise SystemExit(f"{name}: model row {model_field} is not guarded in its requires and result")
        source_guard = normalize_code_line(
            f"unmodeled_type() return if slot >= {source_field}" if name != "generic_instantiation_row_is_readable"
            else f"null return if slot >= {source_field}"
        )
        if not any(code == source_guard for _, code in source_function_lines):
            raise SystemExit(f"{name}: model row {model_field} is not bound to source field {source_field}")

require_model(
    "generic_parameter_pool_offset_is_bounded",
    "def generic_parameter_pool_offset_is_bounded(total: usize, start: usize, count: usize, offset: usize) -> bool:",
    ("requires start <= total and count <= total - start and offset < count",),
    ("ensure result == true",),
    "return start + offset >= start and start + offset < total",
)
pool_model_lines = model_lines("generic_parameter_pool_offset_is_bounded")
pool_requires = next((line for _, line in pool_model_lines if line.startswith("requires ")), "")
pool_return = next((line for _, line in pool_model_lines if line.startswith("return ")), "")
pool_signature = next((line for _, line in pool_model_lines if line.startswith("def ")), "")
pool_formals = re.fullmatch(
    r"def generic_parameter_pool_offset_is_bounded\((.*)\) -> bool:", pool_signature
)
if pool_formals is None:
    raise SystemExit("parameter pool model signature could not be parsed")
formal_names = tuple(part.strip().split(":", 1)[0] for part in pool_formals.group(1).split(","))
if formal_names != ("total", "start", "count", "offset"):
    raise SystemExit("parameter pool model arguments changed")

# The precondition establishes the source span's safety; the result establishes
# that the in-span loop offset produces an index below the pool length. Keep the
# correspondence explicit so a renamed or disconnected model variable cannot
# silently preserve a proved but irrelevant arithmetic lemma.
pool_model_relations = {
    "total": (("start <= total", "count <= total - start"), ("start + offset < total",)),
    "start": (("start <= total", "count <= total - start"), ("start + offset >= start",)),
    "count": (("count <= total - start", "offset < count"), ()),
    "offset": (("offset < count",), ("start + offset >= start", "start + offset < total")),
}
for model_arg, (required_relations, result_relations) in pool_model_relations.items():
    if any(relation not in pool_requires for relation in required_relations):
        raise SystemExit(f"parameter pool model argument {model_arg} is disconnected from its precondition")
    if any(relation not in pool_return for relation in result_relations):
        raise SystemExit(f"parameter pool model argument {model_arg} is disconnected from its result")

pool_source_lines = normalized_lines(function_section(inference_text, "push_type_bindings"))
pool_source_map = {
    "total": (
        "return 0 if pstart > generics.params.count",
        "return 0 if count > generics.params.count - pstart",
    ),
    "start": (
        "pstart: usize = generics.param_start[slot]",
        "return 0 if pstart > generics.params.count",
        "return 0 if count > generics.params.count - pstart",
    ),
    "count": (
        "count: usize = generics.param_count[slot]",
        "return 0 if count > generics.params.count - pstart",
        "for k in 0..<count |structs, generics, pstart, type_args, bound, count|:",
    ),
    "offset": (
        "for k in 0..<count |structs, generics, pstart, type_args, bound, count|:",
        "break if k >= type_args.count",
        "structs.bindings.binding_names <- structs.bindings.binding_names.push(generics.params[pstart + k])",
        "structs.bindings.binding_types <- structs.bindings.binding_types.push(copied_type(type_args[k]))",
    ),
}
for model_arg, expected_lines in pool_source_map.items():
    positions = []
    for expected in expected_lines:
        normalized = normalize_code_line(expected)
        try:
            position = next(index for index, (_, code) in enumerate(pool_source_lines) if code == normalized)
        except StopIteration:
            raise SystemExit(f"parameter pool model argument {model_arg} is not mapped to source: {expected}") from None
        if positions and position <= positions[-1]:
            raise SystemExit(f"parameter pool source mapping is out of order for {model_arg}: {expected}")
        positions.append(position)
if "pstart + count > generics.params.count" in "\n".join(code for _, code in pool_source_lines):
    raise SystemExit("parameter pool source reintroduced overflow-prone end-index arithmetic")

require_model(
    "generic_binding_indices_are_bounded",
    "def generic_binding_indices_are_bounded(total: usize, start: usize, count: usize, offset: usize, argument_count: usize) -> bool:",
    (
        "requires start <= total and count <= total - start",
        "requires offset < count and offset < argument_count",
    ),
    ("ensure result == true",),
    "return start + offset < total and offset < argument_count",
)
binding_source_map = {
    "total": (
        "return 0 if pstart > generics.params.count",
        "return 0 if count > generics.params.count - pstart",
    ),
    "start": (
        "pstart: usize = generics.param_start[slot]",
        "return 0 if pstart > generics.params.count",
        "return 0 if count > generics.params.count - pstart",
        "structs.bindings.binding_names <- structs.bindings.binding_names.push(generics.params[pstart + k])",
    ),
    "count": (
        "count: usize = generics.param_count[slot]",
        "return 0 if count > generics.params.count - pstart",
        "for k in 0..<count |structs, generics, pstart, type_args, bound, count|:",
    ),
    "offset": (
        "for k in 0..<count |structs, generics, pstart, type_args, bound, count|:",
        "break if k >= type_args.count",
        "structs.bindings.binding_names <- structs.bindings.binding_names.push(generics.params[pstart + k])",
        "structs.bindings.binding_types <- structs.bindings.binding_types.push(copied_type(type_args[k]))",
    ),
    "argument_count": (
        "break if k >= type_args.count",
        "structs.bindings.binding_types <- structs.bindings.binding_types.push(copied_type(type_args[k]))",
    ),
}
binding_model_lines = model_lines("generic_binding_indices_are_bounded")
binding_requires = " ".join(line for _, line in binding_model_lines if line.startswith("requires "))
binding_return = next((line for _, line in binding_model_lines if line.startswith("return ")), "")
for model_arg, expected_lines in binding_source_map.items():
    if model_arg not in binding_requires and model_arg not in binding_return:
        raise SystemExit(f"generic binding model argument {model_arg} is unused")
    positions = []
    for expected in expected_lines:
        normalized = normalize_code_line(expected)
        try:
            position = next(index for index, (_, code) in enumerate(pool_source_lines) if code == normalized)
        except StopIteration:
            raise SystemExit(f"generic binding model argument {model_arg} is not mapped to source: {expected}") from None
        if positions and position <= positions[-1]:
            raise SystemExit(f"generic binding source mapping is out of order for {model_arg}: {expected}")
        positions.append(position)

require_model(
    "generic_parameter_metadata_index_is_bounded",
    "def generic_parameter_metadata_index_is_bounded(names_total: usize, flags_total: usize, start: usize, count: usize, offset: usize) -> bool:",
    (
        "requires names_total == flags_total",
        "requires start <= names_total and count <= names_total - start and offset < count",
    ),
    ("ensure result == true",),
    "return start + offset < names_total and start + offset < flags_total",
)
metadata_model_lines = model_lines("generic_parameter_metadata_index_is_bounded")
metadata_requires = " ".join(line for _, line in metadata_model_lines if line.startswith("requires "))
metadata_return = next((line for _, line in metadata_model_lines if line.startswith("return ")), "")
metadata_source_lines = normalized_lines(function_section(value_inference_text, "generic_usize_value_position"))
metadata_source_map = {
    "names_total": (
        "return -1 if generics.params.count != generics.param_is_usize_value.count",
        "return -1 if start > generics.params.count or count > generics.params.count - start",
    ),
    "flags_total": (
        "return -1 if generics.params.count != generics.param_is_usize_value.count",
        "if generics.params[index] == name and generics.param_is_usize_value[index]:",
    ),
    "start": (
        "start: usize = generics.param_start[slot]",
        "return -1 if start > generics.params.count or count > generics.params.count - start",
        "index: usize = start + offset",
    ),
    "count": (
        "count: usize = generics.param_count[slot]",
        "return -1 if start > generics.params.count or count > generics.params.count - start",
        "for offset in 0..<count |generics, start, name, found|:",
    ),
    "offset": ("for offset in 0..<count |generics, start, name, found|:", "index: usize = start + offset", "if generics.params[index] == name and generics.param_is_usize_value[index]:"),
}
for model_arg, expected_source in metadata_source_map.items():
    if model_arg not in metadata_requires and model_arg not in metadata_return:
        raise SystemExit(f"generic metadata model argument {model_arg} is unused")
    cursor = -1
    for expected in expected_source:
        normalized = normalize_code_line(expected)
        try:
            cursor = next(index for index, (_, code) in enumerate(metadata_source_lines) if code == normalized and index > cursor)
        except StopIteration:
            raise SystemExit(f"generic metadata model argument {model_arg} is not source-bound at: {expected}") from None

require_model(
    "generic_callable_parameter_offsets_are_bounded",
    "def generic_callable_parameter_offsets_are_bounded(expected_total: usize, expected_start: usize, row_total: usize, row_start: usize, parameter_count: usize, offset: usize) -> bool:",
    (
        "requires expected_start <= expected_total and parameter_count <= expected_total - expected_start",
        "requires row_start <= row_total and parameter_count <= row_total - row_start",
        "requires offset < parameter_count",
    ),
    ("ensure result == true",),
    "return expected_start + offset < expected_total and row_start + offset < row_total",
)
rejected_callable_offset_model = rejected_model_lines("false_claim_generic_callable_one_past_parameter_is_inside_pool")
expected_rejected_callable_offset_model = (
    (0, normalize_code_line("def false_claim_generic_callable_one_past_parameter_is_inside_pool(total: usize, start: usize, count: usize, offset: usize) -> bool:")),
    (4, normalize_code_line("requires start <= total and count <= total - start and offset == count")),
    (4, normalize_code_line("ensure result == true")),
    (4, normalize_code_line("return offset < count and start + offset < total")),
)
if rejected_callable_offset_model != expected_rejected_callable_offset_model:
    raise SystemExit("negative callable parameter model no longer tests one-past-end access")
call_model_lines = model_lines("generic_callable_parameter_offsets_are_bounded")
call_requires = " ".join(line for _, line in call_model_lines if line.startswith("requires "))
call_return = next((line for _, line in call_model_lines if line.startswith("return ")), "")
call_source_lines = normalized_lines(function_section(generic_call_text, "generic_call_function_row_matches"))
call_source_map = {
    "expected_total": ("false return if expected_start > structs.function_types.fn_pool_params.count", "false return if param_count > structs.function_types.fn_pool_params.count - expected_start"),
    "expected_start": ("expected_start: usize = structs.function_types.fn_pool_param_start[fn_slot]", "false return if expected_start > structs.function_types.fn_pool_params.count", "false return if param_count > structs.function_types.fn_pool_params.count - expected_start", "false return if not value_type_identity_equal(fns.param_types[row_start + param_offset], structs.function_types.fn_pool_params[expected_start + param_offset])"),
    "row_total": ("false return if row_start > fns.param_types.count", "false return if param_count > fns.param_types.count - row_start"),
    "row_start": ("row_start: usize = fns.param_start[row_index]", "false return if row_start > fns.param_types.count", "false return if param_count > fns.param_types.count - row_start", "false return if not value_type_identity_equal(fns.param_types[row_start + param_offset], structs.function_types.fn_pool_params[expected_start + param_offset])"),
    "parameter_count": ("param_count: usize = structs.function_types.fn_pool_param_count[fn_slot]", "false return if fns.param_count[row_index] != param_count", "for param_offset in 0..<param_count |expected_start, row_start, structs, fns|:"),
    "offset": ("for param_offset in 0..<param_count |expected_start, row_start, structs, fns|:", "false return if not value_type_identity_equal(fns.param_types[row_start + param_offset], structs.function_types.fn_pool_params[expected_start + param_offset])"),
}
for model_arg, expected_source in call_source_map.items():
    if model_arg not in call_requires and model_arg not in call_return:
        raise SystemExit(f"generic callable parameter model argument {model_arg} is unused")
    cursor = -1
    for expected in expected_source:
        normalized = normalize_code_line(expected)
        try:
            cursor = next(index for index, (_, code) in enumerate(call_source_lines) if code == normalized and index > cursor)
        except StopIteration:
            raise SystemExit(f"generic callable parameter model argument {model_arg} is not source-bound at: {expected}") from None

row_fields = ("names", "decls", "param_start", "param_count", "is_error", "error_params", "owners")
row_push_lines = {
    "names": "generics.names <- generics.names.push(function_name)",
    "decls": "generics.decls <- generics.decls.push(file.generic_func_decls[generic_index])",
    "param_start": "generics.param_start <- generics.param_start.push(start)",
    "param_count": "generics.param_count <- generics.param_count.push(added)",
    "is_error": "generics.is_error <- generics.is_error.push(line_is_error_returning(file.error_set_func_lines, line))",
    "error_params": "generics.error_params <- generics.error_params.push(error_param)",
    "owners": "generics.owners <- generics.owners.push(file.generic_func_decl_owners[generic_index])",
}
clone_push_lines = {
    **row_push_lines,
    "decls": "generics.decls <- generics.decls.push(declaration)",
    "is_error": "generics.is_error <- generics.is_error.push(line_is_error_returning(file.error_set_func_lines, source_line))",
    "owners": 'generics.owners <- generics.owners.push("")',
}
registration_steps = (
    (12, 'continue if added == 0 and error_param == ""'),
    *((12, row_push_lines[field]) for field in row_fields[:1]),
    (12, "name_chain_extend(generics.name_buckets, generics.name_tails, generics.name_next, generics.names)"),
    *((12, row_push_lines[field]) for field in row_fields[1:]),
)
clone_steps = (
    (16, "continue if not clone or not decl_line_is_generic(file, source_line)"),
    (16, 'continue if added == 0 and error_param == ""'),
    (16, clone_push_lines["names"]),
    (16, "name_chain_extend(generics.name_buckets, generics.name_tails, generics.name_next, generics.names)"),
    *((16, clone_push_lines[field]) for field in row_fields[1:]),
)
exact_steps(registry_text, "register_generics", registration_steps, "generic declaration registration")
exact_steps(registry_text, "register_effect_generic_clones", clone_steps, "generic clone registration")
for field in row_fields:
    occurrences = 0
    for backend_file in (ROOT / "src/backend").glob("*.elisa"):
        occurrences += len(re.findall(
            rf"(?m)^\s*generics\.{re.escape(field)}\s*<-\s*generics\.{re.escape(field)}\.push\(",
            backend_file.read_text(),
        ))
    if occurrences != 2:
        raise SystemExit(f"expected exactly two backend append sites for GenericTable.{field}; found {occurrences}")

require_model(
    "generic_parallel_row_append_preserves_i64_count_alignment",
    "def generic_parallel_row_append_preserves_i64_count_alignment(names: i64, declarations: i64, parameter_starts: i64, parameter_counts: i64, error_flags: i64, error_parameters: i64, owners: i64) -> bool:",
    (
        "requires names >= 0 and names < 9223372036854775807",
        "requires names == declarations and names == parameter_starts and names == parameter_counts",
        "requires names == error_flags and names == error_parameters and names == owners",
    ),
    ("ensure result == true",),
    "return names + 1 == declarations + 1 and names + 1 == parameter_starts + 1 and names + 1 == parameter_counts + 1 and names + 1 == error_flags + 1 and names + 1 == error_parameters + 1 and names + 1 == owners + 1",
)
rejected_row_model = rejected_model_lines("false_claim_i64_generic_registration_keeps_rows_aligned_without_error_parameter_append")
expected_rejected_row_model = (
    (0, normalize_code_line("def false_claim_i64_generic_registration_keeps_rows_aligned_without_error_parameter_append(names: i64, declarations: i64, parameter_starts: i64, parameter_counts: i64, error_flags: i64, error_parameters: i64, owners: i64) -> bool:")),
    (4, normalize_code_line("requires names >= 0 and names < 9223372036854775807")),
    (4, normalize_code_line("requires names == declarations and names == parameter_starts and names == parameter_counts")),
    (4, normalize_code_line("requires names == error_flags and names == error_parameters and names == owners")),
    (4, normalize_code_line("ensure result == true")),
    (4, normalize_code_line("return names + 1 == declarations + 1 and names + 1 == parameter_starts + 1 and names + 1 == parameter_counts + 1 and names + 1 == error_flags + 1 and names + 1 == error_parameters and names + 1 == owners + 1")),
)
if rejected_row_model != expected_rejected_row_model:
    raise SystemExit("negative generic row model no longer isolates the omitted error-parameter append")
rejected_type_arg_model = rejected_model_lines("false_claim_one_past_type_argument_is_accessible")
expected_rejected_type_arg_model = (
    (0, normalize_code_line("def false_claim_one_past_type_argument_is_accessible(argument_count: usize, offset: usize) -> bool:")),
    (4, normalize_code_line("requires offset == argument_count")),
    (4, normalize_code_line("ensure result == true")),
    (4, normalize_code_line("return offset < argument_count")),
)
if rejected_type_arg_model != expected_rejected_type_arg_model:
    raise SystemExit("negative type argument model no longer tests one-past-end access")

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("generic slot proof declaration inventory changed")
if include_targets(NEGATIVE.read_text()).count("./backend_generic_slot_table_bounds.elisa") != 1:
    raise SystemExit("negative controls must include the admitted proof model exactly once")

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("generic slot table proof requires a strict proof build")
stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    PARAM_SOURCE,
    RETURN_SOURCE,
    INFERENCE_SOURCE,
    REGISTRY_SOURCE,
    VALUE_INFERENCE_SOURCE,
    GENERIC_CALL_SOURCE,
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
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
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_NAMES) + len(NEGATIVE_NAMES)
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "generic lookup guards dominate every parallel row and parameter-pool read",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
