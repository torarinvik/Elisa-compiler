"""Explicit packed-store allocation selectors must match their constructor position."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def source(path: str) -> str:
    return (ROOT / path).read_text()


parser = source("src/parser/parser_expr.elisa")
parser_postfix = source("src/parser/parser_expr_postfix.elisa")
structs = source("src/backend/codegen_struct_table.elisa")
backend_env = source("src/backend/codegen_env.elisa")
call_store = source("src/backend/codegen_call_store.elisa")
fixture = source("test/repro/packed_new_store_owner_line_zero.pos.elisa")

position_start = parser.find("def new_region_use_position(")
position_end = parser.find("\n\n", position_start)
position_helper = parser[position_start:position_end]
if "Expr.Call(callee" not in position_helper or \
        "Expr.Field(_, _, field_pos) | Expr.Scope(_, _, field_pos)" not in position_helper:
    raise SystemExit("new[store] selector owner must be the inner constructor field position")
postfix_start = parser_postfix.find("def postfix_dot_suffix(")
postfix_end = parser_postfix.find("\n\n", postfix_start)
if "Ast::Expr.Field(active," not in parser_postfix[postfix_start:postfix_end] or \
        "Ast::pos_of_token(token)" not in parser_postfix[postfix_start:postfix_end]:
    raise SystemExit("field callee positions must originate from the dot token")
if "parser.new_region_use_position(region_new_allocated, Ast::pos_of_token(token))" not in parser or \
        'name: "__region_use", line: region_use_position.line, offset: region_use_position.offset' not in parser:
    raise SystemExit("parser must record successful constructor selectors at the computed exact position")
if "region_use_offsets: mutable darray[u32] = []" not in structs:
    raise SystemExit("backend region-use table must store declaration offsets")
if "region_use_offsets <- structs.annotations.region_use_offsets.push(annotation.offset)" not in backend_env:
    raise SystemExit("backend marker collector must preserve the parser offset")
lookup_start = backend_env.find("def region_use_name_at(")
lookup_end = backend_env.find("\n\n", lookup_start)
lookup = backend_env[lookup_start:lookup_end]
if "line: u32, offset: u32" not in lookup or \
        "region_use_lines[probe] == line and structs.annotations.region_use_offsets[probe] == offset" not in lookup:
    raise SystemExit("backend selector lookup must match both coordinates")
if "callee is Expr.Field(packed_ctor_head, packed_ctor_variant, packed_ctor_line)" not in call_store or \
        "region_use_name_at(packed_ctor_line.line, packed_ctor_line.offset, structs)" not in call_store:
    raise SystemExit("packed constructor lowering must pass its exact source position")
if fixture.count("#line 0 packed-new-store-owner.elisa") != 2 or \
        "new[first_store] Node.Leaf(value: 11)" not in fixture or \
        "new[second_store] Node.Leaf(value: 22)" not in fixture:
    raise SystemExit("regression must allocate distinct packed values into stores on one logical line")
