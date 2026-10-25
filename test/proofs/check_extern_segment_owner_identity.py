"""Extern segment-owner markers must bind to the current declaration position."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "src/semantic/check_extern_segment.elisa"
PARSER = ROOT / "src/parser/parser_export_surface.elisa"


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

lookup = function_text(check, "extern_has_segment_owner")
if not all(fragment in lookup for fragment in (
    "line: u32, offset: u32, name: sview",
    'annotation.name == "__extern_segment_owner"',
    "annotation.owner == name",
    "annotation.line == line",
    "annotation.offset == offset",
)):
    raise SystemExit("extern segment-owner lookup must match the declaration line and offset")

walk = function_text(check, "check_extern_segment_walk")
if not all(fragment in walk for fragment in (
    "extern_has_segment_owner(enum_annotations, line.line, line.offset, name)",
    "check_extern_segment_walk(module_body, enum_annotations, annotation_args, table)",
    "check_extern_segment_walk(scoped_body, enum_annotations, annotation_args, table)",
)):
    raise SystemExit("extern segment diagnostics must use the current declaration identity through nested scopes")

if 'owner: name, name: "__extern_segment_owner", line: token.line, offset: token.start' not in parser:
    raise SystemExit("parser segment-owner markers must preserve the extern declaration offset")
if "Ast::Decl.Extern(name, param_start, arity, variadic, has_params, extern_return_type, parser.snapshot_pending_decorators(), Ast::pos_of_token(token))" not in parser:
    raise SystemExit("extern AST position must share the marker's declaration token offset")
