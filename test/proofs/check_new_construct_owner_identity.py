"""`new` markers must join to their exact AST target, not the erased keyword."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def source(path: str) -> str:
    return (ROOT / path).read_text()


def compact(text: str) -> str:
    return "".join(line.split("#", 1)[0] for line in text.splitlines()).replace(" ", "").replace("\t", "").replace("\n", "")


PARSER = source("src/parser/parser_expr.elisa")
PRIMARY = source("src/parser/parser_expr_primary.elisa")
TABLE_TYPES = source("src/semantic/semantic_types_symbol_table.elisa")
TABLE_SETUP = source("src/semantic/semantic_api/table_setup.elisa")
DIAGNOSTICS = source("src/semantic/semantic_api/diagnostic_output.elisa")
POSITIONAL = source("src/semantic/check_positional_construction.elisa")
PACKED = source("src/semantic/check_packed_move_store.elisa")
LOCAL_VIEW = source("src/semantic/check_local_view_return_escape_lambdas.elisa")
FIXTURE = source("test/repro/new_construct_owner_line_zero.elisa")
SMOKE = source("test/parity/new_construct_owner_line_zero_smoke.sh")

target_start = PARSER.find("def new_construct_target_position(")
target_end = PARSER.find("\n\n", target_start)
target_helper = PARSER[target_start:target_end]
if target_start < 0 or "Expr.Paren(inner, _)" not in target_helper or \
        "Expr.RegionNew(inner, _, _)" not in target_helper or \
        "return Ast::expr_pos(expression)" not in target_helper:
    raise SystemExit("new marker target must preserve the exact consumer AST position through wrappers")
if 'line: target_pos.line, offset: target_pos.offset' not in PRIMARY or \
        PARSER.count("parser.record_new_construct(new_construct_pos)") < 2:
    raise SystemExit("parser must record new markers from the parsed target position")
if 'owner: "__new_auto", name: "__new_auto", line: token.line, offset: token.start' not in PARSER:
    raise SystemExit("deprecated auto-region diagnostic must retain its keyword source location")

if "new_construct_offsets: mutable darray[u32] = []" not in TABLE_TYPES:
    raise SystemExit("semantic table must retain new-marker target offsets beside lines")
for collector, expected in (
    (TABLE_SETUP, 1),
    (DIAGNOSTICS, 2),
):
    compact_source = compact(collector)
    if compact_source.count('table.new_construct_offsets<-table.new_construct_offsets.push(annotation.offset)ifannotation.name=="__new_construct"') != expected:
        raise SystemExit("all semantic table entry paths must preserve new-marker offsets")

positional = compact(POSITIONAL)
if 'positional_construction_is_new_target(table,call_line)' not in positional or \
        'table.new_construct_lines[index]==target_pos.line' not in positional or \
        'table.new_construct_offsets[index]==target_pos.offset' not in positional:
    raise SystemExit("positional-construction exemption must match the exact call target position")

packed = compact(PACKED)
if 'packed_new_construct_at(table,target_pos)' not in packed or \
        'table.new_construct_lines[index]==target_pos.line' not in packed or \
        'table.new_construct_offsets[index]==target_pos.offset' not in packed or \
        'check_packed_constructor_path(owner,shown_owner,variant,line,owners,signature_names,table)' not in packed:
    raise SystemExit("packed-constructor exemption must pass and match the exact call position")

local_view = compact(LOCAL_VIEW)
if 'marker.name=="__new_construct"andmarker.line==array_pos.lineandmarker.offset==array_pos.offset' not in local_view:
    raise SystemExit("local-view initializer classification must match the exact array target position")

if FIXTURE.count("#line 0 new-construct-owner.elisa") != 6 or not all(
    fragment in FIXTURE
    for fragment in (
        "allocated: Box = new Box(value: 1)",
        "unallocated: Box = Box(value: 2)",
        "allocated: Node = new Node.Leaf(value: 1)",
        "unallocated: Node = Node.Leaf(value: 2)",
        "out: mutable darray[i64] @r = []",
        "scratch: mutable darray[i64] = new[] [7]",
    )
):
    raise SystemExit("regression must collide new and ordinary AST targets on logical line zero")
if "new_construct_owner_line_zero.elisa" not in SMOKE or \
        "check_new_construct_owner_identity.py" not in SMOKE or \
        "same-line sibling inherited the new-form positional exemption" not in SMOKE or \
        "same-line sibling inherited the packed-constructor new exemption" not in SMOKE or \
        "sibling new-array marker changed the tied return initializer" not in SMOKE:
    raise SystemExit("smoke must assert each semantic consumer's same-line behavior")

print("new construct exact-target source checks passed")
