"""Flow-strict block-if markers must match the owning if token, not its line."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


parser = read("src/parser/parser_stmt_control_flow.elisa")
types = read("src/semantic/semantic_types_symbol_table.elisa")
table_setup = read("src/semantic/semantic_api/table_setup.elisa")
diagnostics = read("src/semantic/semantic_api/diagnostic_output.elisa")
checker = read("src/semantic/check_flow_shapes_strict.elisa")
pipeline = read("src/semantic/semantic_api/full_pipeline.elisa")
fixture = read("test/repro/flow_strict_block_if_owner_line_zero.elisa")
smoke = read("test/parity/flow_strict_block_if_owner_line_zero_smoke.sh")

if 'owner: "__block_if", name: "__block_if", line: if_token.line, offset: if_token.start, pos: Ast::pos_of_token(if_token)' not in parser:
    raise SystemExit("parser must preserve the exact source position of each block if")
if "block_if_offsets: mutable darray[u32] = []" not in types:
    raise SystemExit("semantic table must retain offsets paired with block-if lines")
for collector in (table_setup, diagnostics):
    if "block_if_offsets <- table.block_if_offsets.push(annotation.offset)" not in collector:
        raise SystemExit("all semantic table collectors must preserve block-if offsets")
if "def flow_strict_is_block_if(position: Ast::Pos" not in checker or \
        "block_if_lines[probe] == position.line and block_if_offsets[probe] == position.offset" not in checker:
    raise SystemExit("flow-strict classification must join exact source coordinates")
if "out.push(if_line.line) if tagged and not exempt" not in checker or \
        "for flagged_line in flagged_if_lines" not in pipeline or \
        "line: flagged_line" not in pipeline:
    raise SystemExit("flow-strict diagnostics must only report positions that match the exact owner")
if fixture.count("#line 0 flow-strict-owner.elisa") != 2 or \
        "can ComplexFlow:" not in fixture or "if inner:" not in fixture or "if outer:" not in fixture:
    raise SystemExit("regression must collide an exempt and tagged if on the same logical line")
if "flow_strict_block_if_owner_line_zero.elisa" not in smoke:
    raise SystemExit("semantic smoke must exercise the same-line exemption collision")
