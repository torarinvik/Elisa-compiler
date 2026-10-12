"""Admit arithmetic semantics for the backend's hexadecimal and UTF-8 literal paths."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
SOURCE = ROOT / "src/backend/codegen_literals_decode.elisa"
POSITIVE = HERE / "backend_literal_decode_semantics.elisa"
NEGATIVE = HERE / "backend_literal_decode_semantics_rejected.elisa"

POSITIVE_NAMES = {
    "literal_hex_decimal_nibble",
    "literal_hex_lowercase_nibble",
    "literal_hex_uppercase_nibble",
    "literal_hex_four_digits_fit_u16",
    "literal_hex_quad_does_not_select_four_byte_utf8",
    "literal_utf8_one_byte_fits",
    "literal_utf8_two_byte_lead_fits",
    "literal_utf8_two_byte_tail_fits",
    "literal_utf8_three_byte_lead_fits",
    "literal_utf8_three_byte_middle_fits",
    "literal_utf8_three_byte_tail_fits",
}
NEGATIVE_NAMES = {
    "false_literal_hex_upper_f_maps_to_sixteen",
    "false_literal_hex_quad_max_exceeds_u16",
    "false_literal_utf8_three_byte_tail_is_192",
}

# Hashes omit comments and whitespace, but cover the full executable bodies. Any
# algorithm change requires a fresh review of the source-to-model correspondence.
FUNCTION_SHA256 = {
    "hex_digit_value": "b6397a60d08f4dc97b2078a5671333a782af29f7c2deb33dfddf65675c7cd71e",
    "push_utf8": "0d65674e8c777d16c3ecfd93772eb65be20873f22a71bd98070eb25968a7df59",
    "decode_string_escapes": "e9b9c0245ce4e05f35e8164f88ff55bf6c5ac5f1eed4f4720d21aeb4c33a0472",
}


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one declaration named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def function_hash(source: str, name: str) -> str:
    return hashlib.sha256(compact(function_section(source, name)).encode()).hexdigest()


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def require_shape(path: Path, name: str, shape: str) -> None:
    if compact(function_section(path.read_text(), name)) != compact(shape):
        raise SystemExit(f"proof declaration {name} changed its verified arithmetic statement")


if not __debug__:
    raise SystemExit("run without Python -O")

source_text = SOURCE.read_text()
for name, expected in FUNCTION_SHA256.items():
    if function_hash(source_text, name) != expected:
        raise SystemExit(f"{name} changed since its source-bound semantic proof; re-review the full function")

hex_decoder = compact(function_section(source_text, "hex_digit_value"))
if hex_decoder != compact(
        "def hex_digit_value(byte: u8) -> i64: "
        "return (byte - 48.u8()).i64() if byte >= 48.u8() and byte <= 57.u8() else "
        "((byte - 97.u8()).i64() + 10 if byte >= 97.u8() and byte <= 102.u8() else "
        "((byte - 65.u8()).i64() + 10 if byte >= 65.u8() and byte <= 70.u8() else -1))"):
    raise SystemExit("hex escape nibble classes or their decimal/letter mappings changed")

utf8 = compact(function_section(source_text, "push_utf8"))
utf8_steps = (
    "if codepoint < 128:",
    "storage.push(codepoint.u8())",
    "return",
    "if codepoint < 2048:",
    "storage.push((192 + (codepoint / 64)).u8())",
    "storage.push((128 + (codepoint % 64)).u8())",
    "return",
    "storage.push((224 + (codepoint / 4096)).u8())",
    "storage.push((128 + ((codepoint / 64) % 64)).u8())",
    "storage.push((128 + (codepoint % 64)).u8())",
)
cursor = 0
for step in utf8_steps:
    position = utf8.find(compact(step), cursor)
    if position < 0:
        raise SystemExit(f"UTF-8 encoder lost or reordered a proved byte formula: {step}")
    cursor = position + len(compact(step))

decoder = compact(function_section(source_text, "decode_string_escapes"))
decoder_steps = (
    "if next_byte == 120 or next_byte == 117:",
    "hex_digits: usize = 2.usize() if next_byte == 120 else 4.usize()",
    "hex_start: usize = next_index + 1.usize()",
    "hex_available: usize = length - hex_start",
    "hex_ok: mutable bool = hex_digits <= hex_available",
    "while hex_index < hex_digits and hex_ok |hex_index, hex_value, hex_ok, text, hex_start, hex_digits|:",
    "hex_at: i64 = hex_digit_value(sview_at(text, hex_start + hex_index))",
    "hex_ok <- false if hex_at < 0",
    "hex_value <- hex_value * 16 + hex_at if hex_at >= 0",
    "hex_index <- hex_index + 1.usize()",
    "if hex_ok:",
    "push_utf8(storage, hex_value) if next_byte == 117",
)
cursor = 0
for step in decoder_steps:
    position = decoder.find(compact(step), cursor)
    if position < 0:
        raise SystemExit(f"escape decoder no longer establishes the proved UTF-8 input path: {step}")
    cursor = position + len(compact(step))

positive_shapes = {
    "literal_hex_decimal_nibble": """
        def literal_hex_decimal_nibble(byte: i64) -> i64:
            requires byte >= 48 and byte <= 57
            ensure result >= 0
            ensure result <= 9
            ensure result == byte - 48
            return byte - 48
    """,
    "literal_hex_lowercase_nibble": """
        def literal_hex_lowercase_nibble(byte: i64) -> i64:
            requires byte >= 97 and byte <= 102
            ensure result >= 10
            ensure result <= 15
            ensure result == byte - 97 + 10
            return byte - 97 + 10
    """,
    "literal_hex_uppercase_nibble": """
        def literal_hex_uppercase_nibble(byte: i64) -> i64:
            requires byte >= 65 and byte <= 70
            ensure result >= 10
            ensure result <= 15
            ensure result == byte - 65 + 10
            return byte - 65 + 10
    """,
    "literal_hex_four_digits_fit_u16": """
        def literal_hex_four_digits_fit_u16(a: i64, b: i64, c: i64, d: i64) -> i64:
            requires a >= 0 and a <= 15
            requires b >= 0 and b <= 15
            requires c >= 0 and c <= 15
            requires d >= 0 and d <= 15
            ensure result >= 0
            ensure result <= 65535
            ensure result == ((a * 16 + b) * 16 + c) * 16 + d
            return ((a * 16 + b) * 16 + c) * 16 + d
    """,
    "literal_hex_quad_does_not_select_four_byte_utf8": """
        def literal_hex_quad_does_not_select_four_byte_utf8(a: i64, b: i64, c: i64, d: i64) -> bool:
            requires a >= 0 and a <= 15
            requires b >= 0 and b <= 15
            requires c >= 0 and c <= 15
            requires d >= 0 and d <= 15
            ensure result == true
            codepoint: i64 = ((a * 16 + b) * 16 + c) * 16 + d
            return codepoint < 65536
    """,
    "literal_utf8_one_byte_fits": """
        def literal_utf8_one_byte_fits(code: i64) -> i64:
            requires code >= 0 and code < 128
            ensure result >= 0
            ensure result <= 127
            ensure result == code
            return code
    """,
    "literal_utf8_two_byte_lead_fits": """
        def literal_utf8_two_byte_lead_fits(code: i64) -> i64:
            requires code >= 128 and code < 2048
            ensure result >= 194
            ensure result <= 223
            return 192 + code / 64
    """,
    "literal_utf8_two_byte_tail_fits": """
        def literal_utf8_two_byte_tail_fits(code: i64) -> i64:
            requires code >= 128 and code < 2048
            ensure result >= 128
            ensure result <= 191
            return 128 + code % 64
    """,
    "literal_utf8_three_byte_lead_fits": """
        def literal_utf8_three_byte_lead_fits(code: i64) -> i64:
            requires code >= 2048 and code < 65536
            ensure result >= 224
            ensure result <= 239
            return 224 + code / 4096
    """,
    "literal_utf8_three_byte_middle_fits": """
        def literal_utf8_three_byte_middle_fits(code: i64) -> i64:
            requires code >= 2048 and code < 65536
            ensure result >= 128
            ensure result <= 191
            return 128 + (code / 64) % 64
    """,
    "literal_utf8_three_byte_tail_fits": """
        def literal_utf8_three_byte_tail_fits(code: i64) -> i64:
            requires code >= 2048 and code < 65536
            ensure result >= 128
            ensure result <= 191
            return 128 + code % 64
    """,
}
for name, shape in positive_shapes.items():
    require_shape(POSITIVE, name, shape)

negative_shapes = {
    "false_literal_hex_upper_f_maps_to_sixteen": """
        def false_literal_hex_upper_f_maps_to_sixteen() -> bool:
            ensure result == true
            return 70 - 65 + 10 == 16
    """,
    "false_literal_hex_quad_max_exceeds_u16": """
        def false_literal_hex_quad_max_exceeds_u16() -> bool:
            ensure result == true
            return ((15 * 16 + 15) * 16 + 15) * 16 + 15 == 65536
    """,
    "false_literal_utf8_three_byte_tail_is_192": """
        def false_literal_utf8_three_byte_tail_is_192() -> bool:
            ensure result == true
            return 128 + 2048 % 64 == 192
    """,
}
for name, shape in negative_shapes.items():
    require_shape(NEGATIVE, name, shape)

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("literal decoder semantic proof declaration inventory changed")
if not NEGATIVE.read_text().startswith('include "./backend_literal_decode_semantics.elisa"'):
    raise SystemExit("literal decoder semantic false claims must include the positive theorems")

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("literal decoder semantic proofs require a strict proof build")
stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    SOURCE,
    POSITIVE,
    NEGATIVE,
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
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(POSITIVE_NAMES)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 37
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "literal decoder semantic proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_NAMES) + len(NEGATIVE_NAMES)
assert negative["summary"]["obligations"] == 43 and negative["summary"]["proven"] == 40
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product, "proof product provenance changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "hex digit value classes, four-digit Unicode escape range, and UTF-8 byte ranges for every production encoder branch",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
