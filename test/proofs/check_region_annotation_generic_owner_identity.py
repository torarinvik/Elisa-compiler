"""Bind struct region-parameter checks to the exact generic declaration owner."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_region_annotation_scalar.elisa"
SMOKE = ROOT / "test/parity/region_scope_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


source = SOURCE.read_text()
smoke = SMOKE.read_text()
checker = function_source(source, "check_region_annotation_scalar")

if not all(fragment in checker for fragment in (
    "generic_index < table.generic_param_owner_offsets.count",
    "table.generic_param_lines[generic_index] == line.line",
    "table.generic_param_owner_offsets[generic_index] == line.offset",
)):
    raise SystemExit("struct region-parameter detection must match line and declaration offset")
if not all(fragment in smoke for fragment in (
    "#line 0 generic_owner.elisa\\ndef phantom[T]()",
    "#line 0 plain_struct.elisa\\nstruct Plain:",
    "values: darray[i64] @missing",
    "same-line generic function suppressed a plain struct's unknown region qualifier",
    'unknown region qualifier \\"missing\\"',
)):
    raise SystemExit("region smoke must cover a generic function colliding with a plain struct at #line 0")
