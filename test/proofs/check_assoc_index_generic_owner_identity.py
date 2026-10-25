"""Bind associated-index generic and bound rows to the exact function declaration."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CONSUMER = ROOT / "src/semantic/check_assoc_index_bounds.elisa"
FIXTURE = ROOT / "test/repro/assoc_index_generic_owner_line0.elisa"
SMOKE = ROOT / "test/parity/assoc_index_generic_owner_line0_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


consumer = CONSUMER.read_text()
fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()
generic_params = function_source(consumer, "aib_function_generic_params")
has_bound = function_source(consumer, "aib_function_has_bound")

if not all(fragment in generic_params for fragment in (
    "func_offset: u32",
    "file.generic_param_lines.count != file.generic_param_names.count",
    "file.generic_param_lines.count != file.generic_param_owner_offsets.count",
    "file.generic_param_lines[index] == func_line",
    "file.generic_param_owner_offsets[index] == func_offset",
)) or "func_line == 0" in generic_params:
    raise SystemExit("associated-index generic parameters must be selected by exact function owner")
if not all(fragment in has_bound for fragment in (
    "func_offset: u32",
    "SemanticAssocIndexBoundMarker::contains(file.generic_param_lines, func_line + 2147483648)",
    "file.generic_param_lines[index] == func_line + 2147483648",
    "file.generic_param_owner_offsets[index] == func_offset",
)) or "func_line == 0" in has_bound:
    raise SystemExit("associated-index bound markers must match the exact function owner offset")
if "aib_function_has_bound(file, line.line, line.offset)" not in consumer or \
        "aib_function_generic_params(file, line.line, line.offset, generic_params)" not in consumer:
    raise SystemExit("Decl.Func analysis must pass both source line and declaration offset")

directives = [line for line in fixture.splitlines() if line.startswith("#line 0 ")]
if len(directives) != 2 or not all(fragment in fixture for fragment in (
    "#line 0 bounded-owner.elisa\ndef bounded[T: IndexKey]",
    "#line 0 ordinary-owner.elisa\ndef ordinary(values: array[i64, 8], T: Key)",
    "return values[T.slot()]",
    "#line 20 actual-bound-owner.elisa\ndef actual_bound[T: IndexKey]",
)):
    raise SystemExit("fixture must collide a bounded generic function with a concrete same-line local name")
if "assoc_index_generic_owner_line0.elisa" not in smoke or \
        "expected one warning from actual_bound" not in smoke:
    raise SystemExit("smoke must retain the real generic-bound warning and exclude the same-line concrete false positive")
