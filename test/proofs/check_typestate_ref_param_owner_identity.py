"""Typestate ref-parameter markers and consume checks must use function identity."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER_PARAMS = (ROOT / "src/parser/parser_func_params.elisa").read_text()
PARSER_SIGNATURE = (ROOT / "src/parser/parser_types_signature.elisa").read_text()
PARSER_CLAUSES = (ROOT / "src/parser/parser_types_signature_clauses.elisa").read_text()
PARSER_FUNCTION = (ROOT / "src/parser/parser_types_function.elisa").read_text()
CHECKER = (ROOT / "src/semantic/check_ensures_structural.elisa").read_text()
AST_TESTS = (ROOT / "test/parity/parser_ast_decls.elisa").read_text()
FIXTURE = (ROOT / "test/repro/typestate_ref_param_owner_line_zero.elisa").read_text()
SMOKE = (ROOT / "test/parity/typestate_ref_param_owner_line_zero_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^\s*def {re.escape(name)}\(.*?(?=^\s*def |^\s*public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


param_parser = function_source(PARSER_PARAMS, "parse_one_param")
ref_lookup = function_source(PARSER_SIGNATURE, "typestate_ref_param_name")
consume_recorder = function_source(PARSER_SIGNATURE, "record_typestate_consume")
consume_appender = function_source(PARSER_SIGNATURE, "append_typestate_consume")
postcondition_capture = function_source(PARSER_CLAUSES, "capture_typestate_postcondition")
ref_target_check = function_source(CHECKER, "ens_check_ref_target")
param_lookup = function_source(CHECKER, "ens_param_type_at")

if 'name: "__typestate_ref_param", line: function_line, offset: function_offset' not in param_parser:
    raise SystemExit("ref-parameter metadata must retain its owning function offset")
if "function_offset: u32" not in ref_lookup or \
        'annotation.line == function_line and annotation.offset == function_offset' not in ref_lookup:
    raise SystemExit("ref-parameter lookup must match both function line and offset")
if "function_offset: u32" not in consume_recorder or \
        "typestate_ref_param_name(consume_name, function_line, function_offset)" not in consume_recorder or \
        "append_typestate_consume(function_name, consume_name, function_line, function_offset, target_pos)" not in consume_recorder:
    raise SystemExit("consume recording must pass the declaration offset through exact ref-marker lookup")
if "function_offset: u32" not in postcondition_capture or \
        "record_typestate_consume(function_name, consume_name, function_line, function_offset, params" not in postcondition_capture or \
        "capture_typestate_postcondition(function_name, param_items, token.line, token.start)" not in PARSER_FUNCTION:
    raise SystemExit("function declaration position must flow through signature postcondition parsing")
if "offset: function_offset" not in consume_appender or \
        "ens_param_type_at(file.top_decls, annotation.detail_line, annotation.offset, annotation.name, consumed_type)" not in ref_target_check:
    raise SystemExit("non-ref consume diagnostics must retain and use the exact function offset")
if "line.offset == func_offset" not in param_lookup:
    raise SystemExit("non-ref target type lookup must select the exact function declaration")
if "test_typestate_ref_param_marker_uses_function_owner_offset" not in AST_TESTS or \
        FIXTURE.count("#line 0 typestate-ref-owner.elisa") != 2 or \
        "def first(value: i64&) -> void:" not in FIXTURE or \
        "def second(value: i64) -> void ensures value => !:" not in FIXTURE:
    raise SystemExit("regression must pair ref and non-ref same-name parameters on logical line zero")
if "typestate_ref_param_owner_line_zero.elisa" not in SMOKE or \
        "requires \"value\" to resolve to a ref target for refstate effects" not in SMOKE or \
        "check_typestate_ref_param_owner_identity.py" not in SMOKE:
    raise SystemExit("typestate ref-param smoke must require the non-ref sibling's diagnostic")

print("typestate ref-parameter owner-offset source checks passed")
