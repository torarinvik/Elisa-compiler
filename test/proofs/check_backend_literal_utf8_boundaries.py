"""Source-bind exact BMP UTF-8 boundary proofs to the backend encoder."""
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
POSITIVE = HERE / "backend_literal_utf8_boundaries.elisa"
NEGATIVE = HERE / "backend_literal_utf8_boundaries_rejected.elisa"

POSITIVE_SHAPES = {
    "literal_utf8_ascii_max_boundary": """
        def literal_utf8_ascii_max_boundary() -> i64:
            ensure result == 127
            return 127
    """,
    "literal_utf8_two_byte_min_boundary": """
        def literal_utf8_two_byte_min_boundary() -> i64:
            ensure result == 49792
            return 194 * 256 + 128
    """,
    "literal_utf8_two_byte_max_boundary": """
        def literal_utf8_two_byte_max_boundary() -> i64:
            ensure result == 57279
            return 223 * 256 + 191
    """,
    "literal_utf8_three_byte_min_boundary": """
        def literal_utf8_three_byte_min_boundary() -> i64:
            ensure result == 14721152
            return 224 * 65536 + 160 * 256 + 128
    """,
    "literal_utf8_last_scalar_before_surrogates": """
        def literal_utf8_last_scalar_before_surrogates() -> i64:
            ensure result == 15572927
            return 237 * 65536 + 159 * 256 + 191
    """,
    "literal_utf8_first_scalar_after_surrogates": """
        def literal_utf8_first_scalar_after_surrogates() -> i64:
            ensure result == 15630464
            return 238 * 65536 + 128 * 256 + 128
    """,
    "literal_utf8_bmp_max_boundary": """
        def literal_utf8_bmp_max_boundary() -> i64:
            ensure result == 15712191
            return 239 * 65536 + 191 * 256 + 191
    """,
}
NEGATIVE_SHAPES = {
    "false_utf8_two_byte_min_is_c180": """
        def false_utf8_two_byte_min_is_c180() -> bool:
            ensure result == true
            return 194 * 256 + 128 == 49408
    """,
    "false_utf8_d7ff_is_ee9fbf": """
        def false_utf8_d7ff_is_ee9fbf() -> bool:
            ensure result == true
            return 237 * 65536 + 159 * 256 + 191 == 15638463
    """,
    "false_utf8_e000_is_ed8080": """
        def false_utf8_e000_is_ed8080() -> bool:
            ensure result == true
            return 238 * 65536 + 128 * 256 + 128 == 15564928
    """,
}
BOUNDARY_CASES = {
    "literal_utf8_ascii_max_boundary": (127, 127),
    "literal_utf8_two_byte_min_boundary": (128, 49792),
    "literal_utf8_two_byte_max_boundary": (2047, 57279),
    "literal_utf8_three_byte_min_boundary": (2048, 14721152),
    "literal_utf8_last_scalar_before_surrogates": (55295, 15572927),
    "literal_utf8_first_scalar_after_surrogates": (57344, 15630464),
    "literal_utf8_bmp_max_boundary": (65535, 15712191),
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
        raise SystemExit(f"proof declaration {name} changed its exact boundary theorem")


def production_encoding(codepoint: int) -> tuple[list[int], int]:
    """Evaluate the source-pinned push_utf8 formulas at one boundary input."""
    if codepoint < 128:
        octets = [codepoint]
    elif codepoint < 2048:
        octets = [192 + codepoint // 64, 128 + codepoint % 64]
    else:
        octets = [224 + codepoint // 4096,
                  128 + (codepoint // 64) % 64,
                  128 + codepoint % 64]
    packed = 0
    for octet in octets:
        packed = packed * 256 + octet
    return octets, packed


if not __debug__:
    raise SystemExit("run without Python -O")

source_text = SOURCE.read_text()
encoder = compact(function_section(source_text, "push_utf8"))
expected_encoder = compact("""
    def push_utf8(storage: mutable darray[u8]&, codepoint: i64) -> void can[Abort.Panic, Memory.Allocate]:
        can Abort.Panic, Memory.Allocate:
            if codepoint < 128:
                storage.push(codepoint.u8())
                return
            if codepoint < 2048:
                storage.push((192 + (codepoint / 64)).u8())
                storage.push((128 + (codepoint % 64)).u8())
                return
            storage.push((224 + (codepoint / 4096)).u8())
            storage.push((128 + ((codepoint / 64) % 64)).u8())
            storage.push((128 + (codepoint % 64)).u8()
""") + ")"
if hashlib.sha256(encoder.encode()).hexdigest() != \
        "0d65674e8c777d16c3ecfd93772eb65be20873f22a71bd98070eb25968a7df59":
    raise SystemExit("push_utf8 changed since the exact-boundary formulas were reviewed")
if encoder != expected_encoder:
    raise SystemExit("push_utf8 no longer has the byte formulas modeled by this boundary proof")

for name, shape in POSITIVE_SHAPES.items():
    require_shape(POSITIVE, name, shape)
for name, shape in NEGATIVE_SHAPES.items():
    require_shape(NEGATIVE, name, shape)
if declarations(POSITIVE) != set(POSITIVE_SHAPES) or declarations(NEGATIVE) != set(NEGATIVE_SHAPES):
    raise SystemExit("UTF-8 boundary proof declaration inventory changed")
if not NEGATIVE.read_text().startswith('include "./backend_literal_utf8_boundaries.elisa"'):
    raise SystemExit("boundary false claims must include the positive source-bound theorems")
for name, (codepoint, expected_packed) in BOUNDARY_CASES.items():
    octets, actual_packed = production_encoding(codepoint)
    if actual_packed != expected_packed:
        raise SystemExit(f"{name}: pinned push_utf8 formulas produce {octets}, packed as {actual_packed}, not {expected_packed}")

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("UTF-8 boundary theorems require a strict proof build")
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
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 14
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "boundary proof report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_SHAPES) + len(NEGATIVE_SHAPES)
assert negative["summary"]["obligations"] == 20 and negative["summary"]["proven"] == 17
assert len([goal for goal in negative["goals"] if not goal["proven"]]) == len(NEGATIVE_SHAPES)
assert negative == run(NEGATIVE)[1], "false boundary claims were not rejected deterministically"

for path, expected in hashes_before.items():
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
        raise SystemExit(f"proof input changed while it was being checked: {path}")

print("UTF-8 boundary semantics: 14 obligations replay; three incorrect boundary encodings are refused")
