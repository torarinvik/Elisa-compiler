"""Bind Try callable/type candidate selection to unresolved static branches."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CALLABLE_ROWS = (ROOT / "src/semantic/check_try_fallible/callable_rows.elisa").read_text()
FALLBACK = (ROOT / "src/semantic/check_try_fallible/fallback_casts.elisa").read_text()
USING_ALIASES = (ROOT / "src/semantic/check_try_fallible/using_aliases.elisa").read_text()
TRY_CHECK = (ROOT / "src/semantic/check_try_fallible.elisa").read_text()
FIXTURE = (ROOT / "test/repro/try_unresolved_static_function_family.elisa").read_text()
SMOKE = (ROOT / "test/parity/try_unresolved_static_function_family_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


filter_annotations = function_source(FALLBACK, "try_static_binding_filtered_annotations")
unresolved_decl = function_source(CALLABLE_ROWS, "callable_function_declaration_is_static_unresolved")
visible_function = function_source(CALLABLE_ROWS, "callable_function_declaration_visible")
ufcs_candidate = function_source(CALLABLE_ROWS, "callable_row_in_ufcs_candidate_set_indexed")
facts = function_source(CALLABLE_ROWS, "try_noncall_callable_facts_add")
candidate = function_source(TRY_CHECK, "callable_try_call_has_unresolved_static_function_candidate")
returns_error = function_source(TRY_CHECK, "callable_error_indexed_returns_error")
family_ref = function_source(TRY_CHECK, "callable_error_indexed_family_ref")
family_refs = function_source(TRY_CHECK, "callable_error_indexed_family_refs")
legacy_family = function_source(USING_ALIASES, "try_noncall_callable_error_family")
nominal_owner = function_source(CALLABLE_ROWS, "try_overload_nominal_type_owner_for_module")
unresolved_wildcard = function_source(CALLABLE_ROWS, "try_overload_unresolved_wildcard_type_owner")
unresolved_selective = function_source(CALLABLE_ROWS, "try_overload_unresolved_selective_import_can_bind_type")
import_module_match = function_source(CALLABLE_ROWS, "callable_import_module_matches_target")
NOMINAL_IMPORT_FIXTURE = (ROOT / "test/repro/try_overload_nominal_identity_controls.elisa").read_text()

if not all(fragment in filter_annotations for fragment in (
    'marker.name != "__function_static_branch"',
    'owner: "__try_unresolved_function"',
    "if not branch.known",
    "marker.identity_id == 4294967295",
)) or not all(fragment in unresolved_decl for fragment in (
    'marker.owner == "__try_unresolved_function"',
    "marker.module == candidate_module",
    "marker.line == declaration_line",
    "marker.offset == declaration_offset",
)):
    raise SystemExit("Try must preserve an unknown static function as an exact unresolved candidate")
if not all("callable_function_declaration_is_static_inactive" in body for body in (visible_function, ufcs_candidate)) or any("callable_function_declaration_is_static_unresolved" in body for body in (visible_function, ufcs_candidate)):
    raise SystemExit("unknown static functions must stay possible visible/UFCS candidates until family selection becomes uncertain")

if not all(fragment in candidate for fragment in (
    "callable_function_declaration_is_static_unresolved",
    "callable_row_visible_for_try_call",
    "callable_try_call_forwards_arguments",
    "callable_symbol_accepts_arity",
)) or "callable_try_call_has_unresolved_static_function_candidate" not in returns_error or not all(fragment in body for body in (family_ref, family_refs) for fragment in ("callable_try_call_has_unresolved_static_function_candidate",)):
    raise SystemExit("Try must treat a possibly selected unresolved function as uncertain before borrowing an ErrorSet family")
if not all(fragment in facts for fragment in (
    "callable_function_declaration_is_static_unresolved",
    "family_rows == 0 and not unresolved_static_branch",
    "not unresolved_static_branch and family_rows <= 1.usize()",
)) or 'marker.owner == "__try_unresolved_function"' not in legacy_family:
    raise SystemExit("cached and legacy Try callable facts must not claim an unresolved branch's family")

if not all(fragment in nominal_owner for fragment in (
    'binding.owner == "__try_unresolved_static_binding"',
    'binding.name == "__from_member"',
    "try_overload_unresolved_selective_import_can_bind_type(file, binding, name, lexical_module, annotations, table)",
    "try_overload_unresolved_wildcard_type_owner(file, name, lexical_module, annotations, table)",
    "unresolved_wildcard_can_change_owner",
)) or not all(fragment in unresolved_wildcard for fragment in (
    'binding.owner != "__try_unresolved_static_binding"',
    'binding.name != "__binding_wildcard_import"',
    "binding.detail_name",
    "symbol.module_owner != binding.detail_name",
    "try_overload_type_declaration_visible",
)):
    raise SystemExit("cached nominal receiver identity must stay unknown when an unresolved import could change its owner")
if not all(fragment in unresolved_selective for fragment in (
    'source.owner == "__from_src"',
    "source.line == binding.line",
    "source.offset == binding.offset",
    "return false if not source_found or source_name == \"\"",
    "callable_import_module_matches_target(symbol.module_owner, binding.module, source_name)",
    "try_overload_type_symbol_is_nominal(symbol)",
    "return false",
)):
    raise SystemExit("unresolved selective imports must require a same-name nominal candidate and leave function/value-only imports non-ambiguous")
if not all(fragment in import_module_match for fragment in (
    'return candidate_module == imported_module if import_module == ""',
    "callable_module_path_matches_suffix(candidate_module, import_module, imported_module)",
)) or "from Provider import Widget" not in NOMINAL_IMPORT_FIXTURE:
    raise SystemExit("nominal owner import matching must handle root selective imports used by receiver resolution")

if not all(fragment in FIXTURE for fragment in (
    "static if UNKNOWN_TARGET:",
    "def origin() -> i64 error[SourceFault]",
    "return try origin()",
)) or not all(fragment in SMOKE for fragment in (
    "try_unresolved_static_function_family.elisa",
    "treated the unresolved function's ErrorSet as definite",
)):
    raise SystemExit("unresolved static-function family repro and Stage0/Stage1 smoke are required")

print("Try static branch uncertainty source binding passed")
