"""Admit overflow-safe EASM decimal parsing against a strict proof product."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "easm_checked_decimal.elisa"
NEGATIVE = HERE / "easm_checked_decimal_rejected.elisa"
HELPER = ROOT / "src/backend/easm_checked_decimal.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
PARSER = ROOT / "src/backend/easm_verify_function.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"
LAYOUT_PARSER = ROOT / "src/backend/easm_parse.elisa"
INTEGRATION = ROOT / "test/breadth/easm_checked_decimal_parse_smoke.elisa"
STDIN_DRIVER = ROOT / "test/breadth/easm_verify_stdin.elisa"
ENFORCEMENT_TEST = ROOT / "scripts/easm_enforcement_fuzz.py"

if not __debug__:
    raise SystemExit("run without Python -O")

helper_text = HELPER.read_text()
env_text = ENV.read_text()
parser_text = PARSER.read_text()
memory_text = MEMORY.read_text()
if 'include "../../src/backend/easm_checked_decimal.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer includes the production checked-digit helpers")
if 'include "./easm_checked_decimal.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer include the production checked-digit helpers")
if 'include "easm_checked_decimal.elisa"' not in env_text:
    raise SystemExit("backend environment no longer imports the checked-digit helpers")
if env_text.index('include "easm_checked_decimal.elisa"') > env_text.index('include "easm_verify_function.elisa"'):
    raise SystemExit("checked-digit helpers are imported after the parser that uses them")

for contract in (
    "ensure result.valid == (value < I64_MAX / DECIMAL_RADIX",
    "ensure result.valid implies result.value == value * DECIMAL_RADIX + digit",
    "ensure not result.valid implies result.value == 0",
    "ensure result.valid == (value > I64_MIN / DECIMAL_RADIX",
    "ensure result.valid implies result.value == value * DECIMAL_RADIX - digit",
):
    if contract not in helper_text:
        raise SystemExit(f"checked decimal helper contract is missing: {contract}")

parser_body = parser_text.split("def easm_parse_i64_checked(text: sview)", 1)[1].split(
    "def easm_parse_i64(text: sview)", 1
)[0]
required_parser_fragments = (
    "EasmCheckedDecimal::ASCII_MINUS",
    "EasmCheckedDecimal::ASCII_DIGIT_ZERO",
    "EasmCheckedDecimal::ASCII_DIGIT_NINE",
    "EasmCheckedDecimal::append_positive_digit(value, digit)",
    "EasmCheckedDecimal::append_negative_digit(value, digit)",
    "return (false, 0) if not step.valid",
    "return (false, 0) if position == sview_len(text)",
)
if not all(fragment in parser_body for fragment in required_parser_fragments):
    raise SystemExit("EASM signed-decimal parser no longer rejects invalid input through checked steps")
if "break if byte <" in parser_body or "value <- value *" in parser_body:
    raise SystemExit("EASM parser bypasses strict digit validation or checked accumulation")
if "value: i64 = easm_parse_i64(easm_trim(fact[marker + 7.usize():sview_len(fact)]))" not in memory_text:
    raise SystemExit("size-guard facts no longer use the hardened signed-decimal parser")

layout_parser_text = LAYOUT_PARSER.read_text()
layout_parse_body = layout_parser_text.split(
    "def parse_layout_module(source: u8&", 1
)[1].split("def parse_module(", 1)[0]
required_layout_fragments = (
    "easm_parse_i64_checked(easm_trim(attributes[5:sview_len(attributes)]))",
    '"invalid-layout-size"',
    "if not parsed_size.valid",
    "easm_parse_i64_checked(easm_trim(attributes[7:sview_len(attributes)]))",
    '"invalid-layout-stride"',
    "if not parsed_stride.valid",
    "easm_parse_i64_checked(easm_trim(rest[guard_start:sview_len(rest)]))",
    '"invalid-layout-required-size"',
    "if not parsed_requirement.valid",
    "easm_parse_i64_checked(offset_text)",
    '"invalid-layout-field-offset"',
    "numeric_offset_prefix and parsed_offset.valid and requires_size_valid",
)
if not all(fragment in layout_parse_body for fragment in required_layout_fragments):
    raise SystemExit("EASM layout parser no longer rejects malformed or overflowing decimal fields")

required_memory_fragments = (
    "def easm_memory_displacement_checked(operand: sview)",
    "return easm_parse_i64_checked(prefix)",
    '"invalid-memory-displacement"',
    "easm_memory_displacement_checked(operand)",
    "def easm_immediate_after_dollar_checked(text: sview)",
    "operand: sview = easm_first_operand(text)",
    "parsed.value < -2147483648 or parsed.value > 2147483647",
)
if not all(fragment in memory_text for fragment in required_memory_fragments):
    raise SystemExit("EASM memory and immediate decimal consumers no longer fail closed")
if '"invalid-stack-adjustment"' not in parser_text or "easm_immediate_after_dollar_checked(inst.text)" not in parser_text:
    raise SystemExit("stack adjustment verification no longer reports malformed immediates")

required_integration_fragments = (
    '"invalid-layout-required-size"',
    "8junk",
    "9223372036854775808",
    "-9223372036854775809",
    '"invalid-layout-field-offset"',
    '"invalid-layout-size"',
    "overflowing_size",
    '"invalid-layout-stride"',
    '"invalid-stack-adjustment"',
    '"invalid-memory-displacement"',
    '"9223372036854775807"',
    '"-9223372036854775808"',
)
integration_text = INTEGRATION.read_text()
if not all(fragment in integration_text for fragment in required_integration_fragments):
    raise SystemExit("EASM decimal integration smoke lost a malformed-input or i64-boundary control")

stdin_driver_text = STDIN_DRIVER.read_text()
if "issues: darray[Easm::Issue] = parsed.issues" not in stdin_driver_text:
    raise SystemExit("EASM stdin verifier no longer preserves parser diagnostics")
enforcement_text = ENFORCEMENT_TEST.read_text()
required_driver_controls = (
    "def required_size_source(value: str) -> str:",
    '("malformed", "8junk")',
    '("overflow", "9223372036854775808")',
    '"invalid-layout-required-size" not in codes',
)
if not all(fragment in enforcement_text for fragment in required_driver_controls):
    raise SystemExit("EASM stdin integration controls lost malformed/overflow required-size rejection")

positive_names = {
    "positive_digit_step_obeys_its_exact_i64_boundary",
    "negative_digit_step_obeys_its_exact_i64_boundary",
    "positive_i64_max_is_reached_without_overflow",
    "negative_i64_min_is_reached_without_overflow",
}
for name in positive_names:
    if f"def {name}(" not in POSITIVE.read_text():
        raise SystemExit(f"positive theorem missing: {name}")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("checked-decimal proof requires a strict proof build")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    HELPER,
    ENV,
    PARSER,
    MEMORY,
    LAYOUT_PARSER,
    INTEGRATION,
    STDIN_DRIVER,
    ENFORCEMENT_TEST,
]
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
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + 2 == negative["summary"]["obligations"]
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "positive_i64_overflow_is_accepted"),
    ("ensure-unproven", "negative_i64_underflow_is_accepted"),
]

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product_manifest, "proof-product provenance changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "signed decimal digit accumulation rejects positive overflow and negative underflow",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [finding["name"] for finding in negative["findings"]],
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
