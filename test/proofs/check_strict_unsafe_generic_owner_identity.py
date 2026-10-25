"""Bind strict-unsafe generic suppression to the exact function declaration."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_strict_unsafe_ops_requires.elisa"
SMOKE = ROOT / "test/parity/unsafe_grant_scope_smoke.sh"


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
generic_context = function_source(source, "strict_unsafe_function_is_generic")
declaration_walk = function_source(source, "strict_unsafe_decls")

if not all(fragment in generic_context for fragment in (
    "function_pos.offset",
    "table.generic_param_owner_offsets[generic_index] == function_pos.offset",
    "generic_line == function_pos.line",
    "generic_line == function_pos.line + 2147483648",
)):
    raise SystemExit("strict-unsafe generic suppression must join by function line and declaration offset")
if "strict_unsafe_function_is_generic(line, table)" not in declaration_walk or \
        "generic_line in table.generic_param_lines" in declaration_walk:
    raise SystemExit("strict-unsafe declaration walk must use exact generic owner identity")
if not all(fragment in smoke for fragment in (
    '"line-zero generic owner does not suppress concrete unsafe check"',
    '"#line 0 generic_owner.elisa\\n"',
    '"#line 0 bad_owner.elisa\\n"',
    '"mutable alias requires"',
)):
    raise SystemExit("unsafe scope smoke must cover a nongeneric function sharing #line 0 with a generic owner")
