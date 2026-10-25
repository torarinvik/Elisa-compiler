"""Bind Try callable selection and cached facts to static function branches."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
FALLBACK = (ROOT / "src/semantic/check_try_fallible/fallback_casts.elisa").read_text()
CALLABLE_ROWS = (ROOT / "src/semantic/check_try_fallible/callable_rows.elisa").read_text()
TRY_CHECK = (ROOT / "src/semantic/check_try_fallible.elisa").read_text()
NONCALL = (ROOT / "src/semantic/check_try_fallible/noncall_scan.elisa").read_text()
FIXTURE = (ROOT / "test/repro/try_inactive_static_function_family.elisa").read_text()
SMOKE = (ROOT / "test/parity/try_inactive_static_function_family_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


filter_body = function_source(FALLBACK, "try_static_binding_filtered_annotations")
if not all(fragment in filter_body for fragment in (
    'marker.owner != "__static_if_branch" or marker.name != "__function_static_branch"',
    "pma_static_if_row_selection(file, marker.identity_id.usize(), marker.module, table)",
    "marker.identity_id == 4294967295",
    'owner: "__try_inactive_function"',
    "branch.known and not branch.selected",
)):
    raise SystemExit("Try must mark only functions proven inactive by static-branch selection")

inactive = function_source(CALLABLE_ROWS, "callable_function_declaration_is_static_inactive")
visible = function_source(CALLABLE_ROWS, "callable_function_declaration_visible")
active_count = function_source(CALLABLE_ROWS, "callable_active_direct_function_count")
facts = function_source(CALLABLE_ROWS, "try_noncall_callable_facts_add")
candidate_set = function_source(CALLABLE_ROWS, "callable_row_in_ufcs_candidate_set_indexed")
if not all(fragment in inactive for fragment in (
    'marker.owner == "__try_inactive_function"',
    "marker.module == candidate_module",
    "marker.line == declaration_line",
    "marker.offset == declaration_offset",
)) or "callable_function_declaration_is_static_inactive" not in visible or "callable_function_declaration_is_static_inactive" not in active_count or "callable_function_declaration_is_static_inactive" not in facts or "callable_function_declaration_is_static_inactive" not in candidate_set:
    raise SystemExit("Try visibility and cached callable facts must use the exact inactive declaration marker")

error_lookup = function_source(TRY_CHECK, "callable_error_indexed_returns_error")
family_lookup = function_source(TRY_CHECK, "callable_error_indexed_family")
family_ref = function_source(TRY_CHECK, "callable_error_indexed_family_ref")
family_refs = function_source(TRY_CHECK, "callable_error_indexed_family_refs")
if not all("callable_function_declaration_is_static_inactive" in body for body in (error_lookup, family_lookup, family_ref, family_refs)):
    raise SystemExit("Try error-family fallback must not retain an inactive function's ErrorSet")
if "callable_active_direct_function_count(table, annotations, annotation.owner)" not in NONCALL or "callable_active_direct_function_count(table, annotations, callee_name)" not in FALLBACK:
    raise SystemExit("Try's direct-callee gates must not count proven-inactive functions")

if "try_noncall_module_path(current_module, module_name" in NONCALL or "try_noncall_module_path(current_module, module_name" in CALLABLE_ROWS:
    raise SystemExit("Decl.Module recursion must use the parser's canonical module path directly")
if not all(fragment in FIXTURE for fragment in (
    "static if USE_INACTIVE_PROVIDER:",
    "Provider::Inner::InactiveFault",
    "static else:",
    "Provider::Inner::ActiveFault",
    "return try Provider::Inner::origin(value)",
)) or not all(fragment in SMOKE for fragment in (
    "try_inactive_static_function_family.elisa",
    "Stage0 selected the inactive function's ErrorSet",
    "Stage1 selected the inactive function's ErrorSet",
)):
    raise SystemExit("the inactive function-family repro and parity smoke must cover both branches")

print("Try inactive static-function source binding passed")
