"""Source-bind checked alignment-text parsing to its recursive proof."""
from __future__ import annotations

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
SOURCE = ROOT / "src/semantic/positive_power_of_two_text.elisa"
CONSUMER = ROOT / "src/semantic/check_unknown_type_annotation.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "positive_power_of_two_text.elisa"
NEGATIVE = HERE / "positive_power_of_two_text_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost )?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost )?def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*(?:ghost )?def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


source_text = SOURCE.read_text()
consumer_text = CONSUMER.read_text()
semantic_text = SEMANTIC.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_guard_spec = '''
ghost def decimal_step_allowed_spec(value: u64, digit: u64) -> bool:
    requires digit <= 9.u64()
    return value < MAX_PREFIX_BEFORE_DIGIT or (value == MAX_PREFIX_BEFORE_DIGIT and digit <= MAX_FINAL_DIGIT)
'''
expected_value_spec = '''
ghost def decimal_step_value_spec(value: u64, digit: u64) -> u64:
    requires digit <= 9.u64() and decimal_step_allowed_spec(value, digit)
    ensure result <= U64_MAX
    return value * 10.u64() + digit
'''
expected_power_spec = '''
ghost def is_positive_power_of_two_spec(value: u64) -> bool:
    return value > 0.u64() and (value & (value - 1.u64())) == 0.u64()
'''
expected_guard = '''
def decimal_step_allowed(value: u64, digit: u64) -> bool:
    requires digit <= 9.u64()
    ensure result == decimal_step_allowed_spec(value, digit)
    return value < MAX_PREFIX_BEFORE_DIGIT or (value == MAX_PREFIX_BEFORE_DIGIT and digit <= MAX_FINAL_DIGIT)
'''
expected_step = '''
def decimal_step_value(value: u64, digit: u64) -> u64:
    requires digit <= 9.u64() and decimal_step_allowed(value, digit)
    ensure result == decimal_step_value_spec(value, digit)
    ensure result <= U64_MAX
    return value * 10.u64() + digit
'''
expected_power = '''
def is_positive_power_of_two(value: u64) -> bool:
    ensure result == is_positive_power_of_two_spec(value)
    return false if value == 0.u64()
    return (value & (value - 1.u64())) == 0.u64()
'''
expected_model = '''
ghost def accepts_from(text: sview, position: usize, value: u64) -> bool:
    requires position <= text.len
    decreases text.len - position
    return is_positive_power_of_two_spec(value) if position == text.len
    byte: u8 = text[position]
    return false if byte < ASCII_DIGIT_ZERO or byte > ASCII_DIGIT_NINE
    digit: u64 = (byte - ASCII_DIGIT_ZERO).u64()
    return false if not decimal_step_allowed_spec(value, digit)
    next_value: u64 = decimal_step_value_spec(value, digit)
    return accepts_from(text, position + 1, next_value)
'''
expected_scan = '''
def accepts(text: sview) -> bool can[Abort.Panic]:
    ensure result == accepts_from(text, 0, 0.u64())
    can Abort.Panic:
        value: mutable u64 = 0.u64()
        position: mutable usize = 0
        while position < text.len |position, value|:
            decreases text.len - position
            invariant position <= text.len
            invariant accepts_from(text, position, value) == accepts_from(text, 0, 0.u64())
            byte: u8 = text[position]
            return false if byte < ASCII_DIGIT_ZERO or byte > ASCII_DIGIT_NINE
            digit: u64 = (byte - ASCII_DIGIT_ZERO).u64()
            return false if not decimal_step_allowed(value, digit)
            value <- decimal_step_value(value, digit)
            position <- position + 1
        return is_positive_power_of_two(value)
'''
for name, expected in (
    ("decimal_step_allowed_spec", expected_guard_spec),
    ("decimal_step_value_spec", expected_value_spec),
    ("is_positive_power_of_two_spec", expected_power_spec),
    ("decimal_step_allowed", expected_guard),
    ("decimal_step_value", expected_step),
    ("is_positive_power_of_two", expected_power),
    ("accepts_from", expected_model),
    ("accepts", expected_scan),
):
    if compact(function_section(source_text, name)) != compact(expected):
        raise SystemExit(f"{name} changed without updating its linked arithmetic proof")

if "moduleSemanticPositivePowerOfTwoText:" not in compact(source_text) or \
        "constU64_MAX:u64=18446744073709551615.u64()" not in compact(source_text) or \
        "constMAX_PREFIX_BEFORE_DIGIT:u64=1844674407370955161.u64()" not in compact(source_text) or \
        "constASCII_DIGIT_ZERO:u8=48" not in compact(source_text) or \
        "constASCII_DIGIT_NINE:u8=57" not in compact(source_text) or \
        "constMAX_FINAL_DIGIT:u64=5.u64()" not in compact(source_text):
    raise SystemExit("checked decimal accumulator constants changed")
if consumer_text.count('include "./positive_power_of_two_text.elisa"') != 1 or \
        "SemanticPositivePowerOfTwoText::accepts(argument)" not in compact(consumer_text):
    raise SystemExit("alignment annotation validation no longer uses the checked parser")
if semantic_text.count('include "./check_unknown_type_annotation.elisa"') != 1:
    raise SystemExit("semantic root must include the alignment-annotation consumer exactly once")
if 'include "../../src/semantic/positive_power_of_two_text.elisa"' not in positive_text or \
        'include "./positive_power_of_two_text.elisa"' not in negative_text:
    raise SystemExit("proof files must import the production checked parser")

positive_names = {
    "production_loop_matches_recursive_model",
    "accepts_one",
    "accepts_larger_power",
    "accepts_u64_signed_boundary_power",
    "leading_zeroes_preserve_the_decimal_value",
    "rejects_zero",
    "rejects_non_power_of_two",
    "rejects_nondecimal_byte",
    "rejects_u64_maximum",
    "rejects_first_value_above_u64",
    "rejects_overflow_that_would_wrap_to_one",
}
negative_names = {
    "false_claim_overflowing_decimal_is_a_power_of_two",
    "false_claim_zero_is_a_power_of_two",
    "false_claim_u64_maximum_is_a_power_of_two",
}
if declarations(positive_text) != positive_names:
    raise SystemExit("checked alignment-text positive proof inventory changed")
if declarations(negative_text) != negative_names:
    raise SystemExit("checked alignment-text false-claim inventory changed")

positive_cases = {
    "production_loop_matches_recursive_model": '''
def production_loop_matches_recursive_model(text: sview) -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticPositivePowerOfTwoText::accepts(text) == SemanticPositivePowerOfTwoText::accepts_from(text, 0, 0.u64())
''',
    "accepts_one": '''
def accepts_one() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticPositivePowerOfTwoText::accepts("1")
''',
    "accepts_larger_power": '''
def accepts_larger_power() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticPositivePowerOfTwoText::accepts("1024")
''',
    "accepts_u64_signed_boundary_power": '''
def accepts_u64_signed_boundary_power() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticPositivePowerOfTwoText::accepts("9223372036854775808")
''',
    "leading_zeroes_preserve_the_decimal_value": '''
def leading_zeroes_preserve_the_decimal_value() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticPositivePowerOfTwoText::accepts("00016")
''',
    "rejects_zero": '''
def rejects_zero() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return not SemanticPositivePowerOfTwoText::accepts("0")
''',
    "rejects_non_power_of_two": '''
def rejects_non_power_of_two() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return not SemanticPositivePowerOfTwoText::accepts("12")
''',
    "rejects_nondecimal_byte": '''
def rejects_nondecimal_byte() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return not SemanticPositivePowerOfTwoText::accepts("16x")
''',
    "rejects_u64_maximum": '''
def rejects_u64_maximum() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return not SemanticPositivePowerOfTwoText::accepts("18446744073709551615")
''',
    "rejects_first_value_above_u64": '''
def rejects_first_value_above_u64() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return not SemanticPositivePowerOfTwoText::accepts("18446744073709551616")
''',
    "rejects_overflow_that_would_wrap_to_one": '''
def rejects_overflow_that_would_wrap_to_one() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return not SemanticPositivePowerOfTwoText::accepts("18446744073709551617")
''',
}
for name, expected in positive_cases.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"positive proof case {name} changed without updating the admission gate")

negative_cases = {
    "false_claim_overflowing_decimal_is_a_power_of_two": '''
def false_claim_overflowing_decimal_is_a_power_of_two() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticPositivePowerOfTwoText::accepts("18446744073709551617")
''',
    "false_claim_zero_is_a_power_of_two": '''
def false_claim_zero_is_a_power_of_two() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticPositivePowerOfTwoText::accepts("0")
''',
    "false_claim_u64_maximum_is_a_power_of_two": '''
def false_claim_u64_maximum_is_a_power_of_two() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticPositivePowerOfTwoText::accepts("18446744073709551615")
''',
}
for name, expected in negative_cases.items():
    if compact(function_section(negative_text, name)) != compact(expected):
        raise SystemExit(f"false-claim proof case {name} changed without updating the admission gate")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("checked alignment-text proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, CONSUMER, SEMANTIC,
    POSITIVE, NEGATIVE, *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "checked alignment-text proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_after == hashes_before, "proof inputs changed during admission"
