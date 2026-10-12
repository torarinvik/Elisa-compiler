"""Source-bind the backend hex decoder's invalid-byte sentinel across all gaps."""
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
POSITIVE = HERE / "backend_literal_hex_invalid_bytes.elisa"
NEGATIVE = HERE / "backend_literal_hex_invalid_bytes_rejected.elisa"

POSITIVE_SHAPES = {
    "hex_byte_before_decimal_is_rejected": """
        def hex_byte_before_decimal_is_rejected(byte: i64) -> i64:
            requires byte >= 0 and byte < 48
            ensure result == -1
            return byte - 48 if byte >= 48 and byte <= 57 else (byte - 97 + 10 if byte >= 97 and byte <= 102 else (byte - 65 + 10 if byte >= 65 and byte <= 70 else -1))
    """,
    "hex_byte_between_decimal_and_uppercase_is_rejected": """
        def hex_byte_between_decimal_and_uppercase_is_rejected(byte: i64) -> i64:
            requires byte >= 58 and byte <= 64
            ensure result == -1
            return byte - 48 if byte >= 48 and byte <= 57 else (byte - 97 + 10 if byte >= 97 and byte <= 102 else (byte - 65 + 10 if byte >= 65 and byte <= 70 else -1))
    """,
    "hex_byte_between_uppercase_and_lowercase_is_rejected": """
        def hex_byte_between_uppercase_and_lowercase_is_rejected(byte: i64) -> i64:
            requires byte >= 71 and byte <= 96
            ensure result == -1
            return byte - 48 if byte >= 48 and byte <= 57 else (byte - 97 + 10 if byte >= 97 and byte <= 102 else (byte - 65 + 10 if byte >= 65 and byte <= 70 else -1))
    """,
    "hex_byte_after_lowercase_is_rejected": """
        def hex_byte_after_lowercase_is_rejected(byte: i64) -> i64:
            requires byte >= 103 and byte <= 255
            ensure result == -1
            return byte - 48 if byte >= 48 and byte <= 57 else (byte - 97 + 10 if byte >= 97 and byte <= 102 else (byte - 65 + 10 if byte >= 65 and byte <= 70 else -1))
    """,
}
NEGATIVE_SHAPES = {
    "false_hex_byte_47_maps_to_zero": """
        def false_hex_byte_47_maps_to_zero(byte: i64) -> i64:
            requires byte == 47
            ensure result == 0
            return byte - 48 if byte >= 48 and byte <= 57 else (byte - 97 + 10 if byte >= 97 and byte <= 102 else (byte - 65 + 10 if byte >= 65 and byte <= 70 else -1))
    """,
    "false_hex_byte_58_maps_to_ten": """
        def false_hex_byte_58_maps_to_ten(byte: i64) -> i64:
            requires byte == 58
            ensure result == 10
            return byte - 48 if byte >= 48 and byte <= 57 else (byte - 97 + 10 if byte >= 97 and byte <= 102 else (byte - 65 + 10 if byte >= 65 and byte <= 70 else -1))
    """,
    "false_hex_byte_71_maps_to_ten": """
        def false_hex_byte_71_maps_to_ten(byte: i64) -> i64:
            requires byte == 71
            ensure result == 10
            return byte - 48 if byte >= 48 and byte <= 57 else (byte - 97 + 10 if byte >= 97 and byte <= 102 else (byte - 65 + 10 if byte >= 65 and byte <= 70 else -1))
    """,
    "false_hex_byte_103_maps_to_fifteen": """
        def false_hex_byte_103_maps_to_fifteen(byte: i64) -> i64:
            requires byte == 103
            ensure result == 15
            return byte - 48 if byte >= 48 and byte <= 57 else (byte - 97 + 10 if byte >= 97 and byte <= 102 else (byte - 65 + 10 if byte >= 65 and byte <= 70 else -1))
    """,
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


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def require_shape(path: Path, name: str, shape: str) -> None:
    if compact(function_section(path.read_text(), name)) != compact(shape):
        raise SystemExit(f"proof declaration {name} changed its invalid-byte theorem")


if not __debug__:
    raise SystemExit("run without Python -O")

source_text = SOURCE.read_text()
decoder = compact(function_section(source_text, "hex_digit_value"))
if hashlib.sha256(decoder.encode()).hexdigest() != \
        "b6397a60d08f4dc97b2078a5671333a782af29f7c2deb33dfddf65675c7cd71e":
    raise SystemExit("hex_digit_value changed since the sentinel ranges were reviewed")
expected_decoder = compact("""
    def hex_digit_value(byte: u8) -> i64:
        return (byte - 48.u8()).i64() if byte >= 48.u8() and byte <= 57.u8() else ((byte - 97.u8()).i64() + 10 if byte >= 97.u8() and byte <= 102.u8() else ((byte - 65.u8()).i64() + 10 if byte >= 65.u8() and byte <= 70.u8() else -1))
""")
if decoder != expected_decoder:
    raise SystemExit("hex_digit_value no longer partitions digit and letter bytes before the -1 sentinel")

for name, shape in POSITIVE_SHAPES.items():
    require_shape(POSITIVE, name, shape)
for name, shape in NEGATIVE_SHAPES.items():
    require_shape(NEGATIVE, name, shape)
if declarations(POSITIVE) != set(POSITIVE_SHAPES) or declarations(NEGATIVE) != set(NEGATIVE_SHAPES):
    raise SystemExit("hex invalid-byte proof declaration inventory changed")
if not NEGATIVE.read_text().startswith('include "./backend_literal_hex_invalid_bytes.elisa"'):
    raise SystemExit("hex false claims must include the positive invalid-byte theorems")

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("hex invalid-byte proofs require a strict proof build")
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
    assert report["summary"]["semantic_diagnostics"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(POSITIVE_SHAPES)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 8
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "hex invalid-byte report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_SHAPES) + len(NEGATIVE_SHAPES)
assert negative["summary"]["obligations"] == 16 and negative["summary"]["proven"] == 12
assert [goal["name"] for goal in negative["goals"] if not goal["proven"]] == list(NEGATIVE_SHAPES)
assert negative == run(NEGATIVE)[1], "false invalid-byte classifications were not rejected deterministically"

for path, expected in hashes_before.items():
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
        raise SystemExit(f"proof input changed while it was being checked: {path}")

print("hex invalid-byte semantics: four non-hex intervals replay; four false digit claims are refused")
