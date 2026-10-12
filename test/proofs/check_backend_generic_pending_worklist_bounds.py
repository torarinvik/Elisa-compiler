"""Source-bind and replay the generic pending-instantiation bounds proofs."""
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
INSTANTIATE_SOURCE = ROOT / "src/backend/codegen_instantiate.elisa"
DEBUG_SOURCE = ROOT / "src/backend/codegen_debug.elisa"
REGISTRATION_SOURCE = ROOT / "src/backend/codegen_packed_meta.elisa"
INFERENCE_SOURCE = ROOT / "src/backend/codegen_generic_inference.elisa"
POSITIVE = HERE / "backend_generic_pending_worklist_bounds.elisa"
NEGATIVE = HERE / "backend_generic_pending_worklist_bounds_rejected.elisa"
POSITIVE_NAMES = {
    "generic_pending_parallel_append_preserves_i64_row_alignment",
    "generic_pending_worklist_row_is_readable",
    "generic_pending_template_slot_is_readable",
    "generic_pending_argument_offset_is_bounded",
    "generic_pending_template_parameter_offset_is_bounded",
}
NEGATIVE_NAMES = {
    "false_claim_pending_rows_share_base_extent",
    "false_claim_one_past_pending_argument_is_accessible",
    "false_claim_pending_append_keeps_rows_aligned_without_handle",
}


def strip_comment(line: str) -> str:
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


def normalize(code: str) -> str:
    return " ".join(strip_comment(code).split())


def function_section(source: str, name: str) -> str:
    match = re.search(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source)
    if match is None or len(re.findall(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source)) != 1:
        raise SystemExit(f"expected exactly one declaration named {name}")
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def normalized_lines(source: str) -> tuple[tuple[int, str], ...]:
    rows = []
    for raw in source.splitlines():
        line = strip_comment(raw).expandtabs(4)
        if line.strip():
            rows.append((len(line) - len(line.lstrip()), normalize(line.lstrip())))
    if not rows:
        return ()
    base = min(indent for indent, _ in rows)
    return tuple((indent - base, code) for indent, code in rows)


def exact_steps(source: str, name: str, steps: tuple[tuple[int, str], ...], label: str) -> None:
    rows = normalized_lines(function_section(source, name))
    cursor = 0
    for indent, code in steps:
        expected = (indent, normalize(code))
        try:
            cursor = rows.index(expected, cursor) + 1
        except ValueError:
            raise SystemExit(f"{label}: missing or reordered source line: {code}") from None


def first_read_follows_guard(source: str, name: str, guard: str, read: str) -> bool:
    rows = normalized_lines(function_section(source, name))
    normalized_guard = normalize(guard)
    normalized_read = normalize(read)
    guard_positions = [index for index, (_, code) in enumerate(rows) if code == normalized_guard]
    read_positions = [index for index, (_, code) in enumerate(rows) if normalized_read in code]
    return len(guard_positions) == 1 and bool(read_positions) and guard_positions[0] < read_positions[0]


def inject_read_before_guard(source: str, name: str, guard: str, read: str) -> str:
    section = function_section(source, name)
    lines = section.splitlines(keepends=True)
    normalized_guard = normalize(guard)
    positions = [
        index
        for index, line in enumerate(lines)
        if normalize(line.rstrip("\r\n")) == normalized_guard
    ]
    if len(positions) != 1:
        raise SystemExit(f"mutation-control guard is not unique: {guard}")
    position = positions[0]
    indent = len(lines[position]) - len(lines[position].lstrip())
    line_ending = "\r\n" if lines[position].endswith("\r\n") else "\n"
    lines.insert(position, " " * indent + read + line_ending)
    return source[:source.index(section)] + "".join(lines) + source[source.index(section) + len(section):]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def require_model(name: str, signature: str, contracts: tuple[str, ...]) -> None:
    rows = normalized_lines(function_section(POSITIVE.read_text(), name))
    expected = [(0, normalize(signature))]
    expected.extend((4, normalize(line)) for line in contracts)
    cursor = 0
    for item in expected:
        try:
            cursor = rows.index(item, cursor) + 1
        except ValueError:
            raise SystemExit(f"proof model {name} changed its source-bound contract: {item[1]}") from None


def model_contract(name: str) -> tuple[str, str]:
    rows = normalized_lines(function_section(POSITIVE.read_text(), name))
    requires = " ".join(code for _, code in rows if code.startswith("requires "))
    result = " ".join(code for _, code in rows if code.startswith("return "))
    return requires, result


def require_negative_model(name: str, expected: tuple[str, ...]) -> None:
    rows = normalized_lines(function_section(NEGATIVE.read_text(), name))
    wanted = [(0, normalize(expected[0]))]
    wanted.extend((4, normalize(line)) for line in expected[1:])
    cursor = 0
    for item in wanted:
        try:
            cursor = rows.index(item, cursor) + 1
        except ValueError:
            raise SystemExit(f"negative proof model {name} changed: {item[1]}") from None


if not __debug__:
    raise SystemExit("run without Python -O")

instantiate_text = INSTANTIATE_SOURCE.read_text()
debug_text = DEBUG_SOURCE.read_text()
registration_text = REGISTRATION_SOURCE.read_text()
inference_text = INFERENCE_SOURCE.read_text()

exact_steps(instantiate_text, "emit_instantiation_body", (
    (8, "return false if index >= generics.pending_bases.count"),
    (8, "return false if index >= generics.pending_handles.count"),
    (8, "return false if index >= generics.pending_slots.count"),
    (8, "return false if index >= generics.pending_arg_start.count"),
    (8, "return false if index >= generics.pending_arg_count.count"),
    (8, "return false if index >= generics.pending_inst_rows.count"),
    (8, "base: sview = generics.pending_bases[index]"),
    (8, "handle: LLVMValueRef = generics.pending_handles[index]"),
    (8, "slot: usize = generics.pending_slots[index]"),
    (8, "return false if slot >= generics.names.count"),
    (8, "return false if slot >= generics.decls.count"),
    (8, "return false if slot >= generics.param_start.count"),
    (8, "return false if slot >= generics.param_count.count"),
    (8, "return false if slot >= generics.is_error.count"),
    (8, "arg_start: usize = generics.pending_arg_start[index]"),
    (8, "arg_count: usize = generics.pending_arg_count[index]"),
    (8, "return false if arg_start > generics.pending_args.count"),
    (8, "return false if arg_count > generics.pending_args.count - arg_start"),
    (8, "slot_param_start: usize = generics.param_start[slot]"),
    (8, "slot_param_count: usize = generics.param_count[slot]"),
    (8, "return false if slot_param_start > generics.params.count"),
    (8, "return false if slot_param_count > generics.params.count - slot_param_start"),
    (8, "for offset in 0..<arg_count |type_args, generics, arg_start|:"),
    (12, "type_args.push(copied_type(generics.pending_args[arg_start + offset]))"),
    (8, 'pending_error_family: sview = generics.pending_error_families[index] if index < generics.pending_error_families.count else ""'),
), "generic instantiation worklist")
exact_steps(debug_text, "emit_module_bodies", (
    (16, "while drained < generics.pending_bases.count |drained, generics, fns, structs, runtime, m, ctx, builder, emitted_count, dangling, module_has_main, force_program|:"),
    (20, "else:"),
    (24, "if drained < generics.pending_handles.count:"),
    (28, "declined_handle: LLVMValueRef = generics.pending_handles[drained]"),
    (28, "strip_function_body(declined_handle)"),
    (28, "note_dangling_decline(generics.pending_bases[drained], declined_handle, module_has_main, dangling)"),
    (24, "record_declined_function(generics.pending_bases[drained], m, ctx)"),
    (20, "drained <- drained + 1"),
), "generic worklist failure path")
exact_steps(registration_text, "instantiate_generic_at_with_error_family", (
    (12, "pending_arg_start: usize = generics.pending_args.count"),
    (12, "for argument in type_args |generics|:"),
    (16, "generics.pending_args <- generics.pending_args.push(copied_type(argument))"),
    (12, "generics.pending_bases <- generics.pending_bases.push(base)"),
    (12, "generics.pending_arg_start <- generics.pending_arg_start.push(pending_arg_start)"),
    (12, "generics.pending_arg_count <- generics.pending_arg_count.push(type_args.count)"),
    (12, "generics.pending_handles <- generics.pending_handles.push(handle)"),
    (12, "generics.pending_inst_rows <- generics.pending_inst_rows.push(instantiation_row)"),
    (12, "generics.pending_slots <- generics.pending_slots.push(slot)"),
    (12, "generics.pending_error_families <- generics.pending_error_families.push(error_family)"),
    (12, "return handle"),
), "pending instantiation registration")
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
), "generic template parameter pool")

first_read_guards = (
    ("return false if index >= generics.pending_bases.count", "generics.pending_bases[index]"),
    ("return false if index >= generics.pending_handles.count", "generics.pending_handles[index]"),
    ("return false if index >= generics.pending_slots.count", "generics.pending_slots[index]"),
    ("return false if index >= generics.pending_arg_start.count", "generics.pending_arg_start[index]"),
    ("return false if index >= generics.pending_arg_count.count", "generics.pending_arg_count[index]"),
    ("return false if index >= generics.pending_inst_rows.count", "generics.pending_inst_rows[index]"),
    ("return false if slot >= generics.decls.count", "generics.decls[slot]"),
    ("return false if slot >= generics.param_start.count", "generics.param_start[slot]"),
    ("return false if slot >= generics.param_count.count", "generics.param_count[slot]"),
    ("return false if slot >= generics.is_error.count", "generics.is_error[slot]"),
    ("return false if arg_start > generics.pending_args.count", "generics.pending_args[arg_start + offset]"),
    ("return false if arg_count > generics.pending_args.count - arg_start", "generics.pending_args[arg_start + offset]"),
)
for guard, read in first_read_guards:
    if not first_read_follows_guard(instantiate_text, "emit_instantiation_body", guard, read):
        raise SystemExit(f"first indexed read is not dominated by its matching guard: {read}")
    mutated = inject_read_before_guard(instantiate_text, "emit_instantiation_body", guard, read)
    if first_read_follows_guard(mutated, "emit_instantiation_body", guard, read):
        raise SystemExit(f"source-order mutation control failed to detect an early read: {read}")

require_model(
    "generic_pending_parallel_append_preserves_i64_row_alignment",
    "def generic_pending_parallel_append_preserves_i64_row_alignment(bases: i64, argument_starts: i64, argument_counts: i64, handles: i64, instantiation_rows: i64, slots: i64, error_families: i64) -> bool:",
    (
        "requires bases >= 0 and bases < 9223372036854775807",
        "requires bases == argument_starts and bases == argument_counts and bases == handles",
        "requires bases == instantiation_rows and bases == slots and bases == error_families",
        "ensure result == true",
        "return bases + 1 == argument_starts + 1 and bases + 1 == argument_counts + 1 and bases + 1 == handles + 1 and bases + 1 == instantiation_rows + 1 and bases + 1 == slots + 1 and bases + 1 == error_families + 1",
    ),
)
worklist_requires, worklist_return = model_contract("generic_pending_worklist_row_is_readable")
worklist_source_lines = {code for _, code in normalized_lines(function_section(instantiate_text, "emit_instantiation_body"))}
for model_field, source_field in (
    ("bases", "generics.pending_bases.count"),
    ("handles", "generics.pending_handles.count"),
    ("slots", "generics.pending_slots.count"),
    ("arg_starts", "generics.pending_arg_start.count"),
    ("arg_counts", "generics.pending_arg_count.count"),
    ("inst_rows", "generics.pending_inst_rows.count"),
):
    relation = f"index < {model_field}"
    guard = normalize(f"return false if index >= {source_field}")
    if relation not in worklist_requires or relation not in worklist_return or guard not in worklist_source_lines:
        raise SystemExit(f"pending row model field {model_field} is not bound to {source_field}")
require_model(
    "generic_pending_worklist_row_is_readable",
    "def generic_pending_worklist_row_is_readable(index: usize, bases: usize, handles: usize, slots: usize, arg_starts: usize, arg_counts: usize, inst_rows: usize) -> bool:",
    (
        "requires index < bases and index < handles and index < slots and index < arg_starts and index < arg_counts and index < inst_rows",
        "ensure result == (index < bases and index < handles and index < slots and index < arg_starts and index < arg_counts and index < inst_rows)",
        "return index < bases and index < handles and index < slots and index < arg_starts and index < arg_counts and index < inst_rows",
    ),
)
slot_requires, slot_return = model_contract("generic_pending_template_slot_is_readable")
for model_field, source_field in (
    ("names", "generics.names.count"),
    ("declarations", "generics.decls.count"),
    ("parameter_starts", "generics.param_start.count"),
    ("parameter_counts", "generics.param_count.count"),
    ("error_flags", "generics.is_error.count"),
):
    relation = f"slot < {model_field}"
    guard = normalize(f"return false if slot >= {source_field}")
    if relation not in slot_requires or relation not in slot_return or guard not in worklist_source_lines:
        raise SystemExit(f"template slot model field {model_field} is not bound to {source_field}")
require_model(
    "generic_pending_template_slot_is_readable",
    "def generic_pending_template_slot_is_readable(slot: usize, names: usize, declarations: usize, parameter_starts: usize, parameter_counts: usize, error_flags: usize) -> bool:",
    (
        "requires slot < names and slot < declarations and slot < parameter_starts and slot < parameter_counts and slot < error_flags",
        "ensure result == (slot < names and slot < declarations and slot < parameter_starts and slot < parameter_counts and slot < error_flags)",
        "return slot < names and slot < declarations and slot < parameter_starts and slot < parameter_counts and slot < error_flags",
    ),
)
offset_requires, offset_return = model_contract("generic_pending_argument_offset_is_bounded")
offset_source_lines = {code for _, code in normalized_lines(function_section(instantiate_text, "emit_instantiation_body"))}
offset_bindings = {
    "total": ("start <= total", "count <= total - start", "start + offset < total", "return false if arg_count > generics.pending_args.count - arg_start"),
    "start": ("start <= total", "count <= total - start", "start + offset < total", "arg_start: usize = generics.pending_arg_start[index]"),
    "count": ("count <= total - start", "offset < count", "arg_count: usize = generics.pending_arg_count[index]", "for offset in 0..<arg_count |type_args, generics, arg_start|:"),
    "offset": ("offset < count", "start + offset < total", "for offset in 0..<arg_count |type_args, generics, arg_start|:", "type_args.push(copied_type(generics.pending_args[arg_start + offset]))"),
}
source_binding_lines = {
    "return false if arg_count > generics.pending_args.count - arg_start": {"total"},
    "arg_start: usize = generics.pending_arg_start[index]": {"start"},
    "arg_count: usize = generics.pending_arg_count[index]": {"count"},
    "for offset in 0..<arg_count |type_args, generics, arg_start|:": {"count", "offset"},
    "type_args.push(copied_type(generics.pending_args[arg_start + offset]))": {"offset"},
}
for model_arg, relations in offset_bindings.items():
    for relation in relations:
        if relation in source_binding_lines:
            if normalize(relation) not in offset_source_lines or model_arg not in source_binding_lines[relation]:
                raise SystemExit(f"pending argument offset model argument {model_arg} is not source-bound at {relation}")
        elif relation not in offset_requires and relation not in offset_return:
            raise SystemExit(f"pending argument offset model argument {model_arg} is disconnected")

append_requires, append_return = model_contract("generic_pending_parallel_append_preserves_i64_row_alignment")
registration_lines = {code for _, code in normalized_lines(function_section(registration_text, "instantiate_generic_at_with_error_family"))}
for model_arg, source_line in {
    "bases": "generics.pending_bases <- generics.pending_bases.push(base)",
    "argument_starts": "generics.pending_arg_start <- generics.pending_arg_start.push(pending_arg_start)",
    "argument_counts": "generics.pending_arg_count <- generics.pending_arg_count.push(type_args.count)",
    "handles": "generics.pending_handles <- generics.pending_handles.push(handle)",
    "instantiation_rows": "generics.pending_inst_rows <- generics.pending_inst_rows.push(instantiation_row)",
    "slots": "generics.pending_slots <- generics.pending_slots.push(slot)",
    "error_families": "generics.pending_error_families <- generics.pending_error_families.push(error_family)",
}.items():
    if model_arg not in append_requires or f"{model_arg} + 1" not in append_return or normalize(source_line) not in registration_lines:
        raise SystemExit(f"pending append model field {model_arg} is not bound to its append")

template_offset_requires, template_offset_return = model_contract("generic_pending_template_parameter_offset_is_bounded")
template_source_lines = {
    code for _, code in normalized_lines(function_section(instantiate_text, "emit_instantiation_body"))
}
template_source_lines.update(code for _, code in normalized_lines(function_section(inference_text, "push_type_bindings")))
template_offset_bindings = {
    "total": (
        "start <= total", "count <= total - start", "start + offset < total",
        "return false if slot_param_start > generics.params.count",
        "return false if slot_param_count > generics.params.count - slot_param_start",
        "return 0 if pstart > generics.params.count",
        "return 0 if count > generics.params.count - pstart",
    ),
    "start": (
        "start <= total", "count <= total - start", "start + offset < total",
        "slot_param_start: usize = generics.param_start[slot]",
        "pstart: usize = generics.param_start[slot]",
    ),
    "count": (
        "count <= total - start", "offset < count",
        "slot_param_count: usize = generics.param_count[slot]",
        "count: usize = generics.param_count[slot]",
        "for k in 0..<count |structs, generics, pstart, type_args, bound, count|:",
    ),
    "offset": (
        "offset < count", "start + offset < total",
        "for k in 0..<count |structs, generics, pstart, type_args, bound, count|:",
        "structs.bindings.binding_names <- structs.bindings.binding_names.push(generics.params[pstart + k])",
    ),
}
template_source_binding = {
    "return false if slot_param_start > generics.params.count": {"total", "start"},
    "return false if slot_param_count > generics.params.count - slot_param_start": {"total", "start", "count"},
    "return 0 if pstart > generics.params.count": {"total", "start"},
    "return 0 if count > generics.params.count - pstart": {"total", "start", "count"},
    "slot_param_start: usize = generics.param_start[slot]": {"start"},
    "pstart: usize = generics.param_start[slot]": {"start"},
    "slot_param_count: usize = generics.param_count[slot]": {"count"},
    "count: usize = generics.param_count[slot]": {"count"},
    "for k in 0..<count |structs, generics, pstart, type_args, bound, count|:": {"count", "offset"},
    "structs.bindings.binding_names <- structs.bindings.binding_names.push(generics.params[pstart + k])": {"offset"},
}
for model_arg, relations in template_offset_bindings.items():
    for relation in relations:
        if relation in template_source_binding:
            if normalize(relation) not in template_source_lines or model_arg not in template_source_binding[relation]:
                raise SystemExit(f"template parameter offset argument {model_arg} is not source-bound at {relation}")
        elif relation not in template_offset_requires and relation not in template_offset_return:
            raise SystemExit(f"template parameter offset argument {model_arg} is disconnected")

require_negative_model("false_claim_pending_rows_share_base_extent", (
    "def false_claim_pending_rows_share_base_extent(index: usize, bases: usize, handles: usize, slots: usize) -> bool:",
    "requires index < bases and index < handles and index >= slots",
    "ensure result == true",
    "return index < slots",
))
require_negative_model("false_claim_one_past_pending_argument_is_accessible", (
    "def false_claim_one_past_pending_argument_is_accessible(total: usize, start: usize, count: usize, offset: usize) -> bool:",
    "requires start <= total and count <= total - start and offset == count",
    "ensure result == true",
    "return start + offset < total",
))
require_negative_model("false_claim_pending_append_keeps_rows_aligned_without_handle", (
    "def false_claim_pending_append_keeps_rows_aligned_without_handle(names: i64, argument_starts: i64, argument_counts: i64, handles: i64, instantiation_rows: i64, slots: i64, error_families: i64) -> bool:",
    "requires names >= 0 and names < 9223372036854775807",
    "requires names == argument_starts and names == argument_counts and names == handles",
    "requires names == instantiation_rows and names == slots and names == error_families",
    "ensure result == true",
    "return names + 1 == argument_starts + 1 and names + 1 == argument_counts + 1 and names + 1 == handles and names + 1 == instantiation_rows + 1 and names + 1 == slots + 1 and names + 1 == error_families + 1",
))
require_model(
    "generic_pending_argument_offset_is_bounded",
    "def generic_pending_argument_offset_is_bounded(total: usize, start: usize, count: usize, offset: usize) -> bool:",
    (
        "requires start <= total and count <= total - start and offset < count",
        "ensure result == true",
        "return start + offset < total",
    ),
)
require_model(
    "generic_pending_template_parameter_offset_is_bounded",
    "def generic_pending_template_parameter_offset_is_bounded(total: usize, start: usize, count: usize, offset: usize) -> bool:",
    (
        "requires start <= total and count <= total - start and offset < count",
        "ensure result == true",
        "return start + offset < total",
    ),
)

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("pending worklist proof declaration inventory changed")
if not NEGATIVE.read_text().startswith('include "./backend_generic_pending_worklist_bounds.elisa"'):
    raise SystemExit("negative worklist controls must include the admitted proof model")

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("pending worklist bounds proof requires a strict proof build")
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
    INSTANTIATE_SOURCE,
    DEBUG_SOURCE,
    REGISTRATION_SOURCE,
    INFERENCE_SOURCE,
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    report = json.loads(result.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return result.returncode, report


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
    "scope": "pending generic worklist rows, slot metadata, flattened argument spans, and parallel registration",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
