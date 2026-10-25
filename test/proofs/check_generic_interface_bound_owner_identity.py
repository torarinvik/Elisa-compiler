"""Bind generic interface-bound consumers to exact declaration offsets."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SEMANTIC = ROOT / "src/semantic/check_generic_interface_bounds.elisa"
SYMBOL_TABLE = ROOT / "src/semantic/semantic_types_symbol_table.elisa"
TABLE_CONSTRUCTOR = ROOT / "src/semantic/semantic_types.elisa"
TABLE_SETUP = ROOT / "src/semantic/semantic_api/table_setup.elisa"
DIAGNOSTIC_OUTPUT = ROOT / "src/semantic/semantic_api/diagnostic_output.elisa"
PARSER_FUNCTIONS = ROOT / "src/parser/parser_types_function.elisa"
PARSER_IMPL = ROOT / "src/parser/parser_decl_impl.elisa"
PARSER_PROTOCOL = ROOT / "src/parser/parser_protocol_parameters.elisa"
FIRM_ARGUMENT_CHECK = ROOT / "src/semantic/check_firm_arg_type_mismatch.elisa"
FIXTURE = ROOT / "test/repro/generic_interface_bound_owner_line0.elisa"
SMOKE = ROOT / "test/parity/generic_interface_bound_owner_line0_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


semantic = SEMANTIC.read_text()
symbol_table = SYMBOL_TABLE.read_text()
table_constructor = TABLE_CONSTRUCTOR.read_text()
table_setup = TABLE_SETUP.read_text()
diagnostic_output = DIAGNOSTIC_OUTPUT.read_text()
parser_functions = PARSER_FUNCTIONS.read_text()
parser_impl = PARSER_IMPL.read_text()
parser_protocol = PARSER_PROTOCOL.read_text()
firm_argument_check = FIRM_ARGUMENT_CHECK.read_text()
fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()

if "generic_param_owner_offsets: mutable darray[u32]" not in symbol_table or \
        "generic_param_owner_offsets: []," not in table_constructor or \
        "table.generic_param_owner_offsets <- file.generic_param_owner_offsets" not in table_setup or \
        diagnostic_output.count("table.generic_param_owner_offsets <- file.generic_param_owner_offsets") != 2:
    raise SystemExit("generic parameter owner offsets must reach every semantic table construction path")
if not all(fragment in parser_functions for fragment in (
    "parser.generic_param_owner_offsets <- parser.generic_param_owner_offsets.push(function_offset) if is_generic_name",
    "parser.generic_param_owner_offsets <- parser.generic_param_owner_offsets.push(function_offset) if is_bound_name",
)):
    raise SystemExit("function parameters and interface-bound rows must retain their declaration offset")
if parser_protocol.count("parser.generic_param_owner_offsets <- parser.generic_param_owner_offsets.push(owner_offset)") != 2:
    raise SystemExit("synthesized protocol parameters and bounds must retain their method declaration offset")
impl_generics = function_source(parser_impl, "capture_impl_generic_params")
protocol_parameter = function_source(parser_protocol, "lower_protocol_parameter")
if "parser.generic_param_owner_offsets <- parser.generic_param_owner_offsets.push(member_offset)" not in impl_generics or \
        "parser.generic_param_owner_offsets <- parser.generic_param_owner_offsets.push(owner_offset)" not in protocol_parameter:
    raise SystemExit("impl and synthesized protocol generic rows must retain their method declaration offsets")

owner_identity = function_source(semantic, "generic_owner_identity_is_unique")
owner_bounds = function_source(semantic, "generic_owner_has_interface_bounds")
caller_bound = function_source(semantic, "type_param_satisfies_bound")
inferred_check = function_source(semantic, "check_inferred_protocol_argument")
specialization_check = function_source(semantic, "check_interface_specialization")
expression_walk = function_source(semantic, "walk_interface_bound_expression")
statement_walk = function_source(semantic, "walk_interface_bound_statements")
firm_generic = function_source(firm_argument_check, "firm_parameter_type_is_generic")
if not all(fragment in owner_identity for fragment in (
    "line >= 2147483648",
    "symbol.id.value.usize() < table.builtin_symbol_count",
    "symbol.line != line or symbol.offset != owner_offset",
    "owner_count == 1.usize()",
)) or "line == 0" in owner_identity:
    raise SystemExit("generic owner identity must admit line zero and select a unique line/offset pair")
if not all(fragment in owner_bounds for fragment in (
    "owner_offset: u32",
    "table.generic_param_owner_offsets[row] == owner_offset",
    "table.generic_bound_index_empty",
)):
    raise SystemExit("ambiguous-name bound detection must match exact owner offsets")
if not all(fragment in caller_bound for fragment in (
    "caller_offset: u32",
    "generic_owner_identity_is_unique(caller_line, caller_offset, table)",
    "table.generic_param_owner_offsets[row_index] == caller_offset",
    "table.generic_param_owner_offsets[bound_row] == caller_offset",
    "caller_line + 2147483648",
)) or "caller_line == 0" in caller_bound:
    raise SystemExit("caller type parameters and their bound rows must join by exact owner offset at line zero")

if not all(fragment in inferred_check for fragment in (
    "generic_owner_identity_is_unique(function_symbol.line, function_symbol.offset, table)",
    "generic_param_owner_offsets[index] == function_symbol.offset",
    "caller_offset: u32",
)) or not all(fragment in specialization_check for fragment in (
    "generic_owner_identity_is_unique(symbol.line, symbol.offset, table)",
    "generic_param_owner_offsets[bound_index] == symbol.offset",
    "caller_offset: u32",
)) or not all(fragment in expression_walk for fragment in (
    "caller_offset: u32",
    "check_interface_specialization(object, argument, 0, line.line, caller_line, caller_offset",
    "walk_interface_bound_expression(object, annotations, locals, caller_line, caller_offset, table)",
)) or not all(fragment in statement_walk for fragment in (
    "caller_offset: u32",
    "walk_interface_bound_expression(value, annotations, locals, caller_line, caller_offset, table)",
)) or "walk_interface_bound_statements(body, annotations, binders.names, line.line, line.offset, table)" not in semantic:
    raise SystemExit("specialization checks and recursive source walks must carry exact caller and target offsets")
if not all(fragment in firm_generic for fragment in (
    "table.generic_param_lines.count != table.generic_param_owner_offsets.count",
    "table.generic_param_owner_offsets[generic_index] == symbol.offset",
)) or not all(fragment in firm_argument_check for fragment in (
    "caller_line: mutable u32 = 2147483648",
    "caller_offset: mutable u32 = 0",
    "caller_offset <- table.symbols[caller_id.usize()].offset",
    "call_pos, caller_line, caller_offset, unique_direct_function",
)):
    raise SystemExit("inferred protocol checks must receive the active caller function's declaration offset")

directives = [line for line in fixture.splitlines() if line.startswith("#line 0 ")]
if len(directives) != 3 or not all(fragment in fixture for fragment in (
    "#line 0 generic-build.elisa\ndef build[T: Builder]()",
    "#line 0 generic-relay.elisa\ndef relay[B: Builder]()",
    "#line 0 generic-bad.elisa\ndef bad()",
    "return build[B]()",
    "return build[sview]()",
)):
    raise SystemExit("line-zero fixture must collide bounded function owners while retaining valid and invalid calls")
if "generic_interface_bound_owner_line0.elisa" not in smoke or \
        "expected one failure from bad[sview]" not in smoke or \
        "does not satisfy required interface fact" not in smoke:
    raise SystemExit("smoke must accept the bounded relay and retain exactly the invalid type-argument diagnostic")
