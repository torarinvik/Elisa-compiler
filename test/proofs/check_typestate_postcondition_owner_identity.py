"""Signature typestate postconditions must resolve their own function declaration."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
AST_NODES = (ROOT / "src/parser/ast_side_tables.elisa").read_text()
PARSER_SIGNATURE = (ROOT / "src/parser/parser_types_signature.elisa").read_text()
PARSER_CLAUSES = (ROOT / "src/parser/parser_types_signature_clauses.elisa").read_text()
PARSER_FUNCTION = (ROOT / "src/parser/parser_types_function.elisa").read_text()
PARSER_TYPESTATE = (ROOT / "src/parser/parser_decl_typestate.elisa").read_text()
CHECKER = (ROOT / "src/semantic/check_ensures_structural.elisa").read_text()
TYPESTATE_HELPERS = (ROOT / "src/semantic/check_typestate_call_widening.elisa").read_text()
DERIVED_FLOW = (ROOT / "src/semantic/check_derived_state_flow.elisa").read_text()
TYPESTATE_CONSUMER = (ROOT / "src/semantic/check_typestate_call_widening.elisa").read_text()
AST_TESTS = (ROOT / "test/parity/parser_ast_typestate.elisa").read_text()
FIXTURE = (ROOT / "test/repro/typestate_postcondition_owner_line_zero.elisa").read_text()
FLOW_FIXTURE = (ROOT / "test/repro/derived_typestate_ensures_owner_line_zero.elisa").read_text()
SMOKE = (ROOT / "test/parity/typestate_postcondition_owner_line_zero_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^\s*def {re.escape(name)}\(.*?(?=^\s*def |^\s*public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


postcondition_type = re.search(r"(?ms)^    struct TypestatePostcondition:.*?(?=^    struct |\Z)", AST_NODES)
if postcondition_type is None or "function_offset: u32" not in postcondition_type.group(0):
    raise SystemExit("typestate postcondition AST must retain the owning function token offset")
append_transition = function_source(PARSER_SIGNATURE, "append_typestate_transition")
record_transition = function_source(PARSER_SIGNATURE, "record_typestate_transition")
capture = function_source(PARSER_CLAUSES, "capture_typestate_postcondition")
if "function_offset: u32" not in append_transition or \
        "function_offset: function_offset" not in append_transition or \
        "function_offset: u32" not in record_transition or \
        "append_typestate_transition(function_name, parameter_name, state_name, param_position, function_line, function_offset, target_pos)" not in record_transition or \
        "record_typestate_transition(function_name, parameter_name, state_name, function_line, function_offset, params" not in capture or \
        "capture_typestate_postcondition(function_name, param_items, token.line, token.start)" not in PARSER_FUNCTION:
    raise SystemExit("signature parser must thread function token offset into typestate postcondition rows")
if "function_offset: transition_name.start" not in PARSER_TYPESTATE:
    raise SystemExit("generated typestate transition postconditions must retain their function offset")

state_check = function_source(CHECKER, "ens_check_state_target")
param_lookup = function_source(CHECKER, "ens_param_type_at")
func_lookup = function_source(CHECKER, "ens_func_name_at")
if "postcondition.function_offset" not in state_check or \
        "ens_param_type_at(file.top_decls, postcondition.line, postcondition.function_offset, postcondition.parameter_name, target_type)" not in state_check or \
        "ens_func_name_at(file.top_decls, postcondition.line, postcondition.function_offset)" not in state_check:
    raise SystemExit("state-target diagnostics must resolve parameter type and function name by exact postcondition owner")
if "line.offset == func_offset" not in param_lookup or \
        "func_offset == SIGNATURE_CONTRACT_OFFSET_NONE or line.offset == func_offset" not in func_lookup:
    raise SystemExit("typestate postcondition lookups must match the owning function offset")
has_ensures = function_source(TYPESTATE_HELPERS, "fn_has_typestate_ensures")
ensured_state = function_source(TYPESTATE_HELPERS, "fn_typestate_ensured_state")
if not all(fragment in has_ensures for fragment in (
    "function_line: u32",
    "function_offset: u32",
    "pc.line == function_line and pc.function_offset == function_offset",
)) or not all(fragment in ensured_state for fragment in (
    "function_line: u32",
    "function_offset: u32",
    "pc.line == function_line and pc.function_offset == function_offset",
)):
    raise SystemExit("function-level state checks must select postconditions by exact declaration identity")
if "fn_typestate_ensured_state(postconditions, name, param.name, line.line, line.offset)" not in DERIVED_FLOW or \
        "fn_has_typestate_ensures(postconditions, name, param.name, line.line, line.offset)" not in DERIVED_FLOW:
    raise SystemExit("derived-flow declaration checks must pass their owning Decl.Func position")
final_state_lookup = function_source(DERIVED_FLOW, "typestate_param_final_state")
balance_check = function_source(DERIVED_FLOW, "check_typestate_balance_declarations")
if "write_found: mutable bool&" not in final_state_lookup or \
        "write_found <- true" not in final_state_lookup or \
        "final_state != state and write_found" not in balance_check or \
        "write_line != 0" in balance_check:
    raise SystemExit("typestate balance checks must distinguish a real logical-line-zero write from no write")
for helper_name in ("fn_typestate_ensured_state", "fn_has_typestate_ensures"):
    helper = function_source(TYPESTATE_CONSUMER, helper_name)
    if "function_line: u32" not in helper or "function_offset: u32" not in helper or \
            "pc.line == function_line and pc.function_offset == function_offset" not in helper:
        raise SystemExit(f"{helper_name} must match postconditions to the exact function declaration")
if "test_signature_typestate_postcondition_retains_function_offset" not in AST_TESTS or \
        FIXTURE.count("#line 0 typestate-postcondition-owner.elisa") != 2 or \
        "def first(target: Stateful) -> void ensures target => Ready:" not in FIXTURE or \
        "def second(target: Plain) -> void ensures target => Ready:" not in FIXTURE:
    raise SystemExit("regression must use stateful and plain same-name parameters on logical line zero")
if "typestate_postcondition_owner_line_zero.elisa" not in SMOKE or \
        "ensures on function \"second\" requires \"target\" to resolve to a named-state-bearing target, got Plain" not in SMOKE or \
        "check_typestate_postcondition_owner_identity.py" not in SMOKE:
    raise SystemExit("typestate state-target smoke must report the plain sibling without borrowing the earlier stateful type")
if "derived_typestate_ensures_owner_line_zero.elisa" not in SMOKE or \
        "parameter value must be left in its declared state before \"advance\" returns, but it is left in state Large" not in SMOKE or \
        FLOW_FIXTURE.count("#line 0 derived-typestate-ensures-owner.elisa") != 4 or \
        FLOW_FIXTURE.count("#line 0 derived-typestate-ensures-owner.elisa\n    value.value <- 1") != 2 or \
        "def advance(value: mutable Counter[Small]&, extra: i64) -> void ensures value => Large:" not in FLOW_FIXTURE or \
        "def advance(value: mutable Counter[Small]&, extra: bool) -> void:" not in FLOW_FIXTURE:
    raise SystemExit("derived-flow regression must distinguish same-line overload postconditions by function owner")

print("typestate postcondition owner-offset source checks passed")
