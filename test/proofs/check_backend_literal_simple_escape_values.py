"""Source-bind the byte values produced by the backend's simple string escapes."""
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
POSITIVE = HERE / "backend_literal_simple_escape_values.elisa"
NEGATIVE = HERE / "backend_literal_simple_escape_values_rejected.elisa"

POSITIVE_SHAPES = {
    "literal_newline_escape_maps_to_lf": """
        def literal_newline_escape_maps_to_lf(escape: i64) -> i64:
            requires escape == 110
            ensure result == 10
            return 10 if escape == 110 else escape
    """,
    "literal_tab_escape_maps_to_tab": """
        def literal_tab_escape_maps_to_tab(escape: i64) -> i64:
            requires escape == 116
            ensure result == 9
            return 9 if escape == 116 else escape
    """,
    "literal_carriage_return_escape_maps_to_cr": """
        def literal_carriage_return_escape_maps_to_cr(escape: i64) -> i64:
            requires escape == 114
            ensure result == 13
            return 13 if escape == 114 else escape
    """,
    "literal_nul_escape_maps_to_zero": """
        def literal_nul_escape_maps_to_zero(escape: i64) -> i64:
            requires escape == 48
            ensure result == 0
            return 0 if escape == 48 else escape
    """,
    "literal_backslash_escape_preserves_backslash": """
        def literal_backslash_escape_preserves_backslash(escape: i64) -> i64:
            requires escape == 92
            ensure result == 92
            return escape
    """,
    "literal_double_quote_escape_preserves_quote": """
        def literal_double_quote_escape_preserves_quote(escape: i64) -> i64:
            requires escape == 34
            ensure result == 34
            return escape
    """,
    "literal_single_quote_escape_preserves_quote": """
        def literal_single_quote_escape_preserves_quote(escape: i64) -> i64:
            requires escape == 39
            ensure result == 39
            return escape
    """,
}
NEGATIVE_SHAPES = {
    "false_newline_escape_maps_to_cr": """
        def false_newline_escape_maps_to_cr(escape: i64) -> i64:
            requires escape == 110
            ensure result == 13
            return 10 if escape == 110 else escape
    """,
    "false_tab_escape_maps_to_lf": """
        def false_tab_escape_maps_to_lf(escape: i64) -> i64:
            requires escape == 116
            ensure result == 10
            return 9 if escape == 116 else escape
    """,
    "false_nul_escape_maps_to_character_zero": """
        def false_nul_escape_maps_to_character_zero(escape: i64) -> i64:
            requires escape == 48
            ensure result == 48
            return 0 if escape == 48 else escape
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
        raise SystemExit(f"proof declaration {name} changed its simple-escape theorem")


if not __debug__:
    raise SystemExit("run without Python -O")

source_text = SOURCE.read_text()
decoder = compact(function_section(source_text, "decode_string_escapes"))
if hashlib.sha256(decoder.encode()).hexdigest() != \
        "e9b9c0245ce4e05f35e8164f88ff55bf6c5ac5f1eed4f4720d21aeb4c33a0472":
    raise SystemExit("decode_string_escapes changed since its simple-escape byte mapping was reviewed")
expected_mapping = compact("""
    decoded: u8 = when next_byte:
        110 -> 10
        116 -> 9
        114 -> 13
        48 -> 0
        _ -> next_byte
    storage.push(decoded)
""")
if expected_mapping not in decoder:
    raise SystemExit("backend simple-escape arms changed from the byte mapping specified here")

for name, shape in POSITIVE_SHAPES.items():
    require_shape(POSITIVE, name, shape)
for name, shape in NEGATIVE_SHAPES.items():
    require_shape(NEGATIVE, name, shape)
if declarations(POSITIVE) != set(POSITIVE_SHAPES) or declarations(NEGATIVE) != set(NEGATIVE_SHAPES):
    raise SystemExit("simple-escape proof declaration inventory changed")
if not NEGATIVE.read_text().startswith('include "./backend_literal_simple_escape_values.elisa"'):
    raise SystemExit("simple-escape false claims must include the positive source-bound theorems")

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("simple-escape theorems require a strict proof build")
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
assert positive == run(POSITIVE)[1], "simple-escape proof report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_SHAPES) + len(NEGATIVE_SHAPES)
assert negative["summary"]["obligations"] == 20 and negative["summary"]["proven"] == 17
assert len([goal for goal in negative["goals"] if not goal["proven"]]) == len(NEGATIVE_SHAPES)
assert negative == run(NEGATIVE)[1], "false simple-escape claims were not rejected deterministically"

for path, expected in hashes_before.items():
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
        raise SystemExit(f"proof input changed while it was being checked: {path}")

print("simple string escapes: seven exact byte mappings replay; three false mappings are refused")
