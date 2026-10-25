"""Keep generic function-body binders attached to their exact declaration."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
RESOLVE = ROOT / "src/semantic/resolve.elisa"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


source = RESOLVE.read_text()
walk = function_source(source, "resolve_declarations_walk_with_context")
if not all(fragment in walk for fragment in (
    "table.generic_param_lines.count",
    "generic_index < table.generic_param_names.count",
    "generic_index < table.generic_param_owner_offsets.count",
    "table.generic_param_lines[generic_index] == line.line",
    "table.generic_param_owner_offsets[generic_index] == line.offset",
    "bound.push(table.generic_param_names[generic_index])",
)):
    raise SystemExit("function-body generic binders must use the declaration's exact line/offset owner")
