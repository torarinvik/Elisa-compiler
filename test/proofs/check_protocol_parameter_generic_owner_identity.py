"""Keep generic function and protocol-parameter metadata bound to declaration offsets."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
FUNCTIONS = ROOT / "src/parser/parser_types_function.elisa"
PROTOCOL = ROOT / "src/parser/parser_protocol_parameters.elisa"
UNIT_TEST = ROOT / "test/parity/parser_ast_extern.elisa"
SMOKE = ROOT / "test/parity/protocol_parameters_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


functions = FUNCTIONS.read_text()
protocol = PROTOCOL.read_text()
unit_test = UNIT_TEST.read_text()
smoke = SMOKE.read_text()

record_generic = function_source(functions, "record_generic_func_metadata")
bound_lookup = function_source(protocol, "protocol_parameter_bound")
replace_lowered = function_source(protocol, "lower_protocol_parameter_declarations")

if "declaration_pos: Ast::Pos = Ast::decl_pos(declaration)" not in record_generic or \
        "parameter_owner_offset == declaration_pos.offset" not in record_generic:
    raise SystemExit("generic function metadata must be discovered from its exact declaration offset")
if "annotation.offset == declaration_pos.offset" not in record_generic:
    raise SystemExit("errorset template discovery must stop at its exact function marker")
if "owner_offset: u32" not in bound_lookup or \
        "parser.generic_param_owner_offsets[index] == owner_offset" not in bound_lookup:
    raise SystemExit("protocol parameter shadowing must use generic rows owned by this declaration")
if "Ast::decl_pos(parser.generic_func_decls[metadata_index]).offset == pos.offset" not in replace_lower:
    raise SystemExit("lowered protocol methods must replace only their own generic declaration row")
if not all(fragment in unit_test for fragment in (
    "#line 0 generic-shadow.elisa",
    "#line 0 plain-function.elisa",
    "#line 0 protocol-parameter.elisa",
    "generic_func_decls.count == 2",
    "assert name != \"plain\"",
    "found_draw",
)):
    raise SystemExit("parser regression must cover same-line generic, plain, and protocol-bound functions")
if "check_protocol_parameter_generic_owner_identity.py" not in smoke:
    raise SystemExit("protocol parameter smoke must gate the parser source proof")
