"""For-brace field names are selected by the exact owning Stmt.For position."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


parser = read("src/parser/parser_stmt_for.elisa")
side_tables = read("src/backend/codegen_struct_table_side_tables.elisa")
collector = read("src/backend/codegen_module.elisa")
lookup_source = read("src/backend/codegen_env.elisa")
consumer = read("src/backend/codegen_stmt_for_shapes_iterable.elisa")
fixture = read("test/repro/for_brace_field_owner_offset.elisa")
smoke = read("test/parity/for_brace_field_owner_offset_smoke.sh")

if "consume_for_brace_pattern(variables_buffer, for_token.line, for_token.start)" not in parser or \
        "consume_for_brace_member(variables, for_line, for_offset)" not in parser or \
        'name: "__for_brace_field", line: for_line, offset: for_offset' not in parser or \
        "Ast::Stmt.For(bind, variables_buffer, iterable_expression, body, Ast::pos_of_token(for_token))" not in parser:
    raise SystemExit("parser must attach every field row to its owning for-token offset")
if "for_brace_field_offsets: mutable darray[u32] = []" not in side_tables or \
        "for_brace_field_offsets <- structs.queries.for_brace_field_offsets.push(annotation.offset)" not in collector:
    raise SystemExit("backend collection must preserve the parser's for-token offset")

lookup_start = lookup_source.find("def for_brace_field_at(")
lookup_end = lookup_source.find("\n\n\n", lookup_start)
lookup = lookup_source[lookup_start:lookup_end]
if lookup_start < 0 or not all(fragment in lookup for fragment in (
    "for_offset: u32",
    "for_brace_field_offsets.count != structs.queries.for_brace_field_names.count",
    "for_brace_field_offsets[probe] == for_offset",
)):
    raise SystemExit("backend lookup must fail closed on misalignment and match the exact loop offset")
if "for_brace_field_at(for_line.offset, sd_bind, structs)" not in consumer:
    raise SystemExit("field destructuring must use the Stmt.For source offset")

if fixture.count("#line 0 for-brace-fields.elisa") != 2 or not all(fragment in fixture for fragment in (
    "for {left: first_left, right: first_right} in pairs:",
    "for {right: second_right, left: second_left} in pairs:",
    "return 1 if total != 840",
)):
    raise SystemExit("regression must swap field order between two same-logical-line loops")
if "for_brace_field_owner_offset.elisa" not in smoke or \
        "for optimization in 0 2" not in smoke:
    raise SystemExit("behavioral smoke must compile and run the same-line swapped-field regression")

print("for-brace field owner offset source proof OK")
