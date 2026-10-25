"""Bind qualified enum defaults to the same private-type filter as import lookup."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/driver/pymodule/defaults/alias_targets.elisa"
FIXTURE = ROOT / "test/repro/pymodule_qualified_private_enum_default.elisa"
SMOKE = ROOT / "test/parity/pymodule_qualified_private_enum_default_smoke.sh"


def compact_function(source: str, name: str) -> str:
    lines = source.splitlines()
    start = next((i for i, line in enumerate(lines) if line.lstrip().startswith(f"def {name}(")), None)
    if start is None:
        raise SystemExit(f"missing production helper {name}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("def ")), len(lines))
    return "".join("".join(line.split()) for line in lines[start:end] if not line.lstrip().startswith("#"))


source = SOURCE.read_text(encoding="utf-8")
resolver = compact_function(source, "pymodule_default_enum_value")
qualified = resolver.find("ifenum_qualifierisqualifier:")
visibility = resolver.find("pymodule_default_imported_enum_is_visible", qualified)
variant_lookup = resolver.find("variant_start:usize=file.enum_decl_variant_starts", qualified)
if not (qualified >= 0 and visibility > qualified and variant_lookup > visibility):
    raise SystemExit("qualified enum defaults must pass visibility before reading the variant")

fixture = FIXTURE.read_text(encoding="utf-8")
if not all(part in fixture for part in (
    "private:\n        const enum Mode of i64:\n            High = 11",
    "const enum Mode of i64:\n    High = 97",
    "Values::Mode.High",
)):
    raise SystemExit("qualified private-enum fixture lost its distinct private and root candidates")
smoke = SMOKE.read_text(encoding="utf-8")
if "is private to module" not in smoke or "Values::Mode.High" not in fixture:
    raise SystemExit("qualified private-enum smoke must assert the visibility diagnostic")

print('{"source_bound": true, "qualified_visibility_before_variant": true}')
