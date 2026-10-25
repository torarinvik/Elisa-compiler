"""Bind ErrorSet shadow lookup to the active static-import view."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_errorset_shadow.elisa"
FIXTURE = ROOT / "test/repro/errorset_shadow_static_import_branch.elisa"
UNKNOWN_FIXTURE = ROOT / "test/repro/errorset_shadow_unknown_static_import.elisa"
SMOKE = ROOT / "test/parity/errorset_shadow_static_import_branch_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


source = SOURCE.read_text()
checker = function_source(source, "check_errorset_shadow")
if not all(fragment in checker for fragment in (
        "pma_active_import_annotations(file, table)",
        "for annotation in annotations",
        "esh_is_error_set_visible(annotations, annotation.name")):
    raise SystemExit("ErrorSet shadow checks must resolve visibility through branch-filtered imports")
visibility = function_source(source, "esh_is_error_set_visible")
uncertain_import = function_source(source, "esh_unknown_static_import_may_define")
if "esh_unknown_static_import_may_define(annotations, name, function_module)" not in visibility or \
        visibility.find("esh_unknown_static_import_may_define(") > visibility.find("esh_imported_name_candidate(") or \
        not all(fragment in uncertain_import for fragment in (
            'marker.owner != "__pma_unknown_static_import"',
            'marker.name == "__from_member" and marker.detail_name == name',
            'marker.detail_name == "__binding_wildcard_import"')):
    raise SystemExit("uncertain import candidates must block imported ErrorSet shadow claims")

fixture = FIXTURE.read_text()
unknown_fixture = UNKNOWN_FIXTURE.read_text()
smoke = SMOKE.read_text()
if not all(fragment in fixture for fragment in (
        "static if false:",
        "from InactiveProvider import Fault",
        "static else:",
        "from ActiveProvider import Fault",
        "struct Fault:",
        "errorset Fault")):
    raise SystemExit("fixture must distinguish inactive ErrorSet provider from active nominal type")
if not all(fragment in smoke for fragment in (
        "errorset_shadow_static_import_branch.elisa",
        "errorset_shadow_unknown_static_import.elisa",
        "ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown",
        "shadows the declared error set")):
    raise SystemExit("smoke must reject a false shadow diagnostic from the inactive provider")
if not all(fragment in unknown_fixture for fragment in (
        "static if ELISA_TARGET_OS_WASI:",
        "from UnknownErrorProvider import Fault",
        "static else:",
        "from ActiveStructProvider import Fault",
        "errorset Fault")):
    raise SystemExit("unknown fixture must keep an ErrorSet candidate behind an unresolved target branch")

print('{"source_bound": true, "active_errorset_shadow_imports": true}')
