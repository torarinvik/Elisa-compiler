"""Extern signature contracts must stay bound to their declaration offset."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def source(path: str) -> str:
    return (ROOT / path).read_text()


def function_text(text: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        text,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


parser_signature = source("src/parser/parser_types_signature.elisa")
parser_export = source("src/parser/parser_export_surface.elisa")
parser_bounds = source("src/parser/parser_extern_bounds.elisa")
precondition = source("src/semantic/check_precondition_violated.elisa")
field_primitive = source("src/semantic/check_field_access_on_primitive.elisa")
unknown_field = source("src/semantic/check_unknown_field_access.elisa")
ordering = source("src/semantic/check_ordering_non_numeric.elisa")
poison = source("src/semantic/check_poisoned_operand.elisa")
extern_contract = source("src/semantic/check_extern_contract.elisa")
extern_resource = source("src/semantic/check_extern_resource.elisa")
extern_bounds = source("src/semantic/check_extern_bounds.elisa")
extern_header_probe = source("src/parser/parser_extern_header_probes.elisa")
pipeline = source("src/semantic/semantic_api/full_pipeline.elisa")
unsafe_report = source("src/driver/elisac_emit_unsafe_externs.elisa")
backend_ensure = source("src/backend/codegen_extern_ensure.elisa")
backend_side_tables = source("src/backend/codegen_struct_table_side_tables.elisa")
gate = source("test/parity/diagnostics_smoke.sh")

capture = function_text(parser_signature, "capture_extern_header_contracts")
if "extern_offset: u32" not in capture or "drain_signature_contracts(extern_line, extern_offset)" not in capture:
    raise SystemExit("extern signature capture must pass the declaration offset into contract draining")
if "capture_extern_header_contracts(token.line, token.start)" not in parser_export:
    raise SystemExit("extern parser must key captured signature contracts to the declaration token")
if 'name: "__extern_contract", line: token.line, offset: token.start' not in parser_export:
    raise SystemExit("extern contract-presence marker must carry the declaration offset")
if 'owner: "__extern_return_ptr", name: name, line: token.line, offset: token.start' not in parser_export:
    raise SystemExit("extern pointer-return marker must carry the declaration offset")
if 'owner: "__extern_return", name: extern_return_type, line: token.line, offset: token.start' not in parser_export:
    raise SystemExit("extern return-head marker must carry the declaration offset")
contract_probe = function_text(extern_header_probe, "header_has_signature_contract")
if 'parser.header_token_text(index) == "require"' not in contract_probe:
    raise SystemExit("singular extern `require` clauses must mark the exact contract-bearing declaration")

bounds_parser = function_text(parser_bounds, "apply_extern_bounds")
if "extern_offset: u32" not in bounds_parser or bounds_parser.count("offset: extern_offset") < 8:
    raise SystemExit("extern @bounds annotations must carry the exact declaration offset")
if "apply_extern_bounds(name, param_start, arity, token.line, token.start)" not in parser_export:
    raise SystemExit("extern @bounds parser must pass the declaration token offset")

for file_text, function_name in (
    (precondition, "collect_preconditions"),
    (field_primitive, "check_field_access_on_primitive_declarations"),
    (unknown_field, "check_unknown_field_access_declarations"),
    (ordering, "check_ordering_non_numeric_declarations"),
):
    walk = function_text(file_text, function_name)
    if "signature_contract_owner_offset_at(" not in walk or "line.offset" not in walk:
        raise SystemExit(f"{function_name} must select signature rows by exact extern offset")

if "signature_contract_owner_offset_at(contract_index, file.signature_contract_lines, file.signature_contract_kinds, file.signature_contract_exprs, file.enum_annotations) != extern_line.offset" not in poison:
    raise SystemExit("poisoned-operand traversal must select requires rows by exact extern offset")

coverage = function_text(extern_contract, "extern_contract_names_param")
if "signature_contract_owner_offset_at(sig_index, signature_contract_lines, signature_contract_kinds, signature_contract_exprs, annotations) == offset" not in coverage:
    raise SystemExit("extern pointer coverage must only use predicates owned by this declaration")
presence = function_text(extern_contract, "extern_has_signature_contract")
if 'annotation.name == "__extern_contract" and annotation.line == line and annotation.offset == offset' not in presence:
    raise SystemExit("strict-extern contract presence must require the exact owner marker")
return_flag = function_text(extern_contract, "extern_return_flag")
if "annotation.offset == offset" not in return_flag or "line.line, line.offset" not in extern_resource:
    raise SystemExit("extern return-pointer diagnostics must select the exact declaration marker")

bounds_lookup = function_text(extern_bounds, "bounds_note")
bounds_check = function_text(extern_bounds, "check_extern_bounds")
if "annotation.offset == offset" not in bounds_lookup or "annotations[index].offset != line.offset" not in bounds_check:
    raise SystemExit("extern bounds annotations and contract rows must use exact declaration identity")
if "signature_contract_owner_offset_at(sig_index, signature_contract_lines, signature_contract_kinds, signature_contract_exprs, signature_annotations) != line.offset" not in bounds_check:
    raise SystemExit("extern @bounds contract validation must reject sibling signature rows")

if not all(text in pipeline for text in (
    "file.signature_contract_exprs, file.enum_annotations, table)",
    "file.signature_contract_kinds, file.signature_contract_exprs, file.enum_annotations",
)):
    raise SystemExit("semantic entry points must pass owner markers to extern contract consumers")

if not all(text in unsafe_report for text in (
    "offsets.push(line.offset)",
    "extern_report_has_signature_contract(line.line, line.offset, name, file_annotations)",
    "extern_report_contract_names_param(lines[index], offsets[index]",
    "extern_report_contract_names_param(lines[best], offsets[best]",
    "|untyped_total, lines, offsets, param_starts, index",
    "|buffer, lines, offsets, param_starts, best",
)):
    raise SystemExit("unsafe extern reporting must carry exact declaration offsets")

if not all(text in backend_ensure for text in (
    "backend_signature_contract_owner_offset_at(contract_index, file)",
    "checkable_offset == contract_owner_offset + 1",
    "structs.contracts.extern_ensure_offsets",
    "fns.offsets[fn_index.usize()]",
)) or "extern_ensure_offsets: mutable darray[u32] = []" not in backend_side_tables:
    raise SystemExit("backend extern ensures must match the FnTable declaration offset")

if 'python3 "$REPO_ROOT/test/proofs/check_extern_signature_contract_owner.py"' not in gate:
    raise SystemExit("diagnostics gate must run the extern signature-contract owner proof")
