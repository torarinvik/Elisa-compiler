"""Admit the production expression-parser precedence table and climbing laws."""
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
MODEL = ROOT / "src/parser/parser_binary_precedence.elisa"
PARSER = ROOT / "src/parser/parser_expr_binary.elisa"
TOKENS = ROOT / "src/lexer/tokens.elisa"
EXPRESSION_ENTRY = ROOT / "src/parser/parser_expr_literals.elisa"
POSITIVE = HERE / "parser_binary_precedence.elisa"
NEGATIVE = HERE / "parser_binary_precedence_rejected.elisa"

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
    return "\n".join(function_section(source, name).splitlines()[1:])


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def enum_variants(path: Path) -> list[str]:
    lines = path.read_text().splitlines()
    header = re.compile(r"^( *)const enum TokenKind of u8\s*:\s*$")
    for index, line in enumerate(lines):
        match = header.match(line)
        if not match:
            continue
        indent = len(match.group(1))
        variants = []
        for variant_line in lines[index + 1:]:
            if not variant_line.strip() or variant_line.lstrip().startswith("#"):
                continue
            variant_indent = len(variant_line) - len(variant_line.lstrip(" "))
            if variant_indent <= indent:
                break
            if variant_indent == indent + 4:
                variants.append(variant_line.strip())
        return variants
    raise SystemExit(f"TokenKind declaration not found in {path}")


expected_levels = {
    "ARROW_OR": 1,
    "AND": 2,
    "COMPARISON": 3,
    "RANGE": 4,
    "BITWISE_OR": 5,
    "BITWISE_XOR": 6,
    "BITWISE_AND": 7,
    "SHIFT": 8,
    "ADDITIVE": 9,
    "MULTIPLICATIVE": 10,
}
model_text = MODEL.read_text()
if "module ParserBinaryPrecedence:" not in model_text:
    raise SystemExit("production precedence model module changed")
for name, value in expected_levels.items():
    if compact(f"const {name}: int = {value}") not in compact(model_text):
        raise SystemExit(f"production precedence constant {name} changed")

expected_arms = {
    "Arrow": "ARROW_OR", "Or": "ARROW_OR",
    "And": "AND",
    "EqEq": "COMPARISON", "BangEq": "COMPARISON", "Lt": "COMPARISON",
    "Gt": "COMPARISON", "LtEq": "COMPARISON", "GtEq": "COMPARISON",
    "In": "COMPARISON", "Is": "COMPARISON", "As": "COMPARISON",
    "Range": "RANGE", "RangeLt": "RANGE", "RangeGt": "RANGE", "RangeLe": "RANGE",
    "Pipe": "BITWISE_OR", "Caret": "BITWISE_XOR", "Ampersand": "BITWISE_AND",
    "LShift": "SHIFT", "RShift": "SHIFT",
    "Plus": "ADDITIVE", "Minus": "ADDITIVE",
    "Star": "MULTIPLICATIVE", "Slash": "MULTIPLICATIVE", "Percent": "MULTIPLICATIVE",
}
if not set(expected_arms) <= set(enum_variants(TOKENS)):
    raise SystemExit("precedence table names a token absent from the production TokenKind enum")
actual_arms = {}
for line in function_section(MODEL.read_text(), "precedence").splitlines():
    match = re.match(r"^\s*(.*?)\s*->\s*([A-Z_]+)\s*$", line)
    if not match:
        continue
    names = re.findall(r"(?:Lexer::)?TokenKind\.(\w+)", match.group(1))
    for kind in names:
        if kind in actual_arms:
            raise SystemExit(f"duplicate precedence arm for {kind}")
        actual_arms[kind] = match.group(2)
if actual_arms != expected_arms:
    raise SystemExit("production precedence model no longer partitions binary operators exactly")
if not re.search(r"(?m)^\s*_\s*->\s*0\s*$", function_section(MODEL.read_text(), "precedence")):
    raise SystemExit("non-operator tokens must retain the precedence-zero fallback")

parser_source = PARSER.read_text()
if parser_source.count('include "./parser_binary_precedence.elisa"') != 1:
    raise SystemExit("parser does not import the shared, proved precedence table exactly once")
expected_forwarder = compact("""def precedence(kind: TokenKind) -> int:
            return ParserBinaryPrecedence::precedence(kind)""")
if not compact(function_section(parser_source, "precedence")).startswith(expected_forwarder):
    raise SystemExit("production parser precedence no longer delegates to the proved table")

step = compact(function_section(parser_source, "binary_expression_step"))
required_step = (
    "current_precedence:int=precedence(kind)",
    "nullreturnifcurrent_precedence<minimum_precedence",
    "next_precedence:int=precedence(parser.peek())",
    "ifcurrent_precedence<next_precedence:",
    "parser.binary_expression_at_level(right,current_precedence+1)",
)
positions = [step.find(fragment) for fragment in required_step]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("production parser no longer follows the proved precedence-climbing thresholds")
unary = compact(function_section(parser_source, "unary_expression"))
if "parser.binary_expression_at_level(not_inner,3)" not in unary:
    raise SystemExit("prefix `not` no longer parses its operand from comparison precedence")
expression_entry = compact(function_section(EXPRESSION_ENTRY.read_text(), "expression_body"))
if "parser.binary_expression_at_level(left,1)" not in expression_entry:
    raise SystemExit("ordinary expressions no longer start binary parsing at precedence one")
driver = compact(function_section(parser_source, "binary_expression_at_level"))
if "parser.binary_expression_step(active,minimum_precedence)" not in driver or "returnactive" not in driver:
    raise SystemExit("expression driver no longer repeats accepted continuations or returns at a stopped operator")

positive_names = {
    "precedence_levels_are_strictly_ordered",
    "comparison_is_tighter_than_boolean_connectives",
    "range_binds_inside_membership_rhs",
    "bitwise_levels_are_distinct_and_ordered",
    "arithmetic_levels_match_expected_order",
    "unrecognized_tokens_stop_at_precedence_zero",
    "equal_precedence_operator_is_excluded_from_right_operand",
    "tighter_operator_is_consumed_by_right_operand",
    "weaker_operator_is_excluded_from_right_operand",
    "prefix_not_uses_comparison_threshold",
}
negative_names = {
    "false_claim_shifts_bind_tighter_than_addition",
    "false_claim_all_bitwise_levels_are_equal",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} declaration inventory changed")

positive_shapes = {
    "precedence_levels_are_strictly_ordered": "requires arrow_or == 1 and logical_and == 2 and comparison == 3 and range == 4 and bitwise_or == 5 and bitwise_xor == 6 and bitwise_and == 7 and shift == 8 and additive == 9 and multiplicative == 10 ensure result == true return arrow_or < logical_and and logical_and < comparison and comparison < range and range < bitwise_or and bitwise_or < bitwise_xor and bitwise_xor < bitwise_and and bitwise_and < shift and shift < additive and additive < multiplicative",
    "comparison_is_tighter_than_boolean_connectives": "requires logical_or == 1 and logical_and == 2 and comparison == 3 ensure result == true return logical_or < logical_and and logical_and < comparison",
    "range_binds_inside_membership_rhs": "requires comparison == 3 and range == 4 ensure result == true return comparison < range",
    "bitwise_levels_are_distinct_and_ordered": "requires bitwise_or == 5 and bitwise_xor == 6 and bitwise_and == 7 and shift == 8 ensure result == true return bitwise_or < bitwise_xor and bitwise_xor < bitwise_and and bitwise_and < shift",
    "arithmetic_levels_match_expected_order": "requires shift == 8 and additive == 9 and multiplicative == 10 ensure result == true return shift < additive and additive < multiplicative",
    "unrecognized_tokens_stop_at_precedence_zero": "requires unknown == 0 and minimum == 1 ensure result == true return unknown < minimum",
    "equal_precedence_operator_is_excluded_from_right_operand": "requires level >= 1 and level <= 10 ensure result == true return level < level + 1",
    "tighter_operator_is_consumed_by_right_operand": "requires outer >= 1 and outer <= 10 requires inner > outer and inner <= 10 ensure result == true return inner >= outer + 1",
    "weaker_operator_is_excluded_from_right_operand": "requires outer >= 1 and outer <= 10 requires inner >= 0 and inner < outer ensure result == true return inner < outer + 1",
    "prefix_not_uses_comparison_threshold": "requires logical_and == 2 and comparison == 3 and threshold == 3 ensure result == true return comparison >= threshold and logical_and < threshold",
}
negative_shapes = {
    "false_claim_shifts_bind_tighter_than_addition": "requires shift == 8 and additive == 9 ensure result == true return shift > additive",
    "false_claim_all_bitwise_levels_are_equal": "requires bitwise_or == 5 and bitwise_xor == 6 ensure result == true return bitwise_or == bitwise_xor",
}
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    source = path.read_text()
    for name, expected in shapes.items():
        if not compact(function_body(source, name)).startswith(compact(expected)):
            raise SystemExit(f"{name} no longer proves the intended precedence law")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("parser precedence proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
    MODEL, PARSER, TOKENS, EXPRESSION_ENTRY,
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
assert all(row.get("verified") for row in positive["declaration_details"]
           if row["kind"] == "function")

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
expected_findings = {("ensure-unproven", name) for name in negative_names}
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == expected_findings
assert not negative_names & {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}

assert require_current_product(BIN, PROVER) == product, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
