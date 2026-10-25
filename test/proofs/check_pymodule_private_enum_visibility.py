"""Source-bound checks for private imported enum visibility in PyModule defaults."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = ROOT / "src/driver/pymodule/defaults.elisa"
ALIAS_TARGETS = ROOT / "src/driver/pymodule/defaults/alias_targets.elisa"
PARSER = ROOT / "src/parser/parser_decl_module.elisa"
PARSER_TYPES = ROOT / "src/parser/parser_types.elisa"
PARSER_DISPATCH = ROOT / "src/parser/parser_decl_dispatch.elisa"
PARSER_EXTERN = ROOT / "src/parser/parser_extern_enum.elisa"
ERROR_VISIBILITY = ROOT / "src/semantic/check_errorset_shadow.elisa"
FIXTURE = ROOT / "test/repro/pymodule_private_import_enum_root_fallback.elisa"
SMOKE = ROOT / "test/parity/pymodule_private_import_enum_root_fallback_smoke.sh"
ERROR_FIXTURE = ROOT / "test/repro/pymodule_private_error_enum_root_fallback.elisa"
ERROR_SMOKE = ROOT / "test/parity/pymodule_private_error_enum_root_fallback_smoke.sh"
EXTEND_FIXTURE = ROOT / "test/repro/pymodule_private_extend_enum_root_fallback.elisa"
EXTEND_SMOKE = ROOT / "test/parity/pymodule_private_extend_enum_root_fallback_smoke.sh"


def compact_function(source: str, name: str) -> str:
    lines = source.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line.lstrip().startswith(f"def {name}(")),
        None,
    )
    if start is None:
        raise SystemExit(f"missing production helper {name}")
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].lstrip().startswith("def ")),
        len(lines),
    )
    return "".join(
        "".join(line.split())
        for line in lines[start:end]
        if not line.lstrip().startswith("#")
    )


defaults = DEFAULTS.read_text(encoding="utf-8")
alias_targets = ALIAS_TARGETS.read_text(encoding="utf-8")
parser = PARSER.read_text(encoding="utf-8")
parser_types = PARSER_TYPES.read_text(encoding="utf-8")
parser_dispatch = PARSER_DISPATCH.read_text(encoding="utf-8")
parser_extern = PARSER_EXTERN.read_text(encoding="utf-8")
imported_owner = compact_function(alias_targets, "pymodule_default_imported_enum_owner")
visibility_call = re.search(
    r"(pymodule_default_[a-z0-9_]*(?:visible|visibility|private)[a-z0-9_]*)\(",
    imported_owner,
)
if visibility_call is None or "lexical_owner" not in imported_owner:
    raise SystemExit("imported enum candidates must pass the use-site scope through a visibility check")

helper_name = visibility_call.group(1)
helper = compact_function(alias_targets + "\n" + defaults, helper_name)
for marker in ("__private_enum_type", "__private_module_decl"):
    if marker not in helper:
        raise SystemExit(f"enum-candidate visibility check must honor typed parser marker {marker}")
if "__section_private" in helper or "__private_member_module" in helper:
    raise SystemExit("generic private declaration rows must not hide same-named public enum types")
if not all(
    fragment in helper
    for fragment in (
        "annotation.name==enum_name",
        "annotation.module==enum_owner",
        "annotation.module,lexical_owner",
        "annotation.module,annotation.name",
    )
):
    raise SystemExit("enum-candidate visibility check must compare access against the use-site scope")

private_marker = compact_function(parser, "private_type_visibility_marker")
if not all(marker in private_marker for marker in ("__private_enum_type", "__private_module_decl")):
    raise SystemExit("parser must identify private enum and module declaration kinds")
if not all(marker in private_marker for marker in ('head=="error"', 'head=="extern"', 'head=="packed"', 'head=="extend"', 'next_head=="enum"')):
    raise SystemExit("private ErrorSet, extern/packed enum, and extended namespace declarations need typed visibility markers")
head_offset = compact_function(parser, "private_declaration_head_offset")
if "TokenKind.At" not in head_offset or "TokenKind.Newline" not in head_offset:
    raise SystemExit("private declaration probes must skip decorator prefixes and their line breaks")
if "private_declaration_head_offset" not in private_marker:
    raise SystemExit("typed visibility markers must use the decorator-aware declaration head")
private_name = compact_function(parser, "private_name_ahead")
if not all(marker in private_name for marker in ("TokenKind.Error", "TokenKind.Extern", "TokenKind.Packed", "private_declaration_head_offset")):
    raise SystemExit("private error, extern enum, and packed enum names must be captured before parsing")
error_declaration = compact_function(parser_types, "error_type_declaration")
if "record_enum_metadata" not in error_declaration:
    raise SystemExit("error declarations must remain bound to the enum metadata consumed by PyModule defaults")
extern_enum = compact_function(parser_extern, "extern_enum_declaration")
if "parser.enum_declaration(true)" not in extern_enum:
    raise SystemExit("extern enum declarations must remain bound to enum metadata")
declaration_unit = compact_function(parser_dispatch, "parse_declaration_unit")
if "TokenKind.Packed" not in declaration_unit or "parser.enum_declaration(false)" not in declaration_unit:
    raise SystemExit("packed enum declarations must remain bound to enum metadata")
record_private = compact_function(parser, "record_private_member_if")
if not all(
    fragment in record_private
    for fragment in (
        "private_type_visibility_marker",
        "typed_marker",
        "Ast::EnumAnnotation{owner:typed_marker",
        "module:parser.current_module",
    )
):
    raise SystemExit("private declaration rows must retain their type-specific marker")

fixture = FIXTURE.read_text(encoding="utf-8")
if not all(
    fragment in fixture
    for fragment in (
        "private:\n        const enum Mode of i64:\n            High = 11",
        "const enum Mode of i64:\n    High = 97",
        "using Values",
        "value: i64 = Mode.High",
    )
):
    raise SystemExit("private-import fixture must distinguish the hidden enum from the public root fallback")
smoke = SMOKE.read_text(encoding="utf-8")
if '"default": "97"' not in smoke or "root_fallback(value: int = 97)" not in smoke:
    raise SystemExit("private-import smoke must assert the public root enum fallback")

error_fixture = ERROR_FIXTURE.read_text(encoding="utf-8")
if not all(
    fragment in error_fixture
    for fragment in (
        "private:\n        error Fault:\n            Hidden",
        "const enum Fault of i64:\n    Hidden = 97",
        "using Values",
        "value: i64 = Fault.Hidden",
    )
):
    raise SystemExit("private ErrorSet fixture must distinguish its hidden variant from the public root enum")
error_smoke = ERROR_SMOKE.read_text(encoding="utf-8")
if '"default": "97"' not in error_smoke or "root_fallback(value: int = 97)" not in error_smoke:
    raise SystemExit("private ErrorSet smoke must assert the public root enum fallback")

error_visibility_source = ERROR_VISIBILITY.read_text(encoding="utf-8")
import_type_candidate = compact_function(error_visibility_source, "esh_import_type_candidate")
if not all(marker in import_type_candidate for marker in (
    "esh_error_set_decl_is_private(annotations,declaration)",
    "notcatch_module_is_ancestor(declaration.module,function_module)",
)):
    raise SystemExit("Core must skip a private imported ErrorSet outside its owning module")
error_visibility = compact_function(error_visibility_source, "esh_is_error_set_visible")
nominal_shadow = error_visibility.find("esh_local_nominal_type_shadows_family")
imported_candidate = error_visibility.find("esh_imported_name_candidate")
if nominal_shadow < 0 or imported_candidate <= nominal_shadow:
    raise SystemExit("Core must check the visible root nominal enum before the imported ErrorSet candidate")

extend_fixture = EXTEND_FIXTURE.read_text(encoding="utf-8")
if not all(
    fragment in extend_fixture
    for fragment in (
        "module Api:",
        "private extend Values:\n        const enum Mode of i64:\n            High = 11",
        "const enum Mode of i64:\n    High = 97",
        "using Api::Values",
        "value: i64 = Mode.High",
    )
):
    raise SystemExit("private extend fixture must distinguish its enum from the visible root enum")
extend_smoke = EXTEND_SMOKE.read_text(encoding="utf-8")
if '"default": "97"' not in extend_smoke or "root_fallback(value: int = 97)" not in extend_smoke:
    raise SystemExit("private extend smoke must assert fallback to the public root enum")

print('{"source_bound": true, "visibility_markers": 5, "root_fallback": true, "private_error_fallback": true, "private_extend_fallback": true, "private_header_forms": true}')
