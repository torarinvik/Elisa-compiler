"""Keep exact allocation-token offsets aligned through Parser and Ast::File."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PARSER = (ROOT / "src/parser/parser_core.elisa").read_text()
PARSER_INIT = (ROOT / "src/parser/parser_core_member_tables.elisa").read_text()
AST = (ROOT / "src/parser/parser_tokens.elisa").read_text()
PARSE_FILE = (ROOT / "src/parser/parser_types_entry.elisa").read_text()
EFFECTS = (ROOT / "src/parser/parser_core_blocks_effects.elisa").read_text()
LOOP_VIEW = (ROOT / "src/semantic/semantic_loop_view.elisa").read_text()
PROBE = (ROOT / "test/repro/cpu_optional_goal_allocation_probe.elisa").read_text()


def compact(text: str) -> str:
    return "".join(line.split("#", 1)[0] for line in text.splitlines()).replace(" ", "").replace("\t", "").replace("\n", "")


def appears_in_order(text: str, *fragments: str) -> bool:
    cursor = 0
    for fragment in fragments:
        found = text.find(fragment, cursor)
        if found < 0:
            return False
        cursor = found + len(fragment)
    return True


parser = compact(PARSER)
parser_init = compact(PARSER_INIT)
ast = compact(AST)
parse_file = compact(PARSE_FILE)
effects = compact(EFFECTS)
loop_view = compact(LOOP_VIEW)
probe = compact(PROBE)

for fragment, text in (
    ("allocation_region_names:mutabledarray[sview@source]", parser),
    ("allocation_region_lines:mutabledarray[u32]", parser),
    ("allocation_region_offsets:mutabledarray[u32]", parser),
    ("allocation_region_names:[]", parser_init),
    ("allocation_region_lines:[]", parser_init),
    ("allocation_region_offsets:[]", parser_init),
    ("allocation_region_names:darray[sview@source]@source", ast),
    ("allocation_region_lines:darray[u32]@source", ast),
    ("allocation_region_offsets:darray[u32]@source", ast),
    ("allocation_region_names:parser.allocation_region_names", parse_file),
    ("allocation_region_lines:parser.allocation_region_lines", parse_file),
    ("allocation_region_offsets:parser.allocation_region_offsets", parse_file),
    ("allocation_region_names:file.allocation_region_names", loop_view),
    ("allocation_region_lines:file.allocation_region_lines", loop_view),
    ("allocation_region_offsets:file.allocation_region_offsets", loop_view),
    ("allocation_region_names:[]", probe),
    ("allocation_region_lines:[]", probe),
    ("allocation_region_offsets:[]", probe),
):
    if fragment not in text:
        raise SystemExit(f"allocation offset metadata is missing from a parser/file boundary: {fragment}")

if not appears_in_order(parse_file,
    "parser.allocation_region_names<-parser.allocation_region_names.push(parser.scan_token_text(index+2))",
    "parser.allocation_region_lines<-parser.allocation_region_lines.push(parser.scan_token_line(index))",
    "parser.allocation_region_offsets<-parser.allocation_region_offsets.push(parser.scan_token_pos(index).offset)",
):
    raise SystemExit("new[region] metadata must record the new token's exact offset in its parallel column")
new_row_appends = (
    "parser.allocation_region_names<-parser.allocation_region_names.push(parser.scan_token_text(index+2))",
    "parser.allocation_region_lines<-parser.allocation_region_lines.push(parser.scan_token_line(index))",
    "parser.allocation_region_offsets<-parser.allocation_region_offsets.push(parser.scan_token_pos(index).offset)",
)
if any(parse_file.count(fragment) != 1 for fragment in new_row_appends):
    raise SystemExit("every new[region] row must append exactly one name, line, and offset")

if not appears_in_order(effects,
    'parser.allocation_region_names<-parser.allocation_region_names.push("__inline_can")',
    "parser.allocation_region_lines<-parser.allocation_region_lines.push(current_token.line)",
    "parser.allocation_region_offsets<-parser.allocation_region_offsets.push(current_token.start)",
    "parser.allocation_region_names<-parser.allocation_region_names.push(granted_ref)",
    "parser.allocation_region_lines<-parser.allocation_region_lines.push(current_token.line)",
    "parser.allocation_region_offsets<-parser.allocation_region_offsets.push(current_token.start)",
):
    raise SystemExit("inline-can metadata must keep its offset column aligned with names and lines")
effect_row_appends = (
    "parser.allocation_region_names<-parser.allocation_region_names.push(",
    "parser.allocation_region_lines<-parser.allocation_region_lines.push(",
    "parser.allocation_region_offsets<-parser.allocation_region_offsets.push(",
)
if any(effects.count(fragment) != 2 for fragment in effect_row_appends):
    raise SystemExit("inline-can marker and captured grants must each append all three parallel columns")

print("allocation region offset metadata source checks passed")
