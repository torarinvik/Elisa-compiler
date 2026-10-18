"""Admit the separator and neighboring-byte bounds in backend numeric spans."""
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
OPS = ROOT / "src/backend/codegen_binary_ops.elisa"
PATTERNS = ROOT / "src/backend/codegen_const_capacity.elisa"
STRUCTS = ROOT / "src/backend/codegen_struct_reg.elisa"
BACKEND = ROOT / "src/backend/codegen.elisa"
LEXER = ROOT / "src/lexer/lexer_numbers.elisa"
PATTERN_FACTS = ROOT / "src/backend/codegen_match_arm_facts.elisa"
PACKED_META = ROOT / "src/backend/codegen_packed_meta.elisa"
BLOCKS = ROOT / "src/backend/codegen_stmt_blocks_exprs.elisa"
BLOCK_BINDING = ROOT / "src/backend/codegen_stmt_binding_blocks.elisa"
POSITIVE = HERE / "backend_decimal_separator.elisa"
NEGATIVE = HERE / "backend_decimal_separator_rejected.elisa"
INTEGRATION_CASE = ROOT / "test/differential/cases/backend_decimal_separator_pattern_capacity.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return "\n".join(line for line in source[start:end].splitlines()
                      if not line.lstrip().startswith("#"))


ops_text = OPS.read_text()
pattern_text = PATTERNS.read_text()
struct_text = STRUCTS.read_text()
backend_text = BACKEND.read_text()
lexer_text = LEXER.read_text()
pattern_facts_text = PATTERN_FACTS.read_text()
packed_meta_text = PACKED_META.read_text()
blocks_text = BLOCKS.read_text()
block_binding_text = BLOCK_BINDING.read_text()

parse_integer = compact(function_section(ops_text, "parse_int_literal"))
separator_branch = (
    "ifbyte==95:"
    "ifindex==startortext.len-index<=1:ok<-false"
    "else:"
    "previous:u8=text[index-1]"
    "following:u8=text[index+1]"
    "ok<-falseifprevious<48orprevious>57orfollowing<48orfollowing>57"
)
if separator_branch not in parse_integer:
    raise SystemExit("backend decimal conversion no longer skips only in-span, between-digit separators")
digit_conversion = "elifbyte<48orbyte>57:ok<-falseelse:digit:u64=(byte.i64()-48).u64()"
if digit_conversion not in parse_integer:
    raise SystemExit("separator handling changed the decimal digit conversion branch")
if parse_integer.count("accumulated<-accumulated*10.u64()+digit") != 1:
    raise SystemExit("decimal conversion no longer applies one checked multiply-add per digit")

capacity = compact(function_section(pattern_text, "capacity_span_parse_primary"))
separator_scan = (
    "elifbyte==95andcursor>startandtext.len-cursor>1:"
    "previous:u8=text[cursor-1]"
    "following:u8=text[cursor+1]"
    "breakifprevious<48orprevious>57orfollowing<48orfollowing>57"
    "cursor<-cursor+1"
)
if separator_scan not in capacity:
    raise SystemExit("capacity literal scan no longer admits only in-span, between-digit separators")
if "falsereturnifcursor!=text.len" not in compact(function_section(pattern_text, "fold_const_capacity_text")):
    raise SystemExit("capacity parser no longer rejects unconsumed malformed literal text")
if 'include "./codegen_const_capacity.elisa"' not in struct_text or 'include "./codegen_struct_reg.elisa"' not in backend_text:
    raise SystemExit("backend facade no longer includes constant-capacity span parsing")
if 'include "./codegen_match_arm_facts.elisa"' not in packed_meta_text:
    raise SystemExit("backend match lowering no longer includes the scalar-pattern parser")
if "return true if parse_int_literal(text, out_value)" not in pattern_facts_text:
    raise SystemExit("match scalar parsing no longer routes integer pattern text through parse_int_literal")
if "fold_const_capacity_text" not in block_binding_text:
    raise SystemExit("region/with header lowering no longer routes raw capacity spans through the checked parser")
if "parse_int_literal(block_clause[block_clause.count - 1], pool_workers)" not in blocks_text:
    raise SystemExit("pool worker-count lowering no longer routes literal spans through parse_int_literal")
if ("fold_const_capacity_text(with_word, structs, with_probe)" not in block_binding_text or
        "fold_const_capacity_text(stmt_region_word, structs, stmt_region_probe)" not in block_binding_text or
        "fold_const_capacity_text(block_clause[1], structs, region_capacity)" not in block_binding_text or
        "parse_int_literal(literal, value)" not in pattern_text):
    raise SystemExit("underscored literal integration paths changed for with, region, or pool capacities")
if 'include "./codegen_stmt_blocks_exprs.elisa"' not in backend_text:
    raise SystemExit("backend facade no longer includes pool block lowering")
integration_text = INTEGRATION_CASE.read_text()
if "region scratch(1_000):" not in integration_text or "match 1_000:" not in integration_text or "1_000: 42" not in integration_text:
    raise SystemExit("source-level integration control lost the underscored region capacity or match pattern")

number_classifier = compact(function_section(lexer_text, "classify_number_input"))
if ("ifc=='_'andlexer.position>0" not in number_classifier or
        "previous.is_digit()andfollowing.is_digit()" not in number_classifier or
        "returnNumberClass.DecimalSeparator" not in number_classifier):
    raise SystemExit("lexer no longer classifies decimal separators only between decimal digits")

expected_positive = {
    "separator_neighbor_indices_are_inside_the_literal": "requires start < index requires index < length requires length - index > 1 ensure result == true return index - 1 >= start and index + 1 < length",
    "separator_in_one_thousand_is_valid": "ensure result == true return 0 < 1 and 1 < 5 and 5 - 1 > 1 and 49 >= 48 and 49 <= 57 and 48 >= 48 and 48 <= 57",
    "one_thousand_with_a_separator_folds_to_one_thousand": "ensure result == true after_first_digit: i64 = 1 after_separator: i64 = after_first_digit after_first_zero: i64 = after_separator * 10 + 0 after_second_zero: i64 = after_first_zero * 10 + 0 after_third_zero: i64 = after_second_zero * 10 + 0 return 0 < 1 and 1 < 5 and 5 - 1 > 1 and 49 >= 48 and 49 <= 57 and 48 >= 48 and 48 <= 57 and after_separator == 1 and after_third_zero == 1000",
    "overflowing_literal_separator_is_between_digits": "ensure result == true return 0 < 19 and 19 < 21 and 21 - 19 > 1 and 49 >= 48 and 49 <= 57 and 54 >= 48 and 54 <= 57",
}
expected_negative = {
    "final_byte_separator_has_an_in_range_successor": "requires index < length requires length - index <= 1 ensure result == true return index + 1 < length",
    "leading_separator_is_accepted": "ensure result == true return 0 < 0 and 0 < 5 and 5 - 0 > 1 and 0 >= 48 and 0 <= 57 and 49 >= 48 and 49 <= 57",
    "trailing_separator_is_accepted": "ensure result == true return 0 < 4 and 4 < 5 and 5 - 4 > 1 and 48 >= 48 and 48 <= 57 and 0 >= 48 and 0 <= 57",
    "doubled_separator_is_accepted": "ensure result == true return 0 < 1 and 1 < 6 and 6 - 1 > 1 and 49 >= 48 and 49 <= 57 and 95 >= 48 and 95 <= 57",
}
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
if set(re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_text, re.MULTILINE)) != set(expected_positive):
    raise SystemExit("separator proof declaration inventory changed")
if set(re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", negative_text, re.MULTILINE)) != set(expected_negative):
    raise SystemExit("separator negative-control inventory changed")
for name, expected in expected_positive.items():
    if compact(expected) not in compact(function_section(positive_text, name)):
        raise SystemExit(f"{name} no longer states its accepted separator or bounds theorem")
for name, expected in expected_negative.items():
    if compact(expected) not in compact(function_section(negative_text, name)):
        raise SystemExit(f"{name} no longer challenges a rejected separator case")

def separator_context(text: str) -> tuple[int, int, int, int, int]:
    index = text.index("_")
    previous = ord(text[index - 1]) if index > 0 else 0
    following = ord(text[index + 1]) if index + 1 < len(text) else 0
    return 0, index, len(text), previous, following


if separator_context("1_000") != (0, 1, 5, 49, 48):
    raise SystemExit("one-thousand pattern/header proof no longer describes the literal `1_000`")
overflowing_case = "1844674407370955161_6"
if (separator_context(overflowing_case) != (0, 19, 21, 49, 54) or
        int(overflowing_case.replace("_", "")) != int("18446744073709551615") + 1):
    raise SystemExit("overflow-with-separator proof no longer describes u64.max + 1")
malformed_cases = {"_1000": (0, 0, 5, 0, 49), "1000_": (0, 4, 5, 48, 0), "1__000": (0, 1, 6, 49, 95)}
if any(separator_context(text) != expected for text, expected in malformed_cases.items()):
    raise SystemExit("leading, trailing, or doubled separator controls changed")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("backend decimal separator proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", OPS, PATTERNS,
    STRUCTS, BACKEND, LEXER, PATTERN_FACTS, PACKED_META, BLOCKS,
    BLOCK_BINDING, INTEGRATION_CASE, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = replay(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
expected_proved = {
    "separator_neighbor_indices_are_inside_the_literal",
    "separator_in_one_thousand_is_valid",
    "one_thousand_with_a_separator_folds_to_one_thousand",
    "overflowing_literal_separator_is_between_digits",
}
assert expected_proved <= {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert positive == replay(POSITIVE)[1], "backend decimal separator proof report changed across identical runs"

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {finding["name"] for finding in negative["findings"]} == set(expected_negative)
assert all(finding["kind"] == "ensure-unproven" for finding in negative["findings"])

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product, "proof product or pinned source tree changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "source-bound underscore separators and bounded neighboring-byte access",
    "producer_proven": positive["summary"]["proven"],
    "independently_replayed": positive["replay"]["replayed"],
    "false_claim_rejected": "final_byte_separator_has_an_in_range_successor",
    "sources_sha256": hashes_before,
}))
