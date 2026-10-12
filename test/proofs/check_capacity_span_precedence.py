"""Admit the source-span capacity parser's precedence-climbing laws."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MODEL = ROOT / "src/backend/codegen_const_capacity_precedence.elisa"
CAPACITY = ROOT / "src/backend/codegen_const_capacity.elisa"
PARSER = ROOT / "src/parser/parser_expr_binary.elisa"
PARSER_PRECEDENCE = ROOT / "src/parser/parser_binary_precedence.elisa"
STRUCT_REG = ROOT / "src/backend/codegen_struct_reg.elisa"
BLOCK_EMITTER = ROOT / "src/backend/codegen_stmt_binding_blocks.elisa"
POSITIVE = HERE / "capacity_span_precedence.elisa"
NEGATIVE = HERE / "capacity_span_precedence_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def function_body(source: str, name: str) -> str:
    lines = function_section(source, name).splitlines()
    return "\n".join(lines[1:])


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


model_text = MODEL.read_text()
if "module BackendCapacityPrecedence:" not in model_text:
    raise SystemExit("capacity precedence model module changed")
expected_constants = {
    "COMPARISON": 0,
    "BITWISE_OR": 1,
    "BITWISE_XOR": 2,
    "BITWISE_AND": 3,
    "SHIFT": 4,
    "ADDITIVE": 5,
    "MULTIPLICATIVE": 6,
    "MAIN_PARSER_OFFSET": 3,
}
for name, value in expected_constants.items():
    if compact(f"const {name}: i32 = {value}") not in compact(model_text):
        raise SystemExit(f"capacity precedence constant {name} changed")

if 'include "./codegen_const_capacity_precedence.elisa"' not in CAPACITY.read_text():
    raise SystemExit("production capacity parser no longer uses its proved precedence constants")
if 'include "./codegen_const_capacity.elisa"' not in STRUCT_REG.read_text():
    raise SystemExit("backend no longer includes the source-span capacity parser")
block_emitter = compact(BLOCK_EMITTER.read_text())
for call_site in (
    "fold_const_capacity_text(with_word, structs, with_probe)",
    "fold_const_capacity_text(stmt_region_word, structs, stmt_region_probe)",
    "fold_const_capacity_text(block_clause[1], structs, region_capacity)",
):
    if compact(call_site) not in block_emitter:
        raise SystemExit(f"region/with capacity lowering no longer uses the proved parser: {call_site}")
expected_operator = compact("""def capacity_span_operator(text: sview, cursor: usize) -> (operator: TokenKind, width: usize, precedence: i32) can[Abort.Panic]:
            length: usize = sview_len(text)
            (TokenKind.Eof, 0, -1.i32()) return if cursor >= length
            if cursor + 1.usize() < length:
                first: u8 = sview_at(text, cursor)
                second: u8 = sview_at(text, cursor + 1.usize())
                (TokenKind.LShift, 2, BackendCapacityPrecedence::SHIFT) return if first == 60 and second == 60
                (TokenKind.RShift, 2, BackendCapacityPrecedence::SHIFT) return if first == 62 and second == 62
                (TokenKind.EqEq, 2, BackendCapacityPrecedence::COMPARISON) return if first == 61 and second == 61
                (TokenKind.BangEq, 2, BackendCapacityPrecedence::COMPARISON) return if first == 33 and second == 61
                (TokenKind.LtEq, 2, BackendCapacityPrecedence::COMPARISON) return if first == 60 and second == 61
                (TokenKind.GtEq, 2, BackendCapacityPrecedence::COMPARISON) return if first == 62 and second == 61
            return match sview_at(text, cursor):
                60: (TokenKind.Lt, 1, BackendCapacityPrecedence::COMPARISON)
                62: (TokenKind.Gt, 1, BackendCapacityPrecedence::COMPARISON)
                124: (TokenKind.Pipe, 1, BackendCapacityPrecedence::BITWISE_OR)
                94: (TokenKind.Caret, 1, BackendCapacityPrecedence::BITWISE_XOR)
                38: (TokenKind.Ampersand, 1, BackendCapacityPrecedence::BITWISE_AND)
                43: (TokenKind.Plus, 1, BackendCapacityPrecedence::ADDITIVE)
                45: (TokenKind.Minus, 1, BackendCapacityPrecedence::ADDITIVE)
                42: (TokenKind.Star, 1, BackendCapacityPrecedence::MULTIPLICATIVE)
                47: (TokenKind.Slash, 1, BackendCapacityPrecedence::MULTIPLICATIVE)
                37: (TokenKind.Percent, 1, BackendCapacityPrecedence::MULTIPLICATIVE)
                _: (TokenKind.Eof, 0, -1.i32())""")
if compact(function_section(CAPACITY.read_text(), "capacity_span_operator")) != expected_operator:
    raise SystemExit("capacity-span operator tokens no longer map to their proved precedence levels")

capacity_parser = compact(function_section(CAPACITY.read_text(), "capacity_span_parse_binary"))
sentinel_break = "breakifoperation.precedence<minimum_precedence"
cursor_advance = "cursor<-cursor+operation.width"
right_parse = "capacity_span_parse_binary(text,cursor,operation.precedence+1)"
parser_steps = [capacity_parser.find(step) for step in (sentinel_break, cursor_advance, right_parse)]
if any(position < 0 for position in parser_steps) or parser_steps != sorted(parser_steps):
    raise SystemExit("capacity parser no longer uses the verified precedence-climbing threshold")
fold_capacity = compact(function_section(CAPACITY.read_text(), "fold_const_capacity_text"))
if "capacity_span_parse_binary(text,cursor,0)" not in fold_capacity or \
        "falsereturnifcursor!=sview_len(text)" not in fold_capacity:
    raise SystemExit("capacity parser no longer begins at its lowest supported precedence")

parser_precedence = compact(PARSER_PRECEDENCE.read_text())
main_levels = (
    "const COMPARISON: int = 3",
    "const BITWISE_OR: int = 5",
    "const BITWISE_XOR: int = 6",
    "const BITWISE_AND: int = 7",
    "const SHIFT: int = 8",
    "const ADDITIVE: int = 9",
    "const MULTIPLICATIVE: int = 10",
)
positions = [parser_precedence.find(compact(level)) for level in main_levels]
if any(position < 0 for position in positions) or positions != sorted(positions) or \
        any(parser_precedence.count(compact(level)) != 1 for level in main_levels):
    raise SystemExit("main parser changed the shared operator precedence levels or their order")
shared_operator_arms = (
    "Lexer::TokenKind.EqEq | Lexer::TokenKind.BangEq | Lexer::TokenKind.Lt | Lexer::TokenKind.Gt | Lexer::TokenKind.LtEq | Lexer::TokenKind.GtEq | Lexer::TokenKind.In | Lexer::TokenKind.Is | Lexer::TokenKind.As -> COMPARISON",
    "Lexer::TokenKind.Pipe -> BITWISE_OR",
    "Lexer::TokenKind.Caret -> BITWISE_XOR",
    "Lexer::TokenKind.Ampersand -> BITWISE_AND",
    "Lexer::TokenKind.LShift | Lexer::TokenKind.RShift -> SHIFT",
    "Lexer::TokenKind.Plus | Lexer::TokenKind.Minus -> ADDITIVE",
    "Lexer::TokenKind.Star | Lexer::TokenKind.Slash | Lexer::TokenKind.Percent -> MULTIPLICATIVE",
)
shared_positions = [parser_precedence.find(compact(arm)) for arm in shared_operator_arms]
if any(position < 0 for position in shared_positions) or shared_positions != sorted(shared_positions):
    raise SystemExit("main parser changed the shared token-to-precedence assignments")

positive_names = {
    "capacity_precedence_levels_are_strictly_ordered",
    "capacity_levels_match_main_parser_offset",
    "translated_capacity_order_matches_main_parser",
    "equal_precedence_operator_is_excluded_from_right_operand",
    "tighter_operator_is_admitted_inside_right_operand",
    "weaker_operator_is_stopped_by_right_operand",
}
negative_names = {"equal_precedence_operator_is_admitted_into_right_operand"}
negative_names |= {
    "unsupported_operator_is_admitted_at_top_level",
    "unconsumed_capacity_suffix_is_accepted",
}
positive_names |= {
    "unsupported_operator_stops_before_cursor_advance",
    "unconsumed_capacity_suffix_has_positive_length",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "../../src/backend/codegen_const_capacity_precedence.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer proves the production precedence model")

positive_shapes = {
    "capacity_precedence_levels_are_strictly_ordered": "requires comparison == 0 and bitwise_or == 1 and bitwise_xor == 2 and bitwise_and == 3 and shift == 4 and additive == 5 and multiplicative == 6 ensure result == true return comparison < bitwise_or and bitwise_or < bitwise_xor and bitwise_xor < bitwise_and and bitwise_and < shift and shift < additive and additive < multiplicative",
    "capacity_levels_match_main_parser_offset": "requires precedence >= 0 and precedence <= 6 ensure result == true main_precedence: i64 = precedence + 3 return (main_precedence == precedence + 3 and main_precedence >= 3 and main_precedence <= 9)",
    "translated_capacity_order_matches_main_parser": "requires lower >= 0 and lower <= 6 requires higher > lower and higher <= 6 ensure result == true lower_main: i64 = lower + 3 higher_main: i64 = higher + 3 return lower_main < higher_main",
    "equal_precedence_operator_is_excluded_from_right_operand": "requires precedence >= 0 and precedence <= 6 ensure result == true return precedence < precedence + 1",
    "tighter_operator_is_admitted_inside_right_operand": "requires outer >= 0 and outer <= 6 requires inner > outer and inner <= 6 ensure result == true return inner >= outer + 1",
    "weaker_operator_is_stopped_by_right_operand": "requires outer >= 0 and outer <= 6 requires inner < outer ensure result == true return inner < outer + 1",
    "unsupported_operator_stops_before_cursor_advance": "requires minimum >= 0 ensure result == true return -1 < minimum",
    "unconsumed_capacity_suffix_has_positive_length": "requires cursor >= 0 and cursor < length ensure result == true return length - cursor > 0",
}
negative_shapes = {
    "equal_precedence_operator_is_admitted_into_right_operand": "ensure result == true return 5 >= 6",
    "unsupported_operator_is_admitted_at_top_level": "ensure result == true return -1 >= 0",
    "unconsumed_capacity_suffix_is_accepted": "requires cursor >= 0 and cursor < length ensure result == true return cursor == length",
}
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    source = path.read_text()
    for name, expected in shapes.items():
        if compact(function_body(source, name)) != compact(expected):
            raise SystemExit(f"{name} no longer proves the intended precedence-climbing law")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("capacity precedence proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
    MODEL, CAPACITY, PARSER, PARSER_PRECEDENCE, STRUCT_REG, BLOCK_EMITTER,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", "equal_precedence_operator_is_admitted_into_right_operand"),
    ("ensure-unproven", "unsupported_operator_is_admitted_at_top_level"),
    ("ensure-unproven", "unconsumed_capacity_suffix_is_accepted"),
}
assert not negative_names & {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}

assert require_current_product(BIN, PROVER) == product, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
