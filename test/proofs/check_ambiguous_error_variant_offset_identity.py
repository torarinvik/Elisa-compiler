"""Bind ambiguous error-variant module recovery to exact family identity."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_ambiguous_error_variant.elisa"
PARSER = ROOT / "src/parser/parser_types_function.elisa"


def function_source(path: Path, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        path.read_text(),
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name} in {path.relative_to(ROOT)}")
    return match.group(0)


module_lookup = function_source(SOURCE, "aev_function_module_for_family")
if not all(fragment in module_lookup for fragment in (
        'declaration.owner != "__fn_module"',
        "declaration.line != family.line",
        "declaration.offset == family.offset",
        "declaration.identity_id == family.identity_id",
        "declaration.occurrence_offset == family.occurrence_offset")):
    raise SystemExit("ambiguous ErrorSet lookup must bind module provenance to the exact family occurrence")
if "declaration.offset == 0" in module_lookup or "family.offset == 0" in module_lookup:
    raise SystemExit("ambiguous ErrorSet lookup must treat byte offset zero as a valid declaration position")

parser_function = function_source(PARSER, "function_declaration")
if not all(fragment in parser_function for fragment in (
        'name: "__error_return", line: token.line, offset: token.start',
        'owner: "__fn_module", name: parser.current_module, line: token.line, offset: token.start',
        "occurrence_offset: error_occurrence")):
    raise SystemExit("parser return-family and module rows must share exact declaration and occurrence identity")

print('{"source_bound": true, "ambiguous_error_variant_module_identity": true}')
