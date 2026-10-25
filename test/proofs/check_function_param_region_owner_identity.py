"""Bind region-return parameter lookup to the function that owns each parameter row."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARAMS = ROOT / "src/parser/parser_func_params.elisa"
FUNCTIONS = ROOT / "src/parser/parser_types_function.elisa"
REGION_TYPES = ROOT / "src/parser/parser_types_signature.elisa"
REGION_LOCAL = ROOT / "src/parser/parser_stmt_control.elisa"
REGION_SCOPE = ROOT / "src/parser/parser_core_cursor.elisa"
CORE = ROOT / "src/parser/parser_core.elisa"
CORE_INIT = ROOT / "src/parser/parser_core_member_tables.elisa"
REGION = ROOT / "src/semantic/check_local_region_annotation.elisa"
SEMANTIC_API = ROOT / "src/semantic/semantic_api.elisa"
TYPE_TABLE = ROOT / "src/semantic/type_table.elisa"
UNIT_TEST = ROOT / "test/parity/parser_ast_extern.elisa"
SMOKE = ROOT / "test/parity/region_scope_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


params = PARAMS.read_text()
functions = FUNCTIONS.read_text()
region_types = REGION_TYPES.read_text()
region_local = REGION_LOCAL.read_text()
region_scope = REGION_SCOPE.read_text()
core = CORE.read_text()
core_init = CORE_INIT.read_text()
region = REGION.read_text()
semantic_api = SEMANTIC_API.read_text()
type_table = TYPE_TABLE.read_text()
unit_test = UNIT_TEST.read_text()
smoke = SMOKE.read_text()

param_list = function_source(params, "parse_param_list")
one_param = function_source(params, "parse_one_param")
param_region_index = function_source(region, "function_param_region_index")

if "function_offset: u32 = 0" not in param_list or \
        "has_function_owner: bool = false" not in param_list or \
        "parse_one_param(param_items, function_line, function_offset, has_function_owner)" not in param_list:
    raise SystemExit("parameter parsing must carry exact function identity into each parameter")
if "owner_offset: annotation_owner_offset" not in one_param or \
        "has_function_owner or function_line > 0" not in one_param:
    raise SystemExit("function parameter region rows must retain their owner offset, including line zero")
if "parse_param_list(param_items, token.line, token.start, true)" not in functions:
    raise SystemExit("ordinary function parameter parsing must pass its def-token offset")
region_arguments = function_source(region_types, "parser_region_type_arguments")
region_argument = function_source(region_types, "parser_region_type_argument")
function_decl = function_source(functions, "function_declaration")
if not all(fragment in region_arguments for fragment in (
    "owner_line: u32",
    "owner_offset: u32",
    "local_annotation_start: usize",
    "use_offset: u32",
)) or not all(fragment in region_argument for fragment in (
    "annotation.owner_offset == owner_offset",
    "annotation.line == owner_line",
    "annotation_index >= local_annotation_start",
    "annotation.owner_offset < use_offset",
    "use_offset < annotation.end_offset",
)):
    raise SystemExit("region type arguments must use exact function owners and active local-binder extents")
if not all(fragment in region_local for fragment in (
    "parser.active_function_region_line",
    "parser.active_function_region_offset",
    "parser.active_function_region_active",
    "parser.active_function_region_annotation_start",
)) or not all(fragment in function_decl for fragment in (
    "parser.active_function_region_annotation_start <- function_region_annotation_start",
    "parser.active_function_region_active <- true",
    "parser.active_function_region_active <- saved_region_function_active",
    "region_scope_end_offset: u32 = parser.lexical_block_end_offset(token.start)",
    "end_offset: region_scope_end_offset",
)):
    raise SystemExit("local declarations must carry the active function owner and close region rows by source offset")
if not all(fragment in core for fragment in (
    "active_function_region_line: mutable u32",
    "active_function_region_offset: mutable u32",
    "active_function_region_annotation_start: mutable usize",
    "active_function_region_active: mutable bool",
)) or not all(fragment in core_init for fragment in (
    "active_function_region_line: 0",
    "active_function_region_offset: 0",
    "active_function_region_annotation_start: 0",
    "active_function_region_active: false",
)):
    raise SystemExit("parser active-function region identity must be initialized")
if "lexical_block_end_offset" not in region_scope or \
        "region_binding_end_offsets.push(annotation.end_offset)" not in semantic_api or \
        "table.region_binding_end_offsets.count" not in type_table or \
        "use_offset < end_offset" not in type_table:
    raise SystemExit("closed region bindings must stop resolving at their exact source offset")
if "annotation.owner_offset == line.offset" not in param_region_index:
    raise SystemExit("region return inference must select parameter rows owned by the exact function")
if not all(fragment in unit_test for fragment in (
    "#line 0 first-region-owner.elisa",
    "#line 0 second-region-owner.elisa",
    "function_offsets[0] != function_offsets[1]",
    "parameter_rows == 2",
    "return_rows == 2",
)):
    raise SystemExit("parser AST regression must check same-line parameter and return-region owner offsets")
if "check_function_param_region_owner_identity.py" not in smoke:
    raise SystemExit("region scope smoke must gate the source-bound owner proof")
if not all(fragment in unit_test for fragment in (
    "region_type_argument_owner_test",
    "unrelated_owner.count == 0",
    "active_local.count == 1",
    "closed_local.count == 0",
    "active_parameter.count == 1",
)):
    raise SystemExit("parser AST regression must reject cross-function region names and closed local binders")
