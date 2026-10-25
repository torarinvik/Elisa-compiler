"""Bind ErrorSet alias fallback resolution to Core's candidate order."""
from __future__ import annotations

import argparse
from pathlib import Path
import re


parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
parser.parse_args()

ROOT = Path(__file__).resolve().parents[2]
ESH = ROOT / "src/semantic/check_errorset_shadow.elisa"
TRY = ROOT / "src/semantic/check_try_fallible.elisa"


def function_source(name: str, path: Path = ESH) -> str:
    source = path.read_text()
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name} in {path.relative_to(ROOT)}")
    return match.group(0)


fallback = function_source("esh_alias_index_targets_error_set")
ordered_candidates = (
    "if esh_root_error_set_is_visible(annotations, target_name)",
    "elif not esh_local_nominal_type_shadows_family(annotations, target_name, declaration.module_owner, table, visited)",
    "if esh_local_alias_names_error_set(annotations, target_name, declaration.module_owner, table, visited)",
    "elif esh_local_error_set_is_visible(annotations, target_name, declaration.module_owner)",
    "esh_imported_name_candidate(annotations, target_name, declaration.module_owner, table)",
)
positions = [fallback.find(candidate) for candidate in ordered_candidates]
if min(positions) < 0 or positions != sorted(positions):
    raise SystemExit(
        "ErrorSet alias fallback must check root ErrorSets, ordered nominal types, "
        "local aliases, local ErrorSets, then imports"
    )
if "esh_local_type_name_exists(" in fallback:
    raise SystemExit("unordered any-scope type lookup must not decide alias target precedence")

visibility = function_source("esh_is_error_set_visible")
private_module_gate = "try_error_alias_module_visible(annotations, declaration.module, function_module)"
imported_fallback = "esh_error_set_imported(annotations, declaration, function_module)"
if private_module_gate not in visibility or imported_fallback not in visibility:
    raise SystemExit("ErrorSet import fallback must respect private module paths")
if visibility.find(private_module_gate) > visibility.find(imported_fallback):
    raise SystemExit("private module visibility must be checked before accepting an imported ErrorSet")

if "visited: mutable darray[u32]&" not in fallback:
    raise SystemExit("recursive alias target lookup must carry a declaration-ID visited stack")
cycle_guard = "return false if any prior_id in visited where prior_id == declaration.declaration_id.value"
push = "visited <- visited.push(declaration.declaration_id.value)"
pop = "_ = visited.pop()"
if not (cycle_guard in fallback and push in fallback and pop in fallback):
    raise SystemExit("recursive alias target lookup must guard and unwind declaration-ID cycles")

for import_path in (
    function_source("esh_import_path_matches"),
    function_source("try_error_set_import_path_matches", TRY),
):
    if "catch_module_qualifier_alias_target(" in import_path or \
            "catch_module_alias_path_matches(import_module, raw_module, declaration_module)" not in import_path:
        raise SystemExit("ErrorSet imports must use their raw path qualified by the importer namespace")
atom = (ROOT / "test/atoms/errorset_shadow_identity.elisa").read_text()
for probe in (
    'return 14 if esh_is_error_set_visible(alias_import_rows, "Fault", "Consumer", 900, path_table)',
    'return 52 if not esh_is_error_set_visible(raw_import_rows, "Fault", "Consumer", 900, path_table)',
):
    if probe not in atom:
        raise SystemExit(f"ErrorSet import atom is missing Core-compatible raw-path probe {probe}")

print(
    '{"source_bound": true, "candidate_order": 5, "declaration_id_cycle_guard": true, "raw_import_path": true}'
)
