"""Bind generic struct discovery and parameter collection to declaration offsets."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER = ROOT / "src/parser/parser_types_signature_clauses.elisa"
BACKEND = ROOT / "src/backend/codegen_template_registry.elisa"
FIXTURE = ROOT / "test/repro/generic_struct_same_line_owner.elisa"
SMOKE = ROOT / "test/parity/generic_struct_module_identity_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


parser = PARSER.read_text()
backend = BACKEND.read_text()
fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()

parser_owner = function_source(parser, "has_generic_parameter_owner")
record_struct = function_source(parser, "record_generic_struct_metadata")
register_structs = function_source(backend, "register_generic_structs")
if not all(fragment in parser_owner for fragment in (
    "generic_param_lines.count != parser.generic_param_names.count",
    "generic_param_lines.count != parser.generic_param_owner_offsets.count",
    "parser.generic_param_lines[index] == line",
    "parser.generic_param_owner_offsets[index] == owner_offset",
)):
    raise SystemExit("parser generic-struct discovery must match the declaration's exact owner offset")
if "Ast::decl_pos(declaration)" not in record_struct or \
        "parser.has_generic_parameter_owner(line, declaration_pos.offset)" not in record_struct:
    raise SystemExit("parser must register a struct as generic only when its own declaration has generic rows")
if not all(fragment in register_structs for fragment in (
    "Ast::decl_pos(struct_decl)",
    "file.generic_param_lines.count != file.generic_param_names.count",
    "file.generic_param_lines.count != file.generic_param_owner_offsets.count",
    "file.generic_param_lines[row] == struct_line",
    "file.generic_param_owner_offsets[row] == struct_pos.offset",
)):
    raise SystemExit("backend template registration must collect only the current struct's generic parameters")

if len([line for line in fixture.splitlines() if line.startswith("#line 0 ")]) != 3 or \
        not all(fragment in fixture for fragment in (
            "struct Box[T]:",
            "struct Pair[A, B]:",
            "struct Plain:",
            "Pair[i64, i32]",
        )):
    raise SystemExit("fixture must place distinct generic arities and a plain struct on logical line zero")
if "check_generic_struct_owner_offset_identity.py" not in smoke or \
        "generic_struct_same_line_owner" not in smoke:
    raise SystemExit("generic struct owner smoke must gate the source proof and line-zero fixture")
