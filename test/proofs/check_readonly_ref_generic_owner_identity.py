"""Require readonly-ref generic classification to use the function's exact source identity."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
VALUES = ROOT / "src/semantic/check_ref_binding_modes_values.elisa"
CHECK = ROOT / "src/semantic/check_readonly_ref.elisa"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


values = VALUES.read_text()
check = CHECK.read_text()
generic = function_source(values, "rbm_function_is_generic")
collect = function_source(check, "collect_mutable_ref_params")

if "function_offset: u32" not in generic or not all(fragment in generic for fragment in (
    "table.generic_param_lines.count != table.generic_param_names.count",
    "table.generic_param_lines.count != table.generic_param_owner_offsets.count",
    "encoded_bound_line: u32 = line + 2147483648",
    "table.generic_param_owner_offsets[generic_index] == function_offset",
    "table.generic_param_lines[generic_index] == line",
    "table.generic_param_lines[generic_index] == encoded_bound_line",
)):
    raise SystemExit("readonly-ref generic lookup must join ordinary and encoded rows by exact owner offset")
if "rbm_function_is_generic(line.line, line.offset, table)" not in collect:
    raise SystemExit("readonly-ref function collection must pass each declaration's offset")
