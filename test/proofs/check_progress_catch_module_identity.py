"""Require progress Catch lookup to preserve the lexical module identity."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src/semantic/check_progress_safety/catch_totality.elisa").read_text()
PROGRESS_SOURCE = (ROOT / "src/semantic/check_progress_safety.elisa").read_text()
TERMINATION_SOURCE = (ROOT / "src/semantic/resolve_flow_termination.elisa").read_text()
PARSER_EXPR = (ROOT / "src/parser/parser_expr.elisa").read_text()
PARSER_STMT = (ROOT / "src/parser/parser_stmt_pattern_arms.elisa").read_text()
ATOM = (ROOT / "test/atoms/catch_totality_offset_identity.elisa").read_text()
match = re.search(
    r"(?ms)^        def progress_catch_error_arms_total_at_offset\(.*?(?=^        def |^    public:|\Z)",
    SOURCE,
)
if match is None:
    raise SystemExit("missing progress Catch totality helper")
helper = "".join(match.group(0).split())
if not all(fragment in helper for fragment in (
        'annotation.name=="__catch_expr"',
        "annotation.module==table.current_module",
        "line_known:bool,offset_known:bool",
        "notline_known",
        "notoffset_knownorannotation.offset==offset")) or any(fragment in helper for fragment in (
        "offset==0orannotation.offset==offset",
        "returnfalseifline==0",
        "offset==4294967295")):
    raise SystemExit("progress Catch totality must use explicit coordinate-presence flags so every u32 position remains valid")
if "catch_rows!=1.usize()" not in helper:
    raise SystemExit("progress Catch totality must remain conservative when marker identity is ambiguous")
line_only = re.search(
    r"(?ms)^        def progress_catch_error_arms_total_at\(.*?(?=^        def |^    public:|\Z)",
    SOURCE,
)
line_free = re.search(
    r"(?ms)^        def progress_catch_error_arms_total\(.*?(?=^        def |^    public:|\Z)",
    SOURCE,
)
if line_only is None or "progress_catch_error_arms_total_at_offset(arms,table,line,0,true,false)" not in "".join(line_only.group(0).split()):
    raise SystemExit("synthetic line-only Catch callers must mark their missing offset explicitly")
if line_free is None or "progress_catch_error_arms_total_at_offset(arms,table,0,0,false,false)" not in "".join(line_free.group(0).split()):
    raise SystemExit("synthetic location-free Catch callers must mark both coordinates absent explicitly")
source_backed_call = "progress_catch_error_arms_total_at_offset(arms,table,line.line,line.offset,true,true)"
source_backed_match_call = "progress_catch_error_arms_total_at_offset(arms,table,match_line.line,match_line.offset,true,true)"
if "".join(SOURCE.split()).count(source_backed_call) != 2 or "".join(SOURCE.split()).count(source_backed_match_call) != 1:
    raise SystemExit("source-backed Catch totality paths must mark their AST line and offset present")
if "".join(PROGRESS_SOURCE.split()).count(source_backed_match_call) != 2 or source_backed_call not in "".join(TERMINATION_SOURCE.split()):
    raise SystemExit("progress and termination Catch paths must forward both AST coordinates as present")
if not all(fragment in ATOM for fragment in (
        'name: "__catch_expr", line: 0, offset: 100, module: "Caller"',
        'owner: "load", name: "__catch_expr", line: 0, offset: 120, module: "Caller"',
        'owner: "load", name: "__catch_expr", line: 0, offset: 100, module: "Other"',
        'name: "Fault.Bad", line: 0, offset: 100, module: "Caller"',
        'progress_catch_error_arms_total_at_offset(arms, table, 0, 100, true, true)')):
    raise SystemExit("progress Catch atom must exercise a line-zero catch at a positive source offset alongside same-line and other-module siblings")
parser_expr = "".join(PARSER_EXPR.split())
if 'Ast::EnumAnnotation{owner:callee_name,name:"__catch_expr",line:token.line,offset:token.start,module:parser.current_module}' not in parser_expr:
    raise SystemExit("expression Catch markers must record their lexical module")
parser_stmt = "".join(PARSER_STMT.split())
if not all(fragment in parser_stmt for fragment in (
        'Ast::EnumAnnotation{owner:"__catch_match",name:"__catch_match",line:catch_token.line,offset:catch_token.start,module:parser.current_module}',
        'Ast::EnumAnnotation{owner:catch_callee,name:"__catch_expr",line:catch_token.line,offset:catch_token.start,module:parser.current_module}')):
    raise SystemExit("statement Catch markers must record their lexical module")

print('{"source_bound": true, "catch_marker_module_identity": true}')
