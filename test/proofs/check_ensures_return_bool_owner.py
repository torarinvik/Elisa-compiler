"""Conditional-return ensures markers must bind to their exact function declaration."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "src/semantic/check_ensures_structural.elisa"
PARSER = ROOT / "src/parser/parser_types_signature.elisa"
FUNCTION_PARSER = ROOT / "src/parser/parser_types_function.elisa"


def function_text(text: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        text,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


check = CHECK.read_text()
parser = PARSER.read_text()
function_parser = FUNCTION_PARSER.read_text()

return_bool_check = function_text(check, "ens_check_return_bool")
if not all(fragment in return_bool_check for fragment in (
    'annotation.name == "__ensures_return_bool"',
    "annotation.owner == name",
    "annotation.line == line.line",
    "annotation.offset == line.offset",
)):
    raise SystemExit("return-bool ensures markers must match the exact Decl.Func position")

marker_producer = function_text(parser, "append_ensures_return_bool")
if not all(fragment in marker_producer for fragment in (
    'name: "__ensures_return_bool"',
    "offset: parser.active_function_region_offset",
)):
    raise SystemExit("return-bool ensures markers must retain their owning function offset")

declaration_parser = function_text(function_parser, "function_declaration")
if not all(fragment in declaration_parser for fragment in (
    "parser.active_function_region_offset <- token.start",
    "Ast::Decl.Func(function_name, threaded_params, return_type, resolved_body, effects, decorators, Ast::pos_of_token(token))",
)):
    raise SystemExit("the marker offset and Decl.Func position must share the `def` token")
