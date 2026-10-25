"""Source-bound checks for private imported enum visibility in PyModule defaults."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = ROOT / "src/driver/pymodule/defaults.elisa"
ALIAS_TARGETS = ROOT / "src/driver/pymodule/defaults/alias_targets.elisa"
PARSER = ROOT / "src/parser/parser_decl_module.elisa"
PARSER_TYPES = ROOT / "src/parser/parser_types.elisa"
PARSER_AGGREGATE = ROOT / "src/parser/parser_types_aggregate.elisa"
PARSER_DISPATCH = ROOT / "src/parser/parser_decl_dispatch.elisa"
PARSER_EXTERN = ROOT / "src/parser/parser_extern_enum.elisa"
ERROR_VISIBILITY = ROOT / "src/semantic/check_errorset_shadow.elisa"
FIXTURE = ROOT / "test/repro/pymodule_private_import_enum_root_fallback.elisa"
SMOKE = ROOT / "test/parity/pymodule_private_import_enum_root_fallback_smoke.sh"
ERROR_FIXTURE = ROOT / "test/repro/pymodule_private_error_enum_root_fallback.elisa"
ERROR_SMOKE = ROOT / "test/parity/pymodule_private_error_enum_root_fallback_smoke.sh"
EXTEND_FIXTURE = ROOT / "test/repro/pymodule_private_extend_enum_root_fallback.elisa"
EXTEND_SMOKE = ROOT / "test/parity/pymodule_private_extend_enum_root_fallback_smoke.sh"
STATIC_BRANCH_FIXTURE = ROOT / "test/repro/pymodule_private_enum_inactive_static_branch.elisa"
STATIC_BRANCH_SMOKE = ROOT / "test/parity/pymodule_private_enum_inactive_static_branch_smoke.sh"
STATIC_IMPORT_FIXTURE = ROOT / "test/repro/pymodule_imported_enum_static_import_branches.elisa"
STATIC_IMPORT_SMOKE = ROOT / "test/parity/pymodule_imported_enum_static_import_branches_smoke.sh"


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
parser_aggregate = PARSER_AGGREGATE.read_text(encoding="utf-8")
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
private_branch_state = compact_function(alias_targets, "pymodule_default_private_marker_branch_selection")
import_branch_state = compact_function(alias_targets, "pymodule_default_import_annotation_branch_selection")
metadata_branch_state = compact_function(alias_targets, "pymodule_default_enum_metadata_branch_selection")
row_selection = compact_function(alias_targets, "pymodule_default_static_if_row_selection")
condition_fold = compact_function(alias_targets, "pymodule_default_static_if_condition_value")
visible_import = compact_function(alias_targets, "pymodule_default_visible_enum_import")
alias_branch_state = compact_function(alias_targets, "pymodule_default_module_alias_branch_selection")
alias_precedence = compact_function(alias_targets, "pymodule_default_module_alias_registration_precedes")
if not all(fragment in helper for fragment in (
        "pymodule_default_private_marker_branch_selection(file,annotation)",
        "continueifbranch.knownandnotbranch.active")):
    raise SystemExit("inactive private enum/module markers must not hide active public enum candidates")
if not all(fragment in metadata_branch_state for fragment in (
        'marker.owner!="__static_if_branch"',
        'marker.name!="__enum_decl_static_branch"',
        "marker.arg_start!=enum_index.u32()",
        "pymodule_default_static_if_row_selection(file,marker.identity_id.usize())",
        "return(true,false)ifbranch.knownandnotbranch.selected",
        "return(false,false)ifunknown")):
    raise SystemExit("enum metadata candidates must retain per-row static-branch identity and uncertainty")
if not all(fragment in private_branch_state for fragment in (
        'marker.name!="__private_member_static_branch"',
        "marker.detail_name!=annotation.name",
        "marker.offset!=annotation.offset",
        "return(true,false)ifbranch.knownandnotbranch.selected",
        "return(false,false)ifunknown")):
    raise SystemExit("private enum/module visibility must filter only proven-inactive declaration markers")
candidate_exists = compact_function(alias_targets, "pymodule_default_imported_enum_candidate_exists")
if not all(fragment in import_branch_state for fragment in (
        '"__binding_wildcard_import_static_branch"',
        '"__from_member_static_branch"',
        "marker.detail_name!=marker_detail",
        "return(false,false)ifunknown")) or \
        visible_import.count("pymodule_default_import_annotation_branch_selection(file,import_annotation)") != 2 or \
        visible_import.count("continueifbranch.knownandnotbranch.active") != 2 or \
        not all(fragment in candidate_exists for fragment in (
            "file.enum_decl_names[enum_index]!=enum_name",
            "pymodule_default_enum_owner_matches_import_target(enum_owner,target_module_path)",
            "pymodule_default_enum_metadata_branch_selection(file,enum_index)",
            "continueifbranch.knownandnotbranch.active",
            "returntrue")) or \
        "pymodule_default_imported_enum_candidate_exists(file,enum_name,source_module_path)" not in visible_import or \
        "unresolved_selective_importorimported_owner.ambiguous" not in visible_import:
    raise SystemExit("PyModule import lookup must skip inactive rows and preserve uncertainty only for possible enum candidates")
selective_import_parser = compact_function(parser, "record_from_import_member")
wildcard_import_parser = compact_function(parser, "consume_using_target")
if 'record_static_if_branch_rows("__from_member_static_branch",member,token)' not in selective_import_parser or \
        'record_static_if_branch_rows("__binding_wildcard_import_static_branch",full_text,target_token)' not in wildcard_import_parser:
    raise SystemExit("parser import rows must retain branch identity for selective and wildcard enum imports")
if not all(fragment in row_selection for fragment in (
        "file.static_if_depths[row]!=branch_depth",
        "branch_kind==StaticIfBranch::Kind.Fallback",
        "condition.backend_folds",
        "return(false,false)ifcondition.backend_folds")):
    raise SystemExit("PyModule static-if selection must preserve first-true/fallback semantics and backend-foldable unknowns")
if not all(fragment in condition_fold for fragment in (
        "Expr.BoolLit(value,_)",
        "Expr.IntLit(value,_)",
        "BackendConstArithmetic::add_is_safe(left_value.value,right_value.value)",
        "return(false,0,true)")):
    raise SystemExit("PyModule branch folding must fold its proven subset and preserve uncertainty for backend-foldable forms")
if not all(fragment in alias_branch_state for fragment in (
        'marker.name!="__using_alias_static_branch"',
        "marker.detail_name!=alias.owner",
        "pymodule_default_static_if_row_selection(file,marker.identity_id.usize())",
        "return(true,false)ifbranch.knownandnotbranch.selected",
        "return(false,false)ifunknown")) or \
        not all(fragment in alias_precedence for fragment in (
            "left.module==right.module",
            "left_is_branchandnotright_is_branch",
            "left.offset<right.offset",
            "pymodule_default_alias_scope_matches(left.module,right.module)")):
    raise SystemExit("module aliases must skip inactive static arms and retain Core registration precedence")
enum_branch_parser = compact_function(parser_aggregate, "record_enum_metadata_static_branch_rows")
enum_metadata_parser = compact_function(parser_aggregate, "record_enum_metadata")
if not all(fragment in enum_branch_parser for fragment in (
        'owner:"__static_if_branch"',
        'name:"__enum_decl_static_branch"',
        "arg_start:metadata_index",
        "identity_id:branch_identity",
        "parser.static_if_branch_rows.count.u32()!=parser.static_if_depth",
        "forbranch_identityinparser.static_if_branch_rows",
        "identity_id:4294967295")) or \
        "record_enum_metadata_static_branch_rows(name,parser.enum_decl_names.count.u32()-1,declaration_line,declaration_offset)ifrecord_static_branch" not in enum_metadata_parser:
    raise SystemExit("parser enum metadata must carry branch identity keyed to its declaration row")
enum_declaration_parser = compact_function(parser_aggregate, "enum_declaration")
if "no_variants,token.line,token.start" not in enum_declaration_parser or \
        "variants,token.line,token.start" not in enum_declaration_parser or \
        "variants,name_token.line,name_token.start" not in compact_function(parser_types, "error_type_declaration"):
    raise SystemExit("all enum metadata rows must pass the declaration source position into branch provenance")
member_lookup = compact_function(alias_targets, "pymodule_default_enum_member_at_owner")
enum_value = compact_function(alias_targets, "pymodule_default_enum_value")
if not all(fragment in member_lookup for fragment in (
        "pymodule_default_enum_metadata_branch_selection(file,enum_index)",
        "continueifbranch.knownandnotbranch.active",
        "unknown_declaration<-true",
        "unknown_declarationor")) or \
        "pymodule_default_enum_metadata_branch_selection(file,enum_index)" not in enum_value:
    raise SystemExit("inactive enum rows must be excluded from member lookup, while unresolved rows block fallback")

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
if "parser.enum_declaration(true)" not in extern_enum or \
        'record_enum_metadata("ForeignEnum","",false,error_variants,enum_pos.line,enum_pos.offset,false)' not in extern_enum:
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

static_branch_fixture = STATIC_BRANCH_FIXTURE.read_text(encoding="utf-8")
if not all(
    fragment in static_branch_fixture
    for fragment in (
        "static if false:\n        private:\n            const enum Mode of i64:\n                High = 11",
        "static else:\n        public:\n            const enum Mode of i64:\n                High = 22",
        "const enum Mode of i64:\n    High = 97",
        "module Hidden:\n    const enum Mode of i64:\n        High = 33",
        "static if false:\n    using Hidden\nstatic else:\n    using Values",
        "using BranchHidden as BranchSelected",
        "using BranchValues as BranchSelected",
        "using BranchSelected as BranchChained",
        "BranchChained::AliasMode.High",
        "using Values",
        "value: i64 = Mode.High",
        "value: i64 = Values::Mode.High",
    )
):
    raise SystemExit("inactive private enum fixture must preserve the active public enum over a root fallback")
static_branch_smoke = STATIC_BRANCH_SMOKE.read_text(encoding="utf-8")
if '"default": "22"' not in static_branch_smoke or \
        "selected_public_enum(value: int = 22)" not in static_branch_smoke or \
        "selected_public_enum_qualified(value: int = 22)" not in static_branch_smoke or \
        '"default": "52"' not in static_branch_smoke or \
        "selected_static_alias(value: int = 52)" not in static_branch_smoke:
    raise SystemExit("static-branch smoke must assert active enum and alias values")

static_import_fixture = STATIC_IMPORT_FIXTURE.read_text(encoding="utf-8")
if not all(fragment in static_import_fixture for fragment in (
        "static if false:\n    from PrivateSelective import SelectiveMode",
        "static else:\n    from PublicSelective import SelectiveMode",
        "static if false:\n    using PrivateWildcard",
        "static else:\n    using PublicWildcard",
        "High = 91",
        "High = 92",
        "value: i64 = SelectiveMode.High",
        "value: i64 = WildcardMode.High")):
    raise SystemExit("static-import fixture must distinguish inactive private imports from active public enum imports")
static_import_smoke = STATIC_IMPORT_SMOKE.read_text(encoding="utf-8")
if '"default": "22"' not in static_import_smoke or \
        '"default": "42"' not in static_import_smoke or \
        "selected_selective(value: int = 22)" not in static_import_smoke or \
        "selected_wildcard(value: int = 42)" not in static_import_smoke:
    raise SystemExit("static-import smoke must assert active public enum defaults for selective and wildcard imports")

print('{"source_bound": true, "visibility_markers": 5, "root_fallback": true, "private_error_fallback": true, "private_extend_fallback": true, "inactive_private_static_branch": true, "inactive_private_import_branches": true, "private_header_forms": true}')
