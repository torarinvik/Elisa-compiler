"""Bind generic function-annotation checks to exact declaration identity."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_unknown_function_annotation.elisa"
SMOKE = ROOT / "test/parity/function_annotation_smoke.sh"


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
generic_owner = function_source(source, "function_has_generic_params")
contracts = function_source(source, "check_function_annotation_contracts")
declarations = function_source(source, "check_unknown_function_annotation_declarations")

if not all(fragment in generic_owner for fragment in (
    "function_offset: u32",
    "table.generic_param_owner_offsets[generic_index] == function_offset",
    "generic_line == line",
    "generic_line == encoded_bound_line",
    "table.generic_param_lines.count != table.generic_param_owner_offsets.count",
)):
    raise SystemExit("generic annotation restriction must select the exact owner and handle malformed metadata conservatively")
if "function_has_generic_params(line, function_offset, table)" not in contracts or \
        "line.line, line.offset, table" not in declarations:
    raise SystemExit("annotation contract walk must pass the function declaration offset")
if not all(fragment in smoke for fragment in (
    '"#line 0 generic_owner.elisa\\n"',
    '"#line 0 ordinary_owner.elisa\\n"',
    '@fixture function "ordinary_seed" must not have type or shape parameters',
)):
    raise SystemExit("annotation smoke must prevent same-line generic owners from misclassifying nongeneric fixtures")
