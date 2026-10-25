"""Bind type-specific visibility metadata to imported enum resolution."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PARSER = ROOT / "src/parser/parser_decl_module.elisa"
ALIAS_TARGETS = ROOT / "src/driver/pymodule/defaults/alias_targets.elisa"
FIXTURE = ROOT / "test/repro/pymodule_private_function_same_name_public_enum.elisa"
SMOKE = ROOT / "test/parity/pymodule_private_function_same_name_public_enum_smoke.sh"


def compact_function(source: str, name: str) -> str:
    lines = source.splitlines()
    start = next((i for i, line in enumerate(lines) if line.lstrip().startswith(f"def {name}(")), None)
    if start is None:
        raise SystemExit(f"missing production helper {name}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("def ")), len(lines))
    return "".join("".join(line.split()) for line in lines[start:end] if not line.lstrip().startswith("#"))


parser = PARSER.read_text(encoding="utf-8")
for marker in ("__private_enum_type", "__private_module_decl"):
    if marker not in parser:
        raise SystemExit(f"parser must preserve declaration-kind visibility marker {marker}")

alias_targets = ALIAS_TARGETS.read_text(encoding="utf-8")
visibility = compact_function(alias_targets, "pymodule_default_imported_enum_is_visible")
if not all(marker in visibility for marker in ("__private_enum_type", "__private_module_decl")):
    raise SystemExit("import visibility must use declaration-kind markers, not generic private-member rows")
if "__section_private" in visibility or "__private_member_module" in visibility:
    raise SystemExit("generic private declarations must not hide same-named public enum types")

import_owner = compact_function(alias_targets, "pymodule_default_imported_enum_owner")
if "pymodule_default_imported_enum_is_visible" not in import_owner:
    raise SystemExit("imported enum candidates must be filtered through type visibility")
resolver = compact_function(alias_targets, "pymodule_default_enum_value")
qualified = resolver.find("ifenum_qualifierisqualifier:")
qualified_visibility = resolver.find("pymodule_default_imported_enum_is_visible", qualified)
variant_lookup = resolver.find("variant_start:usize=file.enum_decl_variant_starts", qualified)
if not (qualified >= 0 and qualified_visibility > qualified and variant_lookup > qualified_visibility):
    raise SystemExit("qualified enum defaults must use the same type visibility filter before reading variants")

fixture = FIXTURE.read_text(encoding="utf-8")
if not all(part in fixture for part in (
    "private:\n        def Mode() -> i64:",
    "public:\n        const enum Mode of i64:\n            High = 11",
    "const enum Mode of i64:\n    High = 97",
    "using Values",
    "Mode.High",
)):
    raise SystemExit("control must pair a private same-named function with a public imported enum and distinct root enum")
smoke = SMOKE.read_text(encoding="utf-8")
if '"default": "11"' not in smoke:
    raise SystemExit("private-function control must retain the public imported enum candidate")

print('{"source_bound": true, "type_specific_visibility": true, "public_enum_default": 11}')
