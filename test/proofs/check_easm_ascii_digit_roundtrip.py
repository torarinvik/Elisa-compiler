"""Bind ASCII digit arithmetic lemmas to the production checked parser."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not args.source_only)
SOURCE = ROOT / "src/backend/easm_checked_decimal.elisa"
POSITIVE = HERE / "easm_ascii_digit_roundtrip.elisa"
NEGATIVE = HERE / "easm_ascii_digit_roundtrip_rejected.elisa"


def compact(text):
    return "".join(text.split())


def names(path):
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def function_section(text, name):
    match = re.search(rf"(?m)^([ \t]*)def {re.escape(name)}\(", text)
    if match is None:
        raise SystemExit(f"missing production function {name}")
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


source = SOURCE.read_text()
positive = POSITIVE.read_text()
negative = NEGATIVE.read_text()
if "const ASCII_DIGIT_ZERO: u8 = 48" not in source or "const ASCII_DIGIT_NINE: u8 = 57" not in source or "const ASCII_MINUS: u8 = 45" not in source:
    raise SystemExit("production ASCII digit boundaries changed")
parse_signed = compact(function_section(source, "parse_signed"))
legacy_digit_rejection = "return(false,0)ifbyte<ASCII_DIGIT_ZEROorbyte>ASCII_DIGIT_NINE"
checked_digit_rejection = compact("""
    if byte < ASCII_DIGIT_ZERO or byte > ASCII_DIGIT_NINE:
        assert not decimal_parse_reference(text).valid
        assert decimal_parse_reference(text).value == 0
        return (false, 0)
""")
if legacy_digit_rejection not in parse_signed and checked_digit_rejection not in parse_signed:
    raise SystemExit("production parser no longer rejects bytes outside the decimal digit interval")
if parse_signed.count("digit:i64=(byte-ASCII_DIGIT_ZERO).i64()") != 1:
    raise SystemExit("production parser no longer maps digits by subtracting ASCII_DIGIT_ZERO")
if "constASCII_MINUS:u8=45" not in compact(source) or "iftext.len>0andtext[0]==EasmCheckedDecimal::ASCII_MINUS:" not in parse_signed:
    raise SystemExit("production parser no longer treats ASCII minus as the leading sign")
positive_names = {
    "ascii_digit_byte_offset_is_in_range",
    "ascii_digit_byte_round_trips",
    "ascii_minus_is_outside_decimal_digit_interval",
    "u8_widening_preserves_order",
    "u8_widening_order_is_total",
    "ascii_digit_widening_stays_below_nine",
    "ascii_digit_widening_stays_above_zero",
}
if names(POSITIVE) != positive_names:
    raise SystemExit("positive theorem inventory changed")
if names(NEGATIVE) != {"ascii_digit_conversion_uses_the_wrong_origin", "false_ascii_minus_is_a_decimal_digit"}:
    raise SystemExit("false-control theorem inventory changed")
expected = {
    "ascii_digit_byte_offset_is_in_range": """
        def ascii_digit_byte_offset_is_in_range(byte: u8) -> bool:
            requires byte >= 48 and byte <= 57
            ensure result == true
            return byte - 48 >= 0 and byte - 48 <= 9
    """,
    "ascii_digit_byte_round_trips": """
        def ascii_digit_byte_round_trips(byte: u8) -> bool:
            requires byte >= 48 and byte <= 57
            ensure result == true
            return byte - 48 + 48 == byte
    """,
    "ascii_minus_is_outside_decimal_digit_interval": """
        def ascii_minus_is_outside_decimal_digit_interval(byte: u8) -> bool:
            requires byte == 45
            ensure result == true
            return byte < 48 or byte > 57
    """,
    "u8_widening_preserves_order": """
        def u8_widening_preserves_order(left: u8, right: u8) -> bool:
            requires left <= right
            ensure result == true
            return left.i64() <= right.i64()
    """,
    "u8_widening_order_is_total": """
        def u8_widening_order_is_total(left: u8, right: u8) -> bool:
            ensure result == (left > right or left.i64() <= right.i64())
            return left > right or left.i64() <= right.i64()
    """,
    "ascii_digit_widening_stays_below_nine": """
        def ascii_digit_widening_stays_below_nine(byte: u8) -> bool:
            requires byte >= 48 and byte <= 57
            requires byte - 48 <= 9
            ensure result == true
            return u8_widening_preserves_order(byte - 48, 9)
    """,
    "ascii_digit_widening_stays_above_zero": """
        def ascii_digit_widening_stays_above_zero(byte: u8) -> bool:
            requires byte >= 48 and byte <= 57
            requires byte - 48 >= 0
            ensure result == true
            return u8_widening_preserves_order(0, byte - 48)
    """,
}
for name, claim in expected.items():
    if compact(function_section(positive, name)) != compact(claim):
        raise SystemExit(f"theorem {name} no longer states its exact arithmetic claim")
if 'include "./easm_ascii_digit_roundtrip.elisa"' not in negative:
    raise SystemExit("false control must include the positive theorem source")
expected_false = """
    def ascii_digit_conversion_uses_the_wrong_origin(byte: u8) -> bool:
        requires byte >= 48 and byte <= 57
        ensure result == true
        return byte - 49 + 49 == byte
"""
if compact(function_section(negative, "ascii_digit_conversion_uses_the_wrong_origin")) != compact(expected_false):
    raise SystemExit("false control no longer tests the off-by-one conversion")
expected_minus_false = """
    def false_ascii_minus_is_a_decimal_digit(byte: u8) -> bool:
        requires byte == 45
        ensure result == true
        return byte >= 48 and byte <= 57
"""
if compact(function_section(negative, "false_ascii_minus_is_a_decimal_digit")) != compact(expected_minus_false):
    raise SystemExit("false control no longer tests sign/digit interval overlap")
if args.source_only:
    print(json.dumps({"source_bound": True, "positive_theorems": len(positive_names), "false_controls": 2}, sort_keys=True))
    raise SystemExit(0)

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("ASCII digit proof requires a strict proof build")
for path in (POSITIVE, NEGATIVE):
    report = subprocess.run([str(BIN), "--json", str(path)], check=False, capture_output=True, text=True)
    try:
        result = json.loads(report.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit(f"invalid Elisa-Proof JSON for {path.name}: {error}") from error
    if path == POSITIVE:
        summary = result.get("summary", {})
        replay = result.get("replay", {})
        if (report.returncode != 0 or result.get("status") != "proved" or
                summary.get("declarations") != 7 or summary.get("obligations") != 16 or
                summary.get("proven") != 16 or summary.get("unproven") != 0 or
                summary.get("semantic_errors") != 0 or replay.get("certificates") != 16 or
                replay.get("replayed") != 16 or replay.get("gaps") != 0 or result.get("findings")):
            raise SystemExit(f"positive proof failed or has replay gaps: {result.get('summary')}")
    else:
        summary = result.get("summary", {})
        replay = result.get("replay", {})
        findings = result.get("findings", [])
        if (report.returncode == 0 or result.get("status") != "failed" or
                summary.get("declarations") != 9 or summary.get("obligations") != 20 or
                summary.get("proven") != 18 or summary.get("unproven") != 2 or
                summary.get("semantic_errors") != 0 or replay.get("certificates") != 18 or
                replay.get("replayed") != 18 or replay.get("gaps") != 0 or len(findings) != 2 or
                findings[0].get("kind") != "ensure-unproven" or
                {finding.get("name") for finding in findings} != {"ascii_digit_conversion_uses_the_wrong_origin", "false_ascii_minus_is_a_decimal_digit"}):
            raise SystemExit("false control did not isolate the off-by-one arithmetic claim")
print(json.dumps({"source_bound": True, "positive_theorems": 7, "false_controls": 2}, sort_keys=True))
