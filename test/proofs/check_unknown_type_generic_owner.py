"""Bind unknown-type and protocol generic exemptions to declaration owners."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
UNKNOWN_SOURCE = ROOT / "src/semantic/check_unknown_type_name.elisa"
STRUCT_SOURCE = ROOT / "src/semantic/resolve_struct_layout.elisa"
FIXTURE = ROOT / "test/repro/unknown_type_generic_owner.elisa"
SMOKE = ROOT / "test/parity/unknown_type_generic_owner_smoke.sh"
GATE = ROOT / "test/parity/diagnostics_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


unknown = UNKNOWN_SOURCE.read_text()
structs = STRUCT_SOURCE.read_text()
fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()
gate = GATE.read_text()

owner_lookup = function_source(unknown, "unknown_type_is_generic")
if not all(fragment in owner_lookup for fragment in (
    "owner_line: u32, owner_offset: u32",
    "table.generic_param_names.count != table.generic_param_lines.count",
    "table.generic_param_names.count != table.generic_param_owner_offsets.count",
    "table.generic_param_lines[index] < 2147483648",
    "table.generic_param_lines[index] == owner_line",
    "table.generic_param_owner_offsets[index] == owner_offset",
    "table.generic_param_names[index] == name",
)):
    raise SystemExit("generic suppression must require aligned exact (line, offset, name) metadata")

unresolved = function_source(unknown, "unknown_type_is_unresolved")
if "unknown_type_is_generic(name, owner_line, owner_offset, table)" not in unresolved or "name.len == 1" not in unresolved:
    raise SystemExit("unknown-type lookup must be owner-scoped while preserving one-letter compatibility")

protocol_name = function_source(unknown, "is_protocol_constraint_name")
if "unknown_type_is_generic(name, owner_line, owner_offset, table)" not in protocol_name or "generic_param_name_index_count" in protocol_name:
    raise SystemExit("protocol constraint exemption must use exact owner metadata, not a global name index")

annotation = function_source(unknown, "check_type_annotation")
if not all(fragment in annotation for fragment in (
    "owner_line: u32, owner_offset: u32",
    "is_protocol_constraint_name(type_name, owner_line, owner_offset, table)",
    "unknown_type_is_unresolved(type_name, file, owner_line, owner_offset, table)",
)):
    raise SystemExit("direct annotations must pass their declaration owner to both classifiers")

elements = function_source(unknown, "check_interned_elements")
element_walk = function_source(unknown, "check_annotation_element_types_with")
if not all(fragment in elements for fragment in (
    "owner_line: u32, owner_offset: u32",
    "unknown_type_is_unresolved(element_name, file, owner_line, owner_offset, table)",
    "depth + 1, owner_line, owner_offset",
)) or "line, 0, owner_line, owner_offset" not in element_walk:
    raise SystemExit("nested and interned element annotations must retain the exact owner pair")

body = function_source(unknown, "check_unknown_types_in_body")
if not all(fragment in body for fragment in (
    "owner_line: u32, owner_offset: u32",
    "check_type_annotation(type_expression, owner_line, owner_offset",
    "check_annotation_element_types_with(type_expression, line.line, owner_line, owner_offset",
    "then_body, scoped_names, owner_line, owner_offset",
    "arm.body, scoped_names, owner_line, owner_offset",
)):
    raise SystemExit("nested statement annotations must retain their enclosing function owner")

declarations = function_source(unknown, "check_unknown_type_name_in")
if not all(fragment in declarations for fragment in (
    "parameter.type_expression, line.line, line.offset",
    "return_type_expr, line.line, line.offset",
    "body, sibling_params, line.line, line.offset",
    "type_expression, const_line.line, const_line.offset",
    "payload_type, enum_line.line, enum_line.offset",
)):
    raise SystemExit("declaration traversal must pass source offsets into direct and nested annotation walkers")

struct_generic = function_source(structs, "is_unresolved_type")
struct_layout = function_source(structs, "check_struct_layout")
struct_walk = function_source(structs, "validate_struct_layouts_range")
if "unknown_type_is_generic(name, owner_line, owner_offset, table)" not in struct_generic or not all(fragment in struct_layout for fragment in (
    "owner_pos: Ast::Pos",
    "is_protocol_constraint_name(type_name, owner_pos.line, owner_pos.offset, table)",
    "is_unresolved_type(type_name, owner_pos.line, owner_pos.offset, table)",
)) or "check_struct_layout(struct_name, members, line, table)" not in struct_walk:
    raise SystemExit("struct field resolution must use the owning struct position for generic and protocol lookup")

if fixture.count("#line 37 ") != 2 or fixture.count("#line 48 ") != 2 or \
        fixture.count("#line 70 ") != 2 or fixture.count("#line 80 ") != 2 or \
        fixture.count("#line 90 ") != 2 or fixture.count("#line 0 ") != 2 or \
        "def generic_direct[Ghost](value: Ghost)" not in fixture or \
        "nested: Element = zeroed" not in fixture or \
        "wrapped: darray[Element] = []" not in fixture or \
        "struct BadBox:" not in fixture or \
        "struct BadConstraintBox:" not in fixture or \
        "def bad_protocol(value: Constraint)" not in fixture or \
        "def bad_zero(value: ZeroName)" not in fixture or \
        "def legacy_letter(value: Z)" not in fixture:
    raise SystemExit("fixture must cover same-line direct, nested, element, struct, protocol and line-zero cases")

if 'python3 "$REPO_ROOT/test/proofs/check_unknown_type_generic_owner.py"' not in smoke or \
        '"$REPO_ROOT/test/parity/unknown_type_generic_owner_smoke.sh"' not in gate:
    raise SystemExit("owner-scoping proof and regression smoke must be wired into the diagnostic gate")
