"""Bind zeroed generic lookups to exact declaration offsets, including logical line zero."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SEMANTIC = ROOT / "src/semantic/check_uninitialized_zeroed.elisa"
TYPE_ALIASES = ROOT / "src/semantic/check_uninitialized_zeroed/type_aliases.elisa"
ZEROED = ROOT / "src/semantic/check_zeroed_value_positions.elisa"
ZEROED_WALK = ROOT / "src/semantic/check_zeroed_value_positions_places.elisa"
SYMBOL_TABLE = ROOT / "src/semantic/semantic_types_symbol_table.elisa"
TABLE_CONSTRUCTOR = ROOT / "src/semantic/semantic_types.elisa"
TABLE_SETUP = ROOT / "src/semantic/semantic_api/table_setup.elisa"
DIAGNOSTIC_OUTPUT = ROOT / "src/semantic/semantic_api/diagnostic_output.elisa"
CALLER = ROOT / "src/semantic/check_uninitialized_zeroed/bindings.elisa"
RESOLVER = ROOT / "src/semantic/resolve_expr_walk.elisa"
RESOLVE_TYPES = ROOT / "src/semantic/resolve_types.elisa"
GENERIC_CALL_TYPES = ROOT / "src/semantic/resolve_generic_call_types.elisa"
POINTER_ERASURE = ROOT / "src/semantic/check_pointer_erasure_cast.elisa"
POINTER_ERASURE_BUFFERS = ROOT / "src/semantic/check_pointer_erasure_cast_buffers.elisa"
BORROW_CAPTURE = ROOT / "src/semantic/check_borrow_after_move/store_capture.elisa"
TRY_CALLABLE_ROWS = ROOT / "src/semantic/check_try_fallible/callable_rows.elisa"
SEMANTIC_API = ROOT / "src/semantic/semantic_api.elisa"
STRUCT_CAPTURE = ROOT / "src/parser/parser_types_signature.elisa"
STRUCT_METADATA = ROOT / "src/parser/parser_types_signature_clauses.elisa"
FUNCTION_CAPTURE = ROOT / "src/parser/parser_types_function.elisa"
TEMPLATE_REGISTRY = ROOT / "src/backend/codegen_template_registry.elisa"
IMPL_CAPTURE = ROOT / "src/parser/parser_decl_impl.elisa"
AST_SIDE_TABLES = ROOT / "src/parser/ast_side_tables.elisa"
FIXTURE = ROOT / "test/repro/zeroed_generic_owner_collision_line_zero.elisa"
FUNCTION_FIXTURE = ROOT / "test/repro/zeroed_generic_function_line_zero.elisa"
SMOKE = ROOT / "test/parity/zeroed_reference_safety_smoke.sh"
TYPEARG_SMOKE = ROOT / "test/parity/cast_typearg_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


semantic = SEMANTIC.read_text()
type_aliases = TYPE_ALIASES.read_text()
zeroed = ZEROED.read_text()
zeroed_walk = ZEROED_WALK.read_text()
symbol_table = SYMBOL_TABLE.read_text()
table_constructor = TABLE_CONSTRUCTOR.read_text()
table_setup = TABLE_SETUP.read_text()
diagnostic_output = DIAGNOSTIC_OUTPUT.read_text()
caller = CALLER.read_text()
resolver = RESOLVER.read_text()
resolve_types = RESOLVE_TYPES.read_text()
generic_call_types = GENERIC_CALL_TYPES.read_text()
pointer_erasure = POINTER_ERASURE.read_text()
pointer_erasure_buffers = POINTER_ERASURE_BUFFERS.read_text()
borrow_capture = BORROW_CAPTURE.read_text()
try_callable_rows = TRY_CALLABLE_ROWS.read_text()
semantic_api = SEMANTIC_API.read_text()
struct_capture_source = STRUCT_CAPTURE.read_text()
struct_metadata_source = STRUCT_METADATA.read_text()
function_capture_source = FUNCTION_CAPTURE.read_text()
template_registry = TEMPLATE_REGISTRY.read_text()
impl_capture_source = IMPL_CAPTURE.read_text()
ast_side_tables = AST_SIDE_TABLES.read_text()
fixture = FIXTURE.read_text()
function_fixture = FUNCTION_FIXTURE.read_text()
smoke = SMOKE.read_text()
typearg_smoke = TYPEARG_SMOKE.read_text()

if "generic_param_owner_offsets: mutable darray[u32]" not in symbol_table or \
        "generic_param_owner_offsets: []," not in table_constructor or \
        "region_generic_function_offsets: []," not in table_constructor or \
        "table.generic_param_owner_offsets <- file.generic_param_owner_offsets" not in table_setup or \
        diagnostic_output.count("table.generic_param_owner_offsets <- file.generic_param_owner_offsets") != 2:
    raise SystemExit("generic owner offsets must reach every semantic SymbolTable construction path")

nominal_scan = function_source(semantic, "zeroed_find_nominal_in_owner")
nominal_index = function_source(semantic, "zeroed_find_nominal_in_owner_index")
nominal_for_type = function_source(semantic, "zeroed_find_nominal_in_owner_for_type")
if not all(fragment in nominal_scan for fragment in (
    "declaration_offset: mutable u32&",
    "declaration_offset <- line.offset",
)) or not all(fragment in nominal_index for fragment in (
    "declaration_offset: mutable u32&",
    "declaration_offset <- symbol.offset",
)) or not all(fragment in nominal_for_type for fragment in (
    "declaration_offset: mutable u32&",
    "zeroed_find_nominal_in_owner_index(table, index_owner, name, declaration_line, declaration_offset, matches)",
)):
    raise SystemExit("nominal owner lookup must return exact AST or indexed symbol offsets")

struct_field = function_source(zeroed, "zeroed_struct_field_type")
nominal_protocol = function_source(zeroed, "zeroed_protocol_check_nominal_contents")
if not all(fragment in struct_field for fragment in (
    "zeroed_find_nominal_in_owner(alias_declarations, head_owner, head_name, struct_line, struct_offset, struct_matches)",
    "table.generic_param_owner_offsets[table_index] == struct_offset",
)) or "struct_line == 0" in struct_field:
    raise SystemExit("zeroed struct-field lookup must select generic rows by exact declaration offset at line zero")
if not all(fragment in nominal_protocol for fragment in (
    "zeroed_find_nominal_in_owner(alias_declarations, head_owner, type_name, nominal_line, nominal_offset, nominal_matches)",
    "table.generic_param_owner_offsets[table_index] == nominal_offset",
)):
    raise SystemExit("protocol nominal traversal must select generic rows by exact declaration offset")
if "table.generic_param_owner_offsets[generic_index] == function_pos.offset" not in zeroed:
    raise SystemExit("explicit generic call substitution must select the callee's exact generic owner")

function_generic = function_source(type_aliases, "zeroed_is_function_generic_type_name")
if not all(fragment in function_generic for fragment in (
    "function_offset: u32",
    "table.generic_param_owner_offsets[index] == function_offset",
    "table.generic_param_names[index] == name",
)) or "function_line == 0" in function_generic:
    raise SystemExit("function-generic identity must use declaration line and owner offset, including line zero")
if type_aliases.count("table.generic_param_owner_offsets[table_index] == struct_offset") != 2:
    raise SystemExit("both Index and IndexN aggregate paths must join generic rows by owner offset")
if "line.line, declarations, alias_declarations, active_enum_index, current_module, alias_names, alias_values, table, false, line.offset" not in caller:
    raise SystemExit("function declaration offset must reach uninitialized-zeroed generic classification")
if "line.line, line.offset, current_module" not in zeroed_walk:
    raise SystemExit("zeroed value traversal must carry its enclosing function's exact offset")
specialization = function_source(resolver, "check_non_generic_specialization")
if not all(fragment in specialization for fragment in (
    "table.generic_param_lines.count != table.generic_param_owner_offsets.count",
    "table.generic_param_lines[generic_index] == symbol.line",
    "table.generic_param_owner_offsets[generic_index] == symbol.offset",
    "table.region_generic_function_lines.count != table.region_generic_function_offsets.count",
    "table.region_generic_function_lines[region_index] == symbol.line",
    "table.region_generic_function_offsets[region_index] == symbol.offset",
)) or "any generic_line in table.generic_param_lines where generic_line == symbol.line" in specialization:
    raise SystemExit("non-generic specialization must classify type and region generics by exact symbol identity")
return_generic = function_source(resolve_types, "function_generic_param_named")
return_type_walk = function_source(resolve_types, "type_id_contains_function_generic")
if not all(fragment in return_generic for fragment in (
    "offset: u32",
    "table.generic_param_owner_offsets[generic_index] == offset",
)) or not all(fragment in return_type_walk for fragment in (
    "function_offset: u32",
    "function_line, function_offset, interned_name(type_id, table)",
    "function_line, function_offset, table)",
)) or "symbol.line, symbol.offset, table" not in resolve_types:
    raise SystemExit("structural return generic classification must preserve exact function identity")
if "function_generic_param_named(table, function_line, function_offset, interned_name(formal_id, table))" not in generic_call_types or \
        "function_generic_param_named(table, function_line, function_offset, interned_name(type_id, table))" not in generic_call_types or \
        "type_id_contains_function_generic(parameter_type_id, callee.line, callee.offset, table)" not in generic_call_types:
    raise SystemExit("generic call substitutions must use the selected callee's exact identity")
if "function_generic_param_named(table, function_line, function_offset, target_name)" not in pointer_erasure or \
        "pointer_erasure_generic_line(table.generic_param_lines, table.generic_param_owner_offsets, function_line, function_offset)" not in pointer_erasure or \
        "line.line, line.offset, params" not in pointer_erasure_buffers or \
        "generic_lines, generic_offsets, line.line, line.offset" not in pointer_erasure_buffers:
    raise SystemExit("pointer-erasure generic classification must carry exact function identity")
if "function_generic_param_named(table, owner_symbol.line, owner_symbol.offset, type_name)" not in borrow_capture:
    raise SystemExit("borrow-after-move generic shadowing must use its owner declaration offset")
if "call_return_function_offset <- symbol.offset" not in try_callable_rows or \
        "type_id_contains_function_generic(call_return_type_id, call_return_function_line, call_return_function_offset, table)" not in try_callable_rows:
    raise SystemExit("try-call return type classification must preserve the selected function offset")

record_struct_generic = function_source(struct_capture_source, "record_struct_generic_param")
capture_struct_generic = function_source(struct_capture_source, "capture_struct_generic_params")
record_generic_struct = function_source(struct_metadata_source, "record_generic_struct_metadata")
generic_struct_owner = function_source(struct_metadata_source, "has_generic_parameter_owner")
register_generic_structs = function_source(template_registry, "register_generic_structs")
capture_function_generic = function_source(function_capture_source, "capture_function_generic_params")
capture_impl_generic = function_source(impl_capture_source, "capture_impl_generic_params")
if not all(fragment in record_struct_generic for fragment in (
    "generic_param_lines <- parser.generic_param_lines.push(struct_line)",
    "generic_param_names <- parser.generic_param_names.push(parameter_name)",
    "generic_param_owner_offsets <- parser.generic_param_owner_offsets.push(owner_offset)",
)) or "parser.record_struct_generic_param(struct_line, owner_offset" not in capture_struct_generic:
    raise SystemExit("struct generic capture must append the declaration owner offset in parallel")
if "Ast::decl_pos(declaration)" not in record_generic_struct or \
        "parser.has_generic_parameter_owner(line, declaration_pos.offset)" not in record_generic_struct or \
        "parser.generic_param_owner_offsets[index] == owner_offset" not in generic_struct_owner:
    raise SystemExit("parser must discover generic structs from the exact declaration owner")
if not all(fragment in register_generic_structs for fragment in (
    "Ast::decl_pos(struct_decl)",
    "file.generic_param_lines.count != file.generic_param_names.count",
    "file.generic_param_lines.count != file.generic_param_owner_offsets.count",
    "file.generic_param_lines[row] == struct_line",
    "file.generic_param_owner_offsets[row] == struct_pos.offset",
)):
    raise SystemExit("backend generic struct templates must collect only their own parameter rows")
if 'python3 "$ROOT/test/proofs/check_zeroed_generic_owner_identity.py"' not in smoke:
    raise SystemExit("zeroed reference smoke must run the source-bound generic-owner proof")
if not all(fragment in capture_function_generic for fragment in (
    "generic_param_lines <- parser.generic_param_lines.push(function_line) if is_generic_name",
    "generic_param_owner_offsets <- parser.generic_param_owner_offsets.push(function_offset) if is_generic_name",
    "generic_param_lines <- parser.generic_param_lines.push(function_line + GENERIC_PARAM_BOUND_FLAG) if is_bound_name",
    "generic_param_owner_offsets <- parser.generic_param_owner_offsets.push(function_offset) if is_bound_name",
)):
    raise SystemExit("function generic and bound rows must retain their declaration owner offset")
if "owner_offset: u32" not in ast_side_tables or \
        "owner_offset: function_offset" not in capture_function_generic:
    raise SystemExit("region generic annotations must retain their function declaration offset")
region_registration = function_source(semantic_api, "register_region_type_names")
if not all(fragment in region_registration for fragment in (
    "table.region_generic_function_lines[owner_index] == annotation.line",
    "table.region_generic_function_offsets[owner_index] == annotation.owner_offset",
    "table.region_generic_function_offsets.push(annotation.owner_offset)",
)):
    raise SystemExit("region-only generic declarations must be indexed by line and owner offset")
if not all(fragment in capture_impl_generic for fragment in (
    "member_offset: u32 = member_token.start",
    "generic_param_lines <- parser.generic_param_lines.push(member_line)",
    "generic_param_owner_offsets <- parser.generic_param_owner_offsets.push(member_offset)",
)):
    raise SystemExit("impl generic rows must use the owning method's source offset")

directives = [line for line in fixture.splitlines() if line.startswith("#line 0 ")]
if len(directives) != 3 or not all(fragment in fixture for fragment in (
    "module A:\n    public:\n#line 0 zeroed-generic-owner-a.elisa\n        struct RefBox[T]:",
    "module B:\n    public:\n#line 0 zeroed-generic-owner-b.elisa\n        struct RefBox[U]:",
    "A::RefBox[mutable i64&]{pointer: zeroed}",
)):
    raise SystemExit("line-zero fixture must collide same-named generic declarations across module owners")
if "zeroed_generic_owner_collision_line_zero.elisa" not in smoke:
    raise SystemExit("zeroed reference smoke must cover the same-line generic owner collision")
if not function_fixture.startswith("#line 0 ") or "def bad[T]() -> i64:" not in function_fixture or \
        "value: T = zeroed" not in function_fixture or "zeroed_generic_function_line_zero.elisa" not in smoke:
    raise SystemExit("zeroed function-generic identity must cover a #line 0 T initializer")
if "same-line generic declaration made plain appear generic" not in typearg_smoke or \
        "same-line region-generic declaration made plain appear generic" not in typearg_smoke:
    raise SystemExit("type-application smoke must cover both ordinary and region generic owner collisions")
