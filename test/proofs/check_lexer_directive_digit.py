"""Admit decimal digit conversion proofs at the production #line scanner call site."""
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
HELPER = ROOT / "src/lexer/lexer_directive_digit.elisa"
LEXER = ROOT / "src/lexer/lexer_comments.elisa"
POSITIVE = HERE / "lexer_directive_digit.elisa"
NEGATIVE = HERE / "lexer_directive_digit_rejected.elisa"

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
    return source[start:end]


def require_ordered(body: str, fragments: tuple[str, ...], label: str) -> None:
    compact_body = compact(body)
    positions = [compact_body.find(compact(fragment)) for fragment in fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{label} no longer follows the checked decimal-digit path")


helper_text = HELPER.read_text()
helper_fn = compact(function_section(helper_text, "decimal_digit_value"))
expected_helper = compact("""def decimal_digit_value(character: u8) -> int:
            ensure result == ((character - 48).int() if character >= 48 and character <= 57 else 0)
            return (character - 48).int() if character >= 48 and character <= 57
            return 0""")
if helper_fn != expected_helper:
    raise SystemExit("production #line digit helper no longer matches its byte offset contract")

lexer_text = LEXER.read_text()
if 'include "./lexer_directive_digit.elisa"' not in lexer_text:
    raise SystemExit("#line scanner no longer imports the proved decimal digit helper")
if "def decimal_digit_value(" in lexer_text:
    raise SystemExit("#line scanner contains a second, unproved decimal digit conversion")
if lexer_text.count("LexerDirectiveDigit::decimal_digit_value(") != 1:
    raise SystemExit("#line scanner no longer has exactly one guarded decimal digit conversion")
scan_line = compact(function_section(lexer_text, "try_consume_line_directive"))
case = compact(
    "ScanLine, '0'..='9': lexer.machine_int <- lexer.machine_int * 10 + LexerDirectiveDigit::decimal_digit_value(char_at(lexer.source, lexer.source_length, cursor).u8()) cursor <- cursor + 1 -> ScanLine"
)
if case not in scan_line:
    raise SystemExit("#line number scan no longer converts only ASCII digits before advancing")
require_ordered(function_section(lexer_text, "try_consume_line_directive"), (
    "number_start: usize = cursor",
    "ScanLine, '0'..='9':",
    "decimal_digit_value(char_at(lexer.source, lexer.source_length, cursor).u8())",
    "false return if cursor == number_start",
), "#line decimal number scanner")

positive_names = {
    "every_ascii_decimal_digit_byte_maps_to_its_offset",
    "every_ascii_decimal_digit_byte_maps_into_zero_through_nine",
    "ascii_zero_maps_to_zero",
    "ascii_nine_maps_to_nine",
    "byte_below_digit_range_maps_to_zero",
    "byte_above_digit_range_maps_to_zero",
    "every_byte_below_digit_range_maps_to_zero",
    "every_byte_above_digit_range_maps_to_zero",
    "punctuation_maps_to_zero",
}
negative_names = {
    "ascii_nine_maps_to_eight",
    "punctuation_maps_to_a_nonzero_value",
    "byte_below_digit_range_maps_to_one",
    "byte_above_digit_range_maps_to_one",
}


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "../../src/lexer/lexer_directive_digit.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer proves the production digit helper")

positive_shapes = {
    "every_ascii_decimal_digit_byte_maps_to_its_offset": "requires character >= 48 and character <= 57 ensure result == true ensure LexerDirectiveDigit::decimal_digit_value(character) == (character - 48).int() return true",
    "every_ascii_decimal_digit_byte_maps_into_zero_through_nine": "requires character >= 48 and character <= 57 ensure result == true return LexerDirectiveDigit::decimal_digit_value(character) >= 0 and LexerDirectiveDigit::decimal_digit_value(character) <= 9",
    "ascii_zero_maps_to_zero": "ensure result == true return LexerDirectiveDigit::decimal_digit_value(48) == 0",
    "ascii_nine_maps_to_nine": "ensure result == true return LexerDirectiveDigit::decimal_digit_value(57) == 9",
    "byte_below_digit_range_maps_to_zero": "ensure result == true return LexerDirectiveDigit::decimal_digit_value(47) == 0",
    "byte_above_digit_range_maps_to_zero": "ensure result == true return LexerDirectiveDigit::decimal_digit_value(58) == 0",
    "every_byte_below_digit_range_maps_to_zero": "requires character < 48 ensure result == true ensure LexerDirectiveDigit::decimal_digit_value(character) == 0 return true",
    "every_byte_above_digit_range_maps_to_zero": "requires character > 57 ensure result == true ensure LexerDirectiveDigit::decimal_digit_value(character) == 0 return true",
    "punctuation_maps_to_zero": "ensure result == true return LexerDirectiveDigit::decimal_digit_value(46) == 0",
}
negative_shapes = {
    "ascii_nine_maps_to_eight": "ensure result == true return LexerDirectiveDigit::decimal_digit_value(57) == 8",
    "punctuation_maps_to_a_nonzero_value": "ensure result == true return LexerDirectiveDigit::decimal_digit_value(46) != 0",
    "byte_below_digit_range_maps_to_one": "ensure result == true return LexerDirectiveDigit::decimal_digit_value(47) == 1",
    "byte_above_digit_range_maps_to_one": "ensure result == true return LexerDirectiveDigit::decimal_digit_value(58) == 1",
}
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    proof_text = path.read_text()
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(proof_text, name)):
            raise SystemExit(f"{name} no longer states the intended #line digit law")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("#line digit proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", HELPER, LEXER,
    POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE, LEXER]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                            text=True, timeout=60)
    report = json.loads(result.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return result.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names) + 1
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "#line digit proof report changed across repeated runs"
assert positive_names | {"decimal_digit_value"} <= {
    item["name"] for item in positive["declaration_details"] if item.get("verified")
}

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert negative["summary"]["declarations"] == len(negative_names) + 1
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert all(finding["status"] == "disproved" and finding["counterexample_found"]
           for finding in negative["findings"])
assert "decimal_digit_value" in {
    item["name"] for item in negative["declaration_details"] if item.get("verified")
}
assert product == require_current_product(BIN, PROVER)
if hashes_before != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}:
    raise SystemExit("#line digit proof inputs changed during replay")

print(json.dumps({
    "admitted": True,
    "scope": "ASCII digit conversion and digit-only use while scanning #line numbers",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
