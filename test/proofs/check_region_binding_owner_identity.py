"""Bind lexical region IDs to their exact owner offsets, including #line 0."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "src/semantic/semantic_api.elisa"
TYPE_TABLE = ROOT / "src/semantic/type_table.elisa"
LOCAL_REGION = ROOT / "src/semantic/check_local_region_annotation.elisa"
LOCAL_REGION_ENTRY = ROOT / "src/semantic/check_local_region_annotation_entry.elisa"
LOOP_ROOTS = ROOT / "src/semantic/check_loop_element_roots.elisa"
GENERIC_CALLS = ROOT / "src/semantic/resolve_generic_call_types.elisa"
REGION_STORES = ROOT / "src/semantic/region_escape_stores.elisa"
REGION_ASSIGNMENTS = ROOT / "src/semantic/region_escape_assignments.elisa"
REGION_RECOVERY = ROOT / "src/semantic/check_region_escape/walk_recovery.elisa"
REGION_ESCAPE = ROOT / "src/semantic/region_escape_provenance.elisa"
REGION_ESCAPE_STORED_REGIONS = ROOT / "src/semantic/region_escape_provenance/stored_regions.elisa"
DESTROYED_REGION = ROOT / "src/semantic/check_destroyed_region.elisa"
DESTROYED_INVALIDATION = ROOT / "src/semantic/check_destroyed_region/invalidation.elisa"
DESTROYED_VIEWS = ROOT / "src/semantic/check_destroyed_region/view_regions.elisa"
DESTROYED_LAMBDAS = ROOT / "src/semantic/check_destroyed_region/lambda_dependencies.elisa"
SYMBOL_TABLE = ROOT / "src/semantic/semantic_types_symbol_table.elisa"
PARSER_FUNCTION = ROOT / "src/parser/parser_types_function.elisa"
PARSER_BLOCKS = ROOT / "src/parser/parser_stmt_control_blocks_prefixed.elisa"
PARSER_CURSOR = ROOT / "src/parser/parser_core_cursor.elisa"
ATOM = ROOT / "test/atoms/compiler_semantic.elisa"
FIXTURE = ROOT / "test/repro/region_binding_owner_line0.elisa"
LOCAL_SHADOW_FIXTURE = ROOT / "test/repro/region_local_shadow_owner_offset.elisa"
SMOKE = ROOT / "test/parity/region_scope_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


api = API.read_text()
type_table = TYPE_TABLE.read_text()
local_region = LOCAL_REGION.read_text()
local_region_entry = LOCAL_REGION_ENTRY.read_text()
loop_roots = LOOP_ROOTS.read_text()
generic_calls = GENERIC_CALLS.read_text()
region_stores = REGION_STORES.read_text()
region_assignments = REGION_ASSIGNMENTS.read_text()
region_recovery = REGION_RECOVERY.read_text()
region_escape = REGION_ESCAPE.read_text()
region_escape_stored_regions = REGION_ESCAPE_STORED_REGIONS.read_text()
destroyed_sources = [
    DESTROYED_REGION.read_text(),
    DESTROYED_INVALIDATION.read_text(),
    DESTROYED_VIEWS.read_text(),
    DESTROYED_LAMBDAS.read_text(),
]
symbol_table = SYMBOL_TABLE.read_text()
parser_function = PARSER_FUNCTION.read_text()
parser_blocks = PARSER_BLOCKS.read_text()
parser_cursor = PARSER_CURSOR.read_text()
atom = ATOM.read_text()
fixture = FIXTURE.read_text()
local_shadow_fixture = LOCAL_SHADOW_FIXTURE.read_text()
smoke = SMOKE.read_text()

register = function_source(api, "register_region_type_names")
lookup = function_source(type_table, "type_region_binding_id_at")
generic_region = function_source(generic_calls, "region_type_id")
region_escape_param = function_source(region_escape, "region_escape_is_region_param")
destroyed_lookup = function_source(destroyed_sources[0], "region_binding_id_at")
destroyed_function_regions = function_source(destroyed_sources[0], "function_regions_of_name")
destroyed_lambda_declarations = function_source(destroyed_sources[3], "check_destroyed_region_declarations")

if not all(fragment in symbol_table for fragment in (
    "region_binding_owner_offsets: mutable darray[u32] = []",
    "region_binding_end_offsets: mutable darray[u32] = []",
)):
    raise SystemExit("region binding storage must retain each parser owner offset")
if not all(fragment in register for fragment in (
    "table.region_binding_owner_offsets[binding_index] == annotation.owner_offset",
    "table.region_binding_owner_offsets.push(annotation.owner_offset)",
    "table.region_binding_end_offsets.push(annotation.end_offset)",
    "table.region_binding_end_offsets[binding_index] == annotation.end_offset",
)):
    raise SystemExit("region binding registration must deduplicate by exact owner identity and close offset")
if not all(fragment in lookup for fragment in (
    "use_offset: u32",
    "table.region_binding_names.count != table.region_binding_owner_offsets.count",
    "table.region_binding_names.count != table.region_binding_end_offsets.count",
    "owner_offset <= use_offset",
    "use_offset < end_offset if end_offset != 0 else table.region_binding_end_lines[binding_index] == 0 or use_line <= table.region_binding_end_lines[binding_index]",
    "owner_offset >= found_offset",
)):
    raise SystemExit("region lookup must prefer the exclusive source end and use line bounds only as fallback")
if not all(fragment in region_escape_param for fragment in (
    'annotation.name == "__region_param"',
    "annotation.owner_offset <= use_offset",
    "annotation.end_offset != 0 and use_offset < annotation.end_offset",
    "annotation.end_offset == 0 and (annotation.end_line == 0 or line <= annotation.end_line)",
)):
    raise SystemExit("region escape inference must keep generic region parameters within their source interval")
if not all(fragment in destroyed_lookup for fragment in (
    "use_offset: u32 = 0",
    "use_offset_known: bool = false",
    "use_offset_known and annotation.owner_offset <= use_offset",
    "annotation.end_offset == 0 or use_offset < annotation.end_offset",
    "candidate_offset: u32 = annotation.owner_offset if use_offset_known else annotation.line",
    "candidate_offset >= found_offset",
)):
    raise SystemExit("destroyed-region lookup must choose the latest active binder using source offsets")
if "use_offset_known: bool = false" not in destroyed_function_regions or \
        "annotation.owner_offset <= use_offset" not in destroyed_function_regions or \
        "use_offset_known" not in destroyed_function_regions or \
        "region_binding_id_at(annotations, annotation.region, function_line, annotation.line, annotation.owner_offset, true)" not in destroyed_sources[0]:
    raise SystemExit("destroyed-region name projections must preserve explicit offset presence, including annotation-owner offsets")
destroyed_call_arguments = []
for destroyed_source in destroyed_sources:
    destroyed_call_arguments.extend(re.findall(r"region_binding_id_at\(([^)]*)\)", destroyed_source))
destroyed_call_arguments = [call for call in destroyed_call_arguments if "annotations:" not in call]
if not destroyed_call_arguments or any(
    len(call.split(",")) < 6 or "true" not in call.split(",")[-1] for call in destroyed_call_arguments
):
    raise SystemExit("destroyed-region call sites must mark their source offsets as present, including byte zero")
if "function_regions_of_name(file.local_region_annotations, parameter.name, line.line, line.line, parameter_regions, line.offset, true)" not in destroyed_lambda_declarations:
    raise SystemExit("lambda parameter region seeding must query function bindings at the declaration offset, including byte zero")
scope = function_source(local_region, "local_region_is_in_scope")
local_annotation_lookup = function_source(local_region, "local_region_annotation_of")
if "use_offset: u32" not in scope or "annotation.owner_offset > use_offset" not in scope or \
        "use_offset < annotation.end_offset" not in scope or \
        "local_region_is_in_scope(file.local_region_annotations, annotation.region, annotation.line, annotation.owner_offset)" not in local_region_entry or \
        "local_region_is_in_scope(shadows, annotation.name, annotation.line, annotation.offset)" not in loop_roots:
    raise SystemExit("region qualifier and loop-shadow checks must use exact source scope bounds")
if not all(fragment in local_annotation_lookup for fragment in (
    "before_offset: u32 = 0",
    "before_offset_known: bool = false",
    "for annotation in annotations |found, found_offset, before_offset, before_offset_known|:",
    "source_visible: bool = annotation.owner_offset <= before_offset and (before_offset < annotation.end_offset if annotation.end_offset != 0 else annotation.end_line == 0 or before_line <= annotation.end_line)",
    "line_visible: bool = annotation.line <= before_line and (annotation.end_line == 0 or before_line <= annotation.end_line)",
    "visible: bool = source_visible if before_offset_known else line_visible",
    "candidate_offset: u32 = annotation.owner_offset if before_offset_known else annotation.line",
    "candidate_offset >= found_offset",
)):
    raise SystemExit("local value-region lookup must choose the newest annotation active at the exact source offset")
if not all(fragment in region_escape for fragment in (
    "Expr.Ident(name, ident_line):",
    "return local_region_name(annotations, name, line, ident_line.offset, true)",
)) or "return local_region_name(annotations, name, line, ident_line.offset, true)" not in region_escape_stored_regions:
    raise SystemExit("region escape provenance must resolve local value annotations at each identifier's source offset")
if "local_region_annotation_of(annotations, name, before_line, before_offset, before_offset_known)" not in region_escape:
    raise SystemExit("local region name lookup must preserve explicit byte-zero offset presence")
if "local_region_annotation_of(annotations, name, line.line, line.offset, true)" not in local_region or \
        "local_region_annotation_of(annotations, source_name, position.line, position.offset, true)" not in destroyed_sources[0] or \
        "local_region_annotation_of(annotations, receiver, line, use_offset, true)" not in region_stores or \
        region_stores.count("local_region_annotation_of(annotations, receiver, line, use_offset, true)") != 2 or \
        "local_region_name(annotations, growth.receiver, line, use_offset, true)" not in region_stores or \
        "local_region_name(annotations, target_name, line, target_pos.offset, true)" not in region_assignments or \
        "local_region_name(annotations, name, line.line, line.offset, true)" not in region_recovery:
    raise SystemExit("semantic local-region lookup callers must mark available AST offsets as present, including byte zero")
if "argument_line.line, argument_line.offset" not in type_table:
    raise SystemExit("generic region selector interning must pass the expression's source offset")
if "type_region_binding_id_at(region_name, use_line, use_offset, table)" not in generic_region or \
        "callee.line, callee.offset, table" not in generic_calls or \
        "ident_line.line, ident_line.offset, table" not in generic_calls:
    raise SystemExit("generic-call region substitution must use exact declaration and argument positions")
if "type_region_binding_id_at(region, line, offset, table)" not in region_stores or \
        "region_escape_region_binding_id(name, position.line, position.offset, table)" not in region_stores:
    raise SystemExit("region escape projections must retain the source offset of each region use")
if "owner_offset: function_offset" not in parser_function or \
        "owner_offset: first_token.start" not in parser_blocks:
    raise SystemExit("region parser producers must retain declaration token offsets")
if not all(fragment in parser_function for fragment in (
    "for annotation_index in function_region_annotation_start..<parser.local_region_annotations.count",
    "if region_annotation.end_offset == 0:",
    "end_offset: region_scope_end_offset",
)):
    raise SystemExit("function parsing must close every still-open local annotation row at the function's source boundary")
block_annotation_closer = function_source(parser_cursor, "close_arena_local_region_annotations")
if not all(fragment in block_annotation_closer for fragment in (
    "if region_annotation.end_offset == 0 and region_annotation.name != \"__region_local\":",
    "annotation_end_line: u32 = parser.lexical_block_end_line(region_annotation.line)",
    "annotation_end_offset: u32 = parser.lexical_block_end_offset(region_annotation.owner_offset)",
    "end_offset: annotation_end_offset",
)) or not all(fragment in parser_blocks for fragment in (
    "region_row_index: usize = parser.local_region_annotations.count",
    "region_end_offset: u32 = parser.lexical_block_end_offset(first_token.start)",
    "end_offset: region_end_offset",
)):
    raise SystemExit("block parsing must close local value rows at dedent and close region rows with their dedicated binder")
if not all(fragment in atom for fragment in (
    "line: 0, owner_offset: 100, end_line: 0, end_offset: 180",
    "line: 0, owner_offset: 200, end_line: 0, end_offset: 300",
    "type_region_binding_id_at(\"shared\", 0, 150, region_identity_table)",
    "type_region_binding_id_at(\"shared\", 0, 180, region_identity_table)",
    "type_region_binding_id_at(\"shared\", 0, 200, region_identity_table)",
    "type_region_binding_id_at(\"shared\", 0, 250, region_identity_table)",
    "closed_boundary_region_id.value != 0",
    "first_region_id.value == second_region_id.value",
    "region: \"logical\", line: 1, owner_offset: 400, end_line: 5, end_offset: 450",
    "type_region_binding_id_at(\"logical\", 99, 425, region_identity_table)",
    "type_region_binding_id_at(\"logical\", 99, 450, region_identity_table)",
    "logical_line_reset_region_id.value == 0 or logical_line_reset_end_region_id.value != 0",
    "owner_offset: 0, end_line: 10, end_offset: 20",
    "owner_offset: 5, end_line: 10, end_offset: 30",
    "local_region_annotation_of(byte_zero_local_rows, \"zero_value\", 99, 0, true)",
    'present_byte_zero_local.region != "first"',
    'owner_offset: 0, end_line: 0, end_offset: 100',
    'owner_offset: 100, end_line: 0, end_offset: 200',
    'region_binding_id_at(destroyed_region_identity_rows, "shared", 0, 99, 0, true)',
    'region_binding_id_at(destroyed_region_identity_rows, "shared", 0, 99, 100, true)',
    'byte_zero_function_region_id != 1 or later_function_region_id != 2',
)):
    raise SystemExit("semantic atom must prove binder identity, byte-zero lookup, exclusive closure, and offset precedence across a #line reset")
if fixture.count("#line 0 ") != 2 or not all(fragment in fixture for fragment in (
    "def first_region_owner[@r]",
    "def second_region_owner[@r]",
)):
    raise SystemExit("regression fixture must contain distinct same-spelled #line 0 region owners")
if "check_region_binding_owner_identity.py" not in smoke or \
        "region_binding_owner_line0.elisa" not in smoke:
    raise SystemExit("region-scope smoke must gate the source proof and #line 0 fixture")
if not all(fragment in local_shadow_fixture for fragment in (
    "def first_local_owner() -> void:",
    "if true:",
    "region inner(64):",
    "buf: darray[i64] @inner = []",
    "after: darray[i64] @outer = buf",
    "#line 0 second-local-owner.elisa",
    "def second_local_owner() -> void:",
)) or 'clean "$(cat "$REPO_ROOT/test/repro/region_local_shadow_owner_offset.elisa")"' not in smoke:
    raise SystemExit("region-scope smoke must compile the nested local-shadow and cross-function #line-zero fixture")
if destroyed_sources[2].count('annotation.owner_offset == symbol.offset') != 2:
    raise SystemExit("destroyed-region return contracts must join __region_return rows by exact declaration offset in indexed and fallback paths")
