"""Admit byte-count semantics for backend source-literal escape decoding."""
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
POSITIVE = HERE / "backend_literal_decode_lengths.elisa"
NEGATIVE = HERE / "backend_literal_decode_lengths_rejected.elisa"
POSITIVE_NAMES = {
    "literal_hex_pair_value_fits_u8",
    "literal_raw_byte_strlen_contribution",
    "literal_hex_escape_strlen_contribution",
    "literal_unicode_escape_encoded_width",
    "literal_unicode_escape_strlen_contribution",
    "literal_simple_escape_strlen_contribution",
}
NEGATIVE_NAMES = {
    "false_literal_x_escape_contributes_two_bytes",
    "false_literal_unicode_0800_uses_two_bytes",
    "false_cstr_nul_escape_contributes_one_byte",
}

FUNCTION_SHA256 = {
    "hex_digit_value": "b6397a60d08f4dc97b2078a5671333a782af29f7c2deb33dfddf65675c7cd71e",
    "push_utf8": "107894c98de754e4b12241cdb65fa7add39a1c876a3e4b33daae9d9ddef7c806",
    "decode_string_escapes": "45fea57369382104303b0e5bde8812f92ccba34c8d672e3ecea87495e1e687fe",
    "decoded_literal_byte_count": "43d7e7d396d281b64d685930657722a43c5cedfa56c2d5105280e5aca8c59588",
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
        raise SystemExit(f"proof declaration {name} changed its byte-count theorem")


def require_ordered(source: str, name: str, steps: tuple[str, ...], label: str) -> None:
    body = compact(function_section(source, name))
    cursor = 0
    for step in steps:
        wanted = compact(step)
        position = body.find(wanted, cursor)
        if position < 0:
            raise SystemExit(f"{label}: missing or reordered source transition: {step}")
        cursor = position + len(wanted)


if not __debug__:
    raise SystemExit("run without Python -O")

source_text = SOURCE.read_text()
for name, expected in FUNCTION_SHA256.items():
    actual = hashlib.sha256(compact(function_section(source_text, name)).encode()).hexdigest()
    if actual != expected:
        raise SystemExit(f"{name} changed since its source-bound byte-count proof; re-review the full function")

# These source transitions connect the arithmetic model to both paths that consume
# the decoded token: storage emission and the allocation-free C-string byte count.
require_ordered(source_text, "decode_string_escapes", (
    "if next_byte == 120 or next_byte == 117:",
    "hex_digits: usize = 2.usize() if next_byte == 120 else 4.usize()",
    "hex_ok: mutable bool = hex_digits <= hex_available",
    "if hex_start <= text.len and hex_digits <= text.len - hex_start:",
    "hex_value <- hex_escape_value(text, hex_start, hex_digits)",
    "if hex_ok:",
    "if next_byte == 117 and hex_value >= 55296 and hex_value <= 56319:",
    "if low_escape_start <= text.len:",
    "pair_codepoint: i64 = utf16_surrogate_pair_codepoint(text, low_escape_start, hex_value)",
    "push_utf8(storage, pair_codepoint)",
    "index <- low_escape_start + 6.usize()",
    "if next_byte == 117 and hex_value >= 56320 and hex_value <= 57343:",
    "all_known <- false",
    "push_utf8(storage, hex_value) if next_byte == 117",
    "storage.push(hex_value.u8()) if next_byte == 120",
    "known: bool = next_byte == 110 or next_byte == 116 or next_byte == 114 or next_byte == 48 or next_byte == 92 or next_byte == 34 or next_byte == 39",
    "decoded: u8 = when next_byte:",
    "110 -> 10",
    "116 -> 9",
    "114 -> 13",
    "48 -> 0",
    "_ -> next_byte",
    "storage.push(decoded)",
), "escape emitter")
require_ordered(source_text, "push_utf8", (
    "if codepoint < 128:",
    "storage.push(codepoint.u8())",
    "return",
    "if codepoint < 2048:",
    "storage.push((192 + (codepoint / 64)).u8())",
    "storage.push((128 + (codepoint % 64)).u8())",
    "return",
    "if codepoint < 65536:",
    "storage.push((224 + (codepoint / 4096)).u8())",
    "storage.push((128 + ((codepoint / 64) % 64)).u8())",
    "storage.push((128 + (codepoint % 64)).u8())",
    "return",
    "storage.push((240 + (codepoint / 262144)).u8())",
    "storage.push((128 + ((codepoint / 4096) % 64)).u8())",
    "storage.push((128 + ((codepoint / 64) % 64)).u8())",
    "storage.push((128 + (codepoint % 64)).u8())",
), "UTF-8 emitter")
require_ordered(source_text, "decoded_literal_byte_count", (
    "while index < length |index, count, text, length|:",
    "byte: u8 = text[index]",
    "remaining: usize = length - index",
    "if byte != 92 or remaining <= 1:",
    "count return if stop_at_nul and byte == 0",
    "count <- count + 1",
    "next_byte: u8 = text[next_index]",
    "if next_byte == 120 or next_byte == 117:",
    "hex_digits: usize = 2.usize() if next_byte == 120 else 4.usize()",
    "-1 return if hex_start > text.len",
    "-1 return if hex_digits > hex_available",
    "-1 return if hex_digits > text.len - hex_start",
    "hex_value: i64 = hex_escape_value(text, hex_start, hex_digits)",
    "-1 return if hex_value < 0",
    "if next_byte == 117 and hex_value >= 55296 and hex_value <= 56319:",
    "-1 return if low_escape_start > text.len",
    "pair_codepoint: i64 = utf16_surrogate_pair_codepoint(text, low_escape_start, hex_value)",
    "-1 return if pair_codepoint < 0",
    "count <- count + 4",
    "index <- low_escape_start + 6.usize()",
    "-1 return if next_byte == 117 and hex_value >= 56320 and hex_value <= 57343",
    "count return if stop_at_nul and hex_value == 0",
    "count <- count + (1 if next_byte == 120 or hex_value < 128 else (2 if hex_value < 2048 else 3))",
    "known: bool = next_byte == 110 or next_byte == 116 or next_byte == 114 or next_byte == 48 or next_byte == 92 or next_byte == 34 or next_byte == 39",
    "-1 return if not known",
    "count return if stop_at_nul and next_byte == 48",
    "count <- count + 1",
), "literal byte counter")

positive_shapes = {
    "literal_hex_pair_value_fits_u8": """
        def literal_hex_pair_value_fits_u8(high: i64, low: i64) -> i64:
            requires high >= 0 and high <= 15
            requires low >= 0 and low <= 15
            ensure result == high * 16 + low
            ensure result >= 0
            ensure result <= 255
            return high * 16 + low
    """,
    "literal_raw_byte_strlen_contribution": """
        def literal_raw_byte_strlen_contribution(byte: i64, stop_at_nul: bool) -> i64:
            requires byte >= 0 and byte <= 255
            ensure result == (0 if stop_at_nul and byte == 0 else 1)
            return 0 if stop_at_nul and byte == 0 else 1
    """,
    "literal_hex_escape_strlen_contribution": """
        def literal_hex_escape_strlen_contribution(value: i64, stop_at_nul: bool) -> i64:
            requires value >= 0 and value <= 255
            ensure result == (0 if stop_at_nul and value == 0 else 1)
            return 0 if stop_at_nul and value == 0 else 1
    """,
    "literal_unicode_escape_encoded_width": """
        def literal_unicode_escape_encoded_width(codepoint: i64) -> i64:
            requires codepoint >= 0 and codepoint <= 65535
            requires codepoint < 55296 or codepoint > 57343
            ensure result >= 1
            ensure result <= 3
            ensure result == (1 if codepoint < 128 else (2 if codepoint < 2048 else 3))
            return 1 if codepoint < 128 else (2 if codepoint < 2048 else 3)
    """,
    "literal_unicode_escape_strlen_contribution": """
        def literal_unicode_escape_strlen_contribution(codepoint: i64, stop_at_nul: bool) -> i64:
            requires codepoint >= 0 and codepoint <= 65535
            requires codepoint < 55296 or codepoint > 57343
            ensure result >= 0
            ensure result <= 3
            ensure result == (0 if stop_at_nul and codepoint == 0 else (1 if codepoint < 128 else (2 if codepoint < 2048 else 3)))
            return 0 if stop_at_nul and codepoint == 0 else (1 if codepoint < 128 else (2 if codepoint < 2048 else 3))
    """,
    "literal_simple_escape_strlen_contribution": """
        def literal_simple_escape_strlen_contribution(escape: i64, stop_at_nul: bool) -> i64:
            requires escape == 110 or escape == 116 or escape == 114 or escape == 48 or escape == 92 or escape == 34 or escape == 39
            ensure result == (0 if stop_at_nul and escape == 48 else 1)
            return 0 if stop_at_nul and escape == 48 else 1
    """,
}
for name, shape in positive_shapes.items():
    require_shape(POSITIVE, name, shape)

negative_shapes = {
    "false_literal_x_escape_contributes_two_bytes": """
        def false_literal_x_escape_contributes_two_bytes(claimed_count: i64) -> bool:
            requires claimed_count == 1
            ensure result == true
            return claimed_count == 2
    """,
    "false_literal_unicode_0800_uses_two_bytes": """
        def false_literal_unicode_0800_uses_two_bytes(codepoint: i64) -> bool:
            requires codepoint == 2048
            ensure result == true
            return (1 if codepoint < 128 else (2 if codepoint < 2048 else 3)) == 2
    """,
    "false_cstr_nul_escape_contributes_one_byte": """
        def false_cstr_nul_escape_contributes_one_byte(stop_at_nul: bool) -> bool:
            requires stop_at_nul
            ensure result == true
            return (0 if stop_at_nul else 1) == 1
    """,
}
for name, shape in negative_shapes.items():
    require_shape(NEGATIVE, name, shape)

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("literal byte-count proof declaration inventory changed")
if not NEGATIVE.read_text().startswith('include "./backend_literal_decode_lengths.elisa"'):
    raise SystemExit("byte-count false claims must include the positive source-linked theorems")

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("literal byte-count proofs require a strict proof build")
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
assert positive["summary"]["declarations"] == len(POSITIVE_NAMES)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 18
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "literal byte-count proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_NAMES) + len(NEGATIVE_NAMES)
assert negative["summary"]["obligations"] == 24 and negative["summary"]["proven"] == 21
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product, "proof product provenance changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "raw-byte, hexadecimal, Unicode, and simple-escape length contributions, including C-string NUL truncation",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
