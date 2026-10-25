"""Require progress Catch lookup to preserve the lexical module identity."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src/semantic/check_progress_safety/catch_totality.elisa").read_text()
PARSER_EXPR = (ROOT / "src/parser/parser_expr.elisa").read_text()
PARSER_STMT = (ROOT / "src/parser/parser_stmt_pattern_arms.elisa").read_text()
match = re.search(
    r"(?ms)^        def progress_catch_error_arms_total_at_offset\(.*?(?=^        def |^    public:|\Z)",
    SOURCE,
)
if match is None:
    raise SystemExit("missing progress Catch totality helper")
helper = "".join(match.group(0).split())
if 'annotation.name=="__catch_expr"' not in helper or "annotation.module==table.current_module" not in helper:
    raise SystemExit("progress Catch totality must match error-return markers in the current lexical module")
if "catch_rows!=1.usize()" not in helper:
    raise SystemExit("progress Catch totality must remain conservative when marker identity is ambiguous")
parser_expr = "".join(PARSER_EXPR.split())
if 'Ast::EnumAnnotation{owner:callee_name,name:"__catch_expr",line:token.line,offset:token.start,module:parser.current_module}' not in parser_expr:
    raise SystemExit("expression Catch markers must record their lexical module")
parser_stmt = "".join(PARSER_STMT.split())
if not all(fragment in parser_stmt for fragment in (
        'Ast::EnumAnnotation{owner:"__catch_match",name:"__catch_match",line:catch_token.line,offset:catch_token.start,module:parser.current_module}',
        'Ast::EnumAnnotation{owner:catch_callee,name:"__catch_expr",line:catch_token.line,offset:catch_token.start,module:parser.current_module}')):
    raise SystemExit("statement Catch markers must record their lexical module")

print('{"source_bound": true, "catch_marker_module_identity": true}')
