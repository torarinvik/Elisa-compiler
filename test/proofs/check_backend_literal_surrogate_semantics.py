"""Prove surrogate-pair semantics and bind pair emission/counting to the backend."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure

argument_parser = argparse.ArgumentParser()
argument_parser.add_argument("--source-only", action="store_true",
                             help="check source and proof bindings without running Elisa-Proof")
ARGS = argument_parser.parse_args()

ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=not ARGS.source_only)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
BACKEND = ROOT / "src/backend/codegen_literals_decode.elisa"
FIXTURE = ROOT / "test/fixtures/lexer/token_model_escapes.elisa"
POSITIVE = HERE / "backend_literal_surrogate_semantics.elisa"
NEGATIVE = HERE / "backend_literal_surrogate_semantics_rejected.elisa"
POSITIVE_NAMES = {
    "literal_surrogate_pair_codepoint_is_unicode_scalar",
    "literal_supplementary_scalar_has_four_byte_utf8_width",
    "literal_high_surrogate_is_not_a_unicode_scalar",
    "literal_low_surrogate_is_not_a_unicode_scalar",
    "literal_unpaired_surrogate_contributes_no_decoded_bytes",
    "literal_two_surrogate_code_units_are_not_the_pair_encoding_width",
    "literal_surrogate_pair_contributes_four_decoded_bytes",
}
NEGATIVE_NAMES = {
    "false_isolated_high_surrogate_is_scalar",
    "false_isolated_low_surrogate_is_scalar",
    "false_valid_surrogate_pair_uses_three_bytes",
}

FUNCTION_SHA256 = {
    ("backend", "push_utf8"): "107894c98de754e4b12241cdb65fa7add39a1c876a3e4b33daae9d9ddef7c806",
    ("backend", "hex_escape_value"): "5f7db2bb2b8a54e6ea70df157056148316da91cff221efc63cf781159fa3774a",
    ("backend", "utf16_surrogate_pair_codepoint"): "4dc66116af2c3f7bd69939116e10b83ee5ac5b7a671a959ab7e45201a3e2f04b",
    ("backend", "decode_string_escapes"): "45fea57369382104303b0e5bde8812f92ccba34c8d672e3ecea87495e1e687fe",
    ("backend", "decoded_literal_byte_count"): "676ede9ce04af6c170349b64f2e7630e6f813bc3de635589ba48dd7537c114d9",
    ("fixture", "frontend_surrogate_pair_codepoint"): "419f247a1fe86e5c01984fb2f6dbcf7ddd9f9de061ad3f37914dc082726ebbf6",
    ("fixture", "frontend_is_high_surrogate"): "f3769c64344527b1990890508777da5abae3973695a38c0e95ed80675e60e339",
    ("fixture", "frontend_is_low_surrogate"): "bc6916ae72b6ae0662c23989e17e34db7b132be3b44ab11315d031e537d4b3a9",
    ("fixture", "frontend_decoded_utf8_len"): "0427bb3fdb65b433857278c8307f58ec6a713ea3ef288152579029c40b5803bf",
    ("fixture", "frontend_decoded_escape"): "ed1b3c1d09389f84a441d14d9cb114524db19c352ee8b43d9e4247b77feac356",
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
        raise SystemExit(f"proof declaration {name} changed its scalar specification")


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

backend_text = BACKEND.read_text()
fixture_text = FIXTURE.read_text()
for (owner, name), expected in FUNCTION_SHA256.items():
    source = backend_text if owner == "backend" else fixture_text
    actual = hashlib.sha256(compact(function_section(source, name)).encode()).hexdigest()
    if actual != expected:
        raise SystemExit(f"{owner}.{name} changed since the surrogate specification was source-bound")

# The lexer model consumes a complete high/low escape pair as one scalar. It emits
# zero decoded bytes for an isolated high or low code unit, matching the stage0
# lexer's explicit invalid-surrogate diagnostic path.
require_ordered(fixture_text, "frontend_decoded_escape", (
    "if esc == 'u':",
    "if not frontend_fixed_hex_value(value, esc_index + 1, 4, &codepoint):",
    "if frontend_is_high_surrogate(codepoint):",
    "if esc_index + 6 < value.len and value[esc_index + 5] == '\\\\' and value[esc_index + 6] == 'u':",
    "if frontend_fixed_hex_value(value, esc_index + 7, 4, &low) and frontend_is_low_surrogate(low):",
    "paired: int = frontend_surrogate_pair_codepoint(codepoint, low)",
    "return FrontendDecodedEscape{next_index: esc_index + 11, byte_len: frontend_decoded_utf8_len(paired), hash: frontend_hash_utf8_codepoint(hash, paired)}",
    "return FrontendDecodedEscape{next_index: next, byte_len: 0, hash: hash}",
    "if frontend_is_low_surrogate(codepoint):",
    "return FrontendDecodedEscape{next_index: next, byte_len: 0, hash: hash}",
), "lexer token model")
surrogate_fixture_lines = [line for line in fixture_text.splitlines() if "surrogate: cstr" in line]
if len(surrogate_fixture_lines) != 1 or surrogate_fixture_lines[0].count("D83D") != 2 or \
        surrogate_fixture_lines[0].count("DE00") != 2:
    raise SystemExit("lexer fixture no longer exercises a valid surrogate pair and isolated high/low units")
if "17793447398112395163" not in compact(fixture_text):
    raise SystemExit("surrogate escape checksum control disappeared from the lexer fixture")

# The backend consumes an adjacent valid high/low escape pair as one Unicode
# scalar. Both emission and the allocation-free counter call the same pair
# decoder; isolated surrogate units remain unknown rather than being encoded
# as invalid UTF-8 scalar values.
require_ordered(backend_text, "utf16_surrogate_pair_codepoint", (
    "remaining: usize = text.len - low_escape_start",
    "return -1 if:",
    "remaining < 6",
    "text[low_escape_start] != 92 or text[low_escape_start + 1.usize()] != 117",
    "low: i64 = hex_escape_value(text, low_escape_start + 2.usize(), 4.usize())",
    "return -1 if low < 56320 or low > 57343",
    "return 65536 + (high - 55296) * 1024 + (low - 56320)",
), "backend surrogate-pair scalar conversion")
require_ordered(backend_text, "decode_string_escapes", (
    "if next_byte == 120 or next_byte == 117:",
    "hex_digits: usize = 2.usize() if next_byte == 120 else 4.usize()",
    "hex_value <- hex_escape_value(text, hex_start, hex_digits)",
    "if next_byte == 117 and hex_value >= 55296 and hex_value <= 56319:",
    "low_escape_start: usize = hex_start + hex_digits",
    "if low_escape_start <= text.len:",
    "pair_codepoint: i64 = utf16_surrogate_pair_codepoint(text, low_escape_start, hex_value)",
    "if pair_codepoint >= 0:",
    "push_utf8(storage, pair_codepoint)",
    "index <- low_escape_start + 6.usize()",
    "continue",
    "all_known <- false",
    "if next_byte == 117 and hex_value >= 56320 and hex_value <= 57343:",
    "all_known <- false",
    "index <- hex_start + hex_digits",
), "backend BMP escape path")
if "pair_codepoint" not in compact(function_section(backend_text, "decode_string_escapes")):
    raise SystemExit("backend escape decoder no longer combines valid surrogate pairs")
utf8_backend = compact(function_section(backend_text, "push_utf8"))
if "ifcodepoint<128:" not in utf8_backend or "ifcodepoint<2048:" not in utf8_backend or \
        "storage.push((224+(codepoint/4096)).u8())" not in utf8_backend or \
        "storage.push((240+(codepoint/262144)).u8())" not in utf8_backend:
    raise SystemExit("backend UTF-8 encoder must retain its 1/2/3/4-byte scalar branches")
count_backend = compact(function_section(backend_text, "decoded_literal_byte_count"))
if "count<-count+4" not in count_backend or "return-1ifnext_byte==117andhex_value>=56320andhex_value<=57343" not in count_backend:
    raise SystemExit("backend byte counter must count pairs once and refuse isolated surrogate units")

positive_shapes = {
    "literal_surrogate_pair_codepoint_is_unicode_scalar": """
        def literal_surrogate_pair_codepoint_is_unicode_scalar(high: i64, low: i64) -> i64:
            requires high >= 55296 and high <= 56319
            requires low >= 56320 and low <= 57343
            ensure result == 65536 + (high - 55296) * 1024 + (low - 56320)
            ensure result >= 65536
            ensure result <= 1114111
            ensure result < 55296 or result > 57343
            return 65536 + (high - 55296) * 1024 + (low - 56320)
    """,
    "literal_supplementary_scalar_has_four_byte_utf8_width": """
        def literal_supplementary_scalar_has_four_byte_utf8_width(codepoint: i64) -> i64:
            requires codepoint >= 65536 and codepoint <= 1114111
            ensure result == 4
            return 1 if codepoint < 128 else (2 if codepoint < 2048 else (3 if codepoint < 65536 else 4))
    """,
    "literal_high_surrogate_is_not_a_unicode_scalar": """
        def literal_high_surrogate_is_not_a_unicode_scalar(codepoint: i64) -> bool:
            requires codepoint >= 55296 and codepoint <= 56319
            ensure result == false
            return codepoint < 55296 or codepoint > 57343
    """,
    "literal_low_surrogate_is_not_a_unicode_scalar": """
        def literal_low_surrogate_is_not_a_unicode_scalar(codepoint: i64) -> bool:
            requires codepoint >= 56320 and codepoint <= 57343
            ensure result == false
            return codepoint < 55296 or codepoint > 57343
    """,
    "literal_unpaired_surrogate_contributes_no_decoded_bytes": """
        def literal_unpaired_surrogate_contributes_no_decoded_bytes(codepoint: i64, paired: bool) -> i64:
            requires codepoint >= 55296 and codepoint <= 57343
            requires not paired
            ensure result == 0
            return 0
    """,
    "literal_two_surrogate_code_units_are_not_the_pair_encoding_width": """
        def literal_two_surrogate_code_units_are_not_the_pair_encoding_width(high: i64, low: i64) -> bool:
            requires high >= 55296 and high <= 56319
            requires low >= 56320 and low <= 57343
            ensure result == true
            return 3 + 3 != 4
    """,
    "literal_surrogate_pair_contributes_four_decoded_bytes": """
        def literal_surrogate_pair_contributes_four_decoded_bytes(high: i64, low: i64) -> i64:
            requires high >= 55296 and high <= 56319
            requires low >= 56320 and low <= 57343
            ensure result == 4
            return 4
    """,
}
for name, shape in positive_shapes.items():
    require_shape(POSITIVE, name, shape)

negative_shapes = {
    "false_isolated_high_surrogate_is_scalar": """
        def false_isolated_high_surrogate_is_scalar(codepoint: i64) -> bool:
            requires codepoint == 55296
            ensure result == true
            return codepoint < 55296 or codepoint > 57343
    """,
    "false_isolated_low_surrogate_is_scalar": """
        def false_isolated_low_surrogate_is_scalar(codepoint: i64) -> bool:
            requires codepoint == 56320
            ensure result == true
            return codepoint < 55296 or codepoint > 57343
    """,
    "false_valid_surrogate_pair_uses_three_bytes": """
        def false_valid_surrogate_pair_uses_three_bytes(claimed_width: i64) -> bool:
            requires claimed_width == 4
            ensure result == true
            return claimed_width == 3
    """,
}
for name, shape in negative_shapes.items():
    require_shape(NEGATIVE, name, shape)
if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("surrogate proof declaration inventory changed")
if not NEGATIVE.read_text().startswith('include "./backend_literal_surrogate_semantics.elisa"'):
    raise SystemExit("surrogate false claims must include the positive scalar theorems")

if ARGS.source_only:
    print(json.dumps({
        "source_bound": True,
        "positive_declarations": len(POSITIVE_NAMES),
        "negative_controls": len(NEGATIVE_NAMES),
        "production_compatibility": "valid-surrogate-pairs-combined",
    }, sort_keys=True))
    raise SystemExit(0)

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("surrogate semantics audit requires a strict proof build")
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
    BACKEND,
    FIXTURE,
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
assert positive["summary"]["declarations"] == 7
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 17
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "surrogate specification report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == 10
assert negative["summary"]["obligations"] == 23 and negative["summary"]["proven"] == 20
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product, "proof product provenance changed during replay"
print(json.dumps({
    "audit_complete": True,
    "specification_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "production_compatibility": "valid-surrogate-pairs-combined",
    "pair_width_counted_once": True,
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
