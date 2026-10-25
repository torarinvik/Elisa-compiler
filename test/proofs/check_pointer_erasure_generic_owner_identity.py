"""Bind pointer-erasure generic checks and regression coverage to function offsets."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_pointer_erasure_cast.elisa"
SMOKE = ROOT / "test/parity/generic_cast_smoke.py"


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
generic_owner = function_source(source, "pointer_erasure_generic_line")
declarations = function_source(source, "check_pointer_erasure_declarations")

if not all(fragment in generic_owner for fragment in (
    "offsets: darray[u32]&",
    "return true if lines.count != offsets.count",
    "lines[generic_index] == line and offsets[generic_index] == offset",
)):
    raise SystemExit("pointer-erasure generic context must match exact declaration offsets")
if not all(fragment in declarations for fragment in (
    "line.line, line.offset",
    "pointer_erasure_generic_line(generic_lines, generic_offsets, line.line, line.offset)",
)):
    raise SystemExit("pointer-erasure declaration walk must pass its exact owner identity")
if not all(fragment in smoke for fragment in (
    "LINE_ZERO_CONCRETE_ALIAS_CAST",
    "#line 0 generic_owner.elisa\ndef phantom[T]()",
    "#line 0 concrete_owner.elisa\ndef concrete_alias_cast(value: T) -> T:",
    "return value.cast[T]",
    '"pointer cast requires can[Unsafe]" not in line_zero_cast_output',
)):
    raise SystemExit("generic cast smoke must cover a concrete #line 0 owner collision")
