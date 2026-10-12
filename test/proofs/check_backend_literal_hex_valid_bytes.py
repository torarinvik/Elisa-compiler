"""Source-bind proofs for valid hexadecimal-byte nibble conversion."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
SOURCE = ROOT / "src/backend/codegen_literals_decode.elisa"
POSITIVE = HERE / "backend_literal_hex_valid_bytes.elisa"
NEGATIVE = HERE / "backend_literal_hex_valid_bytes_rejected.elisa"

SOURCE_HASH = "b6397a60d08f4dc97b2078a5671333a782af29f7c2deb33dfddf65675c7cd71e"
DECODER = (
    "byte - 48 if byte >= 48 and byte <= 57 else "
    "(byte - 97 + 10 if byte >= 97 and byte <= 102 else "
    "(byte - 65 + 10 if byte >= 65 and byte <= 70 else -1))"
)


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


if not __debug__:
    raise SystemExit("run without Python -O")

source_text = SOURCE.read_text()
decoder = compact(function_section(source_text, "hex_digit_value"))
if hashlib.sha256(decoder.encode()).hexdigest() != SOURCE_HASH:
    raise SystemExit("hex_digit_value changed since its byte intervals were proved")
if decoder != compact(f"""
    def hex_digit_value(byte: u8) -> i64:
        return (byte - 48.u8()).i64() if byte >= 48.u8() and byte <= 57.u8() else ((byte - 97.u8()).i64() + 10 if byte >= 97.u8() and byte <= 102.u8() else ((byte - 65.u8()).i64() + 10 if byte >= 65.u8() and byte <= 70.u8() else -1))
"""):
    raise SystemExit("production hex decoder no longer has the verified three-range mapping")

positive_shapes = {
    "decimal_hex_byte_maps_to_its_nibble": f"""
        def decimal_hex_byte_maps_to_its_nibble(byte: i64) -> i64:
            requires byte >= 48 and byte <= 57
            ensure result == byte - 48
            ensure result >= 0 and result <= 9
            return {DECODER}
    """,
    "uppercase_hex_byte_maps_to_its_nibble": f"""
        def uppercase_hex_byte_maps_to_its_nibble(byte: i64) -> i64:
            requires byte >= 65 and byte <= 70
            ensure result == byte - 55
            ensure result >= 10 and result <= 15
            return {DECODER}
    """,
    "lowercase_hex_byte_maps_to_its_nibble": f"""
        def lowercase_hex_byte_maps_to_its_nibble(byte: i64) -> i64:
            requires byte >= 97 and byte <= 102
            ensure result == byte - 87
            ensure result >= 10 and result <= 15
            return {DECODER}
    """,
    "uppercase_and_lowercase_hex_letters_have_equal_nibbles": """
        def uppercase_and_lowercase_hex_letters_have_equal_nibbles(byte: i64) -> bool:
            requires byte >= 65 and byte <= 70
            ensure result == true
            upper: i64 = byte - 55
            lower: i64 = byte + 32 - 87
            return upper == lower
    """,
}
negative_shapes = {
    "uppercase_A_must_map_to_zero": """
        def uppercase_A_must_map_to_zero(byte: i64) -> i64:
            requires byte == 65
            ensure result == 0
            return byte - 55
    """,
    "lowercase_f_must_map_to_sixteen": """
        def lowercase_f_must_map_to_sixteen(byte: i64) -> i64:
            requires byte == 102
            ensure result == 16
            return byte - 87
    """,
    "lowercase_a_must_be_distinct_from_uppercase_A": """
        def lowercase_a_must_be_distinct_from_uppercase_A(byte: i64) -> bool:
            requires byte == 65
            ensure result == true
            upper: i64 = byte - 55
            lower: i64 = byte + 32 - 87
            return upper != lower
    """,
}

for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    proof_text = path.read_text()
    if declarations(path) != set(shapes):
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    for name, expected in shapes.items():
        if compact(function_section(proof_text, name)) != compact(expected):
            raise SystemExit(f"{name} no longer proves the source-bound hexadecimal mapping")
if not NEGATIVE.read_text().startswith('include "./backend_literal_hex_valid_bytes.elisa"'):
    raise SystemExit("false nibble claims must include the valid-byte proofs")

manifest = require_current_product(BIN, PROVER)
if manifest.get("compile_mode") != "strict":
    raise SystemExit("hex valid-byte proofs require a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, SOURCE, POSITIVE, NEGATIVE,
    HERE / "proof_product_gate.py", Path(__file__),
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == 4
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 11
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "valid hexadecimal-byte proof changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == 7
assert negative["summary"]["obligations"] == 17 and negative["summary"]["proven"] == 14
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_shapes
}
assert negative == run(NEGATIVE)[1], "false hexadecimal-byte claims changed across identical runs"

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof input changed during replay"
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "decimal, uppercase, and lowercase hexadecimal byte mappings and case equivalence",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_shapes),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
