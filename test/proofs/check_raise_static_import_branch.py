"""Bind raise error-family import resolution to active static-if imports."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_raise_without_error_set.elisa"
LAMBDA_SOURCE = ROOT / "src/semantic/check_lambda_raise_conformance.elisa"
PARSER_SOURCE = ROOT / "src/parser/parser_types_function.elisa"
IMPORT_PARSER_SOURCE = ROOT / "src/parser/parser_decl_module.elisa"
FIXTURE = ROOT / "test/repro/raise_static_import_branch.elisa"
SMOKE = ROOT / "test/parity/raise_static_import_branch_smoke.sh"
OFFSET_FIXTURE = ROOT / "test/repro/raise_declaration_offset_identity.elisa"
OFFSET_SMOKE = ROOT / "test/parity/raise_declaration_offset_identity_smoke.sh"
LATE_IMPORT_FIXTURE = ROOT / "test/repro/raise_late_import_offset_zero.elisa"
LATE_IMPORT_SMOKE = ROOT / "test/parity/raise_late_import_offset_zero_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


source = SOURCE.read_text()
lambda_source = LAMBDA_SOURCE.read_text()
parser_source = PARSER_SOURCE.read_text()
import_parser_source = IMPORT_PARSER_SOURCE.read_text()
entrypoint = function_source(source, "check_raise_without_error_set")
if "pma_active_import_annotations(file, table)" not in entrypoint:
    raise SystemExit("raise error-family lookup must receive branch-filtered import annotations")
if 'check_raise_without_error_set_decls(file.top_decls, annotations, file, "", table)' not in entrypoint:
    raise SystemExit("raise checker must pass the filtered annotation view to its declaration walk")

fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()
declarations = function_source(source, "check_raise_without_error_set_decls")
statements = function_source(source, "check_raise_statements")
inactive_scope = function_source(source, "raise_static_scope_is_inactive")
declaration_match = function_source(source, "raise_declaration_annotation_matches")
identity_selector = function_source(source, "raise_function_identity")
exemption_selector = function_source(source, "raise_function_declares_error_set")
lambda_family = function_source(lambda_source, "lrc_target_has_family")
lambda_family_name = function_source(lambda_source, "lrc_first_target_family")
if (
        not all(fragment in declaration_match for fragment in (
            "annotation.offset != function_pos.offset",
            "identity_id != 0")) or
        "function_pos.offset != 0" in declaration_match or
        not all(fragment in identity_selector for fragment in (
            "annotation.offset == function_pos.offset",
            'annotation.name == "__error_return"')) or
        "annotation.offset == 0" in identity_selector or
        not all(fragment in exemption_selector for fragment in (
            "annotation.offset == function_pos.offset",
            'annotation.name == "__error_return"',
            "function_offset: u32 = function_pos.offset + 1",
            "file.error_set_func_lines[index] == function_pos.line",
            "file.error_set_func_offsets[index] == function_offset",
            "index >= file.error_set_func_names.count")) or
        "function_pos.offset == 0" in exemption_selector or
        "file.error_set_func_lines[index] == function_pos.line and file.error_set_func_names[index] == function_name" in exemption_selector or
        "line_declares_error_set" in source or
        not all(fragment in lambda_family for fragment in (
            "family.offset != target.offset",
            "raise_return_error_occurrence(annotations, target.function_name, target_pos, target.identity_id)")) or
        "target.offset == 0" in lambda_family or
        not all(fragment in lambda_family_name for fragment in (
            "family.offset == target.offset",
            "raise_return_error_occurrence(annotations, target.function_name, target_pos, target.identity_id)")) or
        "target.offset == 0" in lambda_family_name):
    raise SystemExit("raise-family selectors must key declaration and family rows by exact byte offset, including zero")
if 'name: "__error_return", line: token.line, offset: token.start' not in parser_source or \
        'Ast::Decl.Func(function_name, threaded_params, return_type, resolved_body, effects, decorators, Ast::pos_of_token(token))' not in parser_source or \
        'parser.error_set_func_lines <- parser.error_set_func_lines.push(token.line) if parser.signature_has_error_set' not in parser_source or \
        'parser.error_set_func_offsets <- parser.error_set_func_offsets.push(token.start + 1) if parser.signature_has_error_set' not in parser_source or \
        'parser.error_set_func_names <- parser.error_set_func_names.push(parser.signature_error_set_name) if parser.signature_has_error_set' not in parser_source or \
        'error_set_func_offsets: parser.error_set_func_offsets' not in (ROOT / "src/parser/parser_types_entry.elisa").read_text():
    raise SystemExit("raise declaration and both error-set metadata paths must retain the parser token offset")
if "raise_function_declares_error_set(file, annotations, name, line)" not in declarations:
    raise SystemExit("raise declaration walk must pass the file sidecar used by its exact-offset compatibility path")
if not all(fragment in inactive_scope for fragment in (
        "pma_static_if_row_for_position(file, position)",
        "pma_static_if_row_selection(file, branch_row, current_module, table)",
        "branch.known and not branch.selected")):
    raise SystemExit("raise static-scope pruning must use exact Ast::Pos rows and skip only proven-inactive branches")
if 'continue if kind == "static" and raise_static_scope_is_inactive(file, line, current_module, table)' not in statements:
    raise SystemExit("raise statement walker must skip proven-inactive static blocks")
if "continue if raise_static_scope_is_inactive(file, line, current_module, table)" not in declarations:
    raise SystemExit("raise declaration walker must skip proven-inactive scoped declarations")
if "nested_module: sview @source = name" not in declarations:
    raise SystemExit("raise declaration walker must use the parser's canonical nested module path")
if not all(fragment in fixture for fragment in (
        "def active_statement_raise()",
        "def inactive_statement_raise()",
        "static if false:\n    def inactive_declaration_raise()",
        "raise Fault.Bad")):
    raise SystemExit("fixture must cover active and inactive static statement/declaration bodies")
if not all(fragment in fixture for fragment in (
        "static if false:",
        "from InactiveProvider import Fault",
        "static else:",
        "from ActiveProvider import Fault",
        "error[ActiveProvider::Fault]",
        "raise Fault.Bad")):
    raise SystemExit("fixture must raise an imported bare family against its qualified active provider")
if not all(fragment in smoke for fragment in (
        "raise_static_import_branch.elisa",
        "raise cannot propagate tag",
        "raise requires the current function to return an error union",
        'raise_without_set_count" != 1')):
    raise SystemExit("smoke must preserve active raise diagnostics, reject inactive-arm raises, and select the active import provider")

late_import_fixture = LATE_IMPORT_FIXTURE.read_text()
late_import_smoke = LATE_IMPORT_SMOKE.read_text()
import_resolver = function_source(source, "raise_imported_family_module")
if (
        "continue if imported.offset >= function_pos.offset" not in import_resolver or
        "function_pos.offset == 0" in import_resolver or
        "imported.line >= function_pos.line" in import_resolver or
        'owner: "__from_member", name: member, module: parser.current_module, line: token.line, offset: token.start' not in import_parser_source or
        not late_import_fixture.startswith("def first_offset_raise() -> void error[Fault]:\n") or
        not all(fragment in late_import_fixture for fragment in (
            "raise Fault.Bad",
            "#line 0 later-import.elisa",
            "from ProviderB import Fault",
            "module ProviderA:",
            "module ProviderB:")) or
        not all(fragment in late_import_smoke for fragment in (
            "raise_late_import_offset_zero.elisa",
            "raise cannot propagate tag",
            "raise requires the current function to return an error union"))):
    raise SystemExit("a later imported family must remain invisible to a function at byte offset zero, regardless of #line")

offset_fixture = OFFSET_FIXTURE.read_text()
offset_smoke = OFFSET_SMOKE.read_text()
if not offset_fixture.startswith("def offset_identity(value: i64) -> void error[Fault]:\n") or not all(fragment in offset_fixture for fragment in (
        "#line 1 same-offset-raise.elisa",
        "def offset_identity(value: i64) -> void error[Fault]:",
        "def offset_identity(value: bool) -> void:",
        "raise Fault.Bad")) or not all(fragment in offset_smoke for fragment in (
        "raise_declaration_offset_identity.elisa",
        "raise requires the current function to return an error union",
        '!= "1"')):
    raise SystemExit("same-#line overload fixture must reject borrowing an offset-zero error-return marker")

print('{"source_bound": true, "active_raise_error_imports": true, "inactive_raise_static_scopes": true, "exact_declaration_offsets": true, "exact_legacy_sidecar_offsets": true, "exact_import_offsets": true, "exact_sidecar_producer": true}')
