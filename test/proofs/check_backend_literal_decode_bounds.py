"""Source-bind replayable bounds proofs for literal escape decoding."""
from __future__ import annotations

import hashlib
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure

argument_parser = argparse.ArgumentParser()
argument_parser.add_argument("--source-only", action="store_true",
                             help="check source/proof bounds bindings without running Elisa-Proof")
ARGS = argument_parser.parse_args()

ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=not ARGS.source_only)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
SOURCE = ROOT / "src/backend/codegen_literals_decode.elisa"
POSITIVE = HERE / "backend_literal_decode_bounds.elisa"
NEGATIVE = HERE / "backend_literal_decode_bounds_rejected.elisa"
POSITIVE_NAMES = {
    "literal_decode_escape_next_byte_is_bounded",
    "literal_decode_guarded_next_offset_is_bounded",
    "literal_decode_escape_pair_advance_is_bounded",
    "literal_decode_hex_start_is_bounded",
    "literal_decode_single_byte_advance_is_bounded",
    "literal_decode_hex_digit_is_bounded",
    "literal_decode_hex_advance_is_bounded",
    "literal_pattern_quoted_last_byte_is_bounded",
    "literal_pattern_empty_unquoted_span_is_bounded",
    "literal_pattern_unquoted_span_is_bounded",
    "literal_pattern_quoted_inner_span_is_bounded",
}
NEGATIVE_NAMES = {
    "false_claim_trailing_escape_has_a_next_byte",
    "false_claim_one_past_hex_digit_is_inside_payload",
    "false_claim_empty_pattern_has_a_last_byte",
    "false_claim_quoted_inner_span_exceeds_the_text",
}
FUNCTION_SHA256 = {
    "hex_escape_value": "02657188556db09219fdf99c77c9d8c91e54383fedd21ec4f2c2be0fe3d6bf19",
    "utf16_surrogate_pair_codepoint": "efd83178d036eac52fcac8943a452d570f2d5cb32113db59ce0bbf944ceb079c",
    "decode_string_escapes": "e4dd1e99810e574d447f0fe9fb00d41af2c9846a90789c513de16491ee9fe49a",
    "decoded_literal_byte_count": "87bb5014f767f76c4f29333d19356897e91e31705875189b8b72aa37fd78ec41",
    "string_pattern_content_cstr": "e478082e1381286ea6a815ab6b94021ad55e9390800c2190e04b833b5bf78d7a",
}


def strip_comment(line: str) -> str:
    quote = None
    escaped = False
    for index, char in enumerate(line):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == "#":
            return line[:index]
    return line


def compact(code: str) -> str:
    return "".join("".join(strip_comment(line).split()) for line in code.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one declaration named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def normalized_rows(source: str) -> tuple[tuple[int, str], ...]:
    rows = []
    for raw in source.splitlines():
        line = strip_comment(raw).expandtabs(4)
        if line.strip():
            rows.append((len(line) - len(line.lstrip()), " ".join(line.lstrip().split())))
    if not rows:
        return ()
    base_indent = min(indent for indent, _ in rows)
    return tuple((indent - base_indent, code) for indent, code in rows)


def function_fingerprint(source: str, name: str) -> str:
    rows = normalized_rows(function_section(source, name))
    canonical = "\n".join(f"{indent}:{code}" for indent, code in rows)
    return hashlib.sha256(canonical.encode()).hexdigest()


def ordered_steps(source: str, name: str, steps: tuple[str, ...], label: str) -> None:
    body = compact(function_section(source, name))
    cursor = 0
    for step in steps:
        wanted = compact(step)
        position = body.find(wanted, cursor)
        if position < 0:
            raise SystemExit(f"{label}: missing or reordered source step: {step}")
        cursor = position + len(wanted)


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def require_model(name: str, signature: str, contracts: tuple[str, ...]) -> None:
    body = compact(function_section(POSITIVE.read_text(), name))
    cursor = 0
    for row in (signature, *contracts):
        wanted = compact(row)
        position = body.find(wanted, cursor)
        if position < 0:
            raise SystemExit(f"proof model {name} changed its source-bound contract: {row}")
        cursor = position + len(wanted)


def require_negative(name: str, contracts: tuple[str, ...]) -> None:
    body = compact(function_section(NEGATIVE.read_text(), name))
    cursor = 0
    for row in contracts:
        wanted = compact(row)
        position = body.find(wanted, cursor)
        if position < 0:
            raise SystemExit(f"negative control {name} changed: {row}")
        cursor = position + len(wanted)


if not __debug__:
    raise SystemExit("run without Python -O")

source_text = SOURCE.read_text()
for function_name, expected_sha256 in FUNCTION_SHA256.items():
    if function_fingerprint(source_text, function_name) != expected_sha256:
        raise SystemExit(f"{function_name} changed since its bounds proof was source-bound; re-review the full function")

# Mutation controls cover a read moved before its guard, a scan bypass, and a
# quote-final-byte read moved ahead of its length check.
decoder = function_section(source_text, "decode_string_escapes")
decoder_read_mutation = decoder.replace(
    "                if byte != 92 or remaining <= 1:\n",
    "                next_index: usize = index + 1.usize()\n                next_byte: u8 = text[next_index]\n                if byte != 92 or remaining <= 1:\n",
    1,
)
decoder_skip_mutation = decoder.replace(
    "            while index < length |index, storage, all_known|:\n",
    "            return\n            while index < length |index, storage, all_known|:\n",
    1,
)
pattern = function_section(source_text, "string_pattern_content_cstr")
pattern_guard_mutation = pattern.replace(
    "quoted: bool = length >= 2 and text[0] == 34 and text[length - 1] == 34",
    "quoted: bool = text[length - 1] == 34 and length >= 2 and text[0] == 34",
    1,
)
mutations = (
    (decoder_read_mutation, "decode_string_escapes"),
    (decoder_skip_mutation, "decode_string_escapes"),
    (pattern_guard_mutation, "string_pattern_content_cstr"),
)
if any(mutated == original or function_fingerprint(mutated, name) == FUNCTION_SHA256[name]
       for (mutated, name), original in zip(mutations, (decoder, decoder, pattern))):
    raise SystemExit("literal decoder mutation control failed to detect a guard-order or scan-bypass change")
ordered_steps(source_text, "decode_string_escapes", (
    "while index < length |index, storage, all_known|:",
    "byte: u8 = text[index]",
    "remaining: usize = length - index",
    "if byte != 92 or remaining <= 1:",
    "storage.push(byte)",
    "index <- index + 1.usize()",
    "continue",
    "next_index: usize = index + 1.usize()",
    "next_byte: u8 = text[next_index]",
    "hex_digits: usize = 2.usize() if next_byte == 120 else 4.usize()",
    "hex_start: usize = next_index + 1.usize()",
    "hex_available: usize = length - hex_start",
    "hex_ok: mutable bool = hex_digits <= hex_available",
    "hex_value <- hex_escape_value(text, hex_start, hex_digits)",
    "if next_byte == 117 and hex_value >= 55296 and hex_value <= 56319:",
    "low_escape_start: usize = hex_start + hex_digits",
    "pair_codepoint: i64 = utf16_surrogate_pair_codepoint(text, low_escape_start, hex_value)",
    "if pair_codepoint >= 0:",
    "push_utf8(storage, pair_codepoint)",
    "index <- low_escape_start + 6.usize()",
    "all_known <- false",
    "for raw_index in index..<low_escape_start |storage, text|:",
    "if next_byte == 117 and hex_value >= 56320 and hex_value <= 57343:",
    "all_known <- false",
    "index <- hex_start + hex_digits",
    "storage.push(decoded)",
    "index <- next_index + 1.usize()",
), "escape decoder")
ordered_steps(source_text, "hex_escape_value", (
    "requires start <= text.len and digits <= text.len - start",
    "while index < digits |value, index, text, start, digits|:",
    "invariant index <= digits",
    "digit: i64 = hex_digit_value(text[start + index])",
    "return -1 if digit < 0",
    "value <- value * 16 + digit",
    "index <- index + 1.usize()",
), "bounded hexadecimal parser")
ordered_steps(source_text, "utf16_surrogate_pair_codepoint", (
    "requires low_escape_start <= text.len",
    "remaining: usize = text.len - low_escape_start",
    "return -1 if remaining < 6",
    "return -1 if text[low_escape_start] != 92 or text[low_escape_start + 1.usize()] != 117",
    "low: i64 = hex_escape_value(text, low_escape_start + 2.usize(), 4.usize())",
    "return -1 if low < 56320 or low > 57343",
    "return 65536 + (high - 55296) * 1024 + (low - 56320)",
), "surrogate pair bounds")
ordered_steps(source_text, "decoded_literal_byte_count", (
    "while index < length |index, count, text, length|:",
    "byte: u8 = text[index]",
    "remaining: usize = length - index",
    "if byte != 92 or remaining <= 1:",
    "count return if stop_at_nul and byte == 0",
    "count <- count + 1",
    "index <- index + 1.usize()",
    "continue",
    "next_index: usize = index + 1.usize()",
    "next_byte: u8 = text[next_index]",
    "hex_digits: usize = 2.usize() if next_byte == 120 else 4.usize()",
    "hex_start: usize = next_index + 1.usize()",
    "hex_available: usize = length - hex_start",
    "-1 return if hex_digits > hex_available",
    "hex_value: i64 = hex_escape_value(text, hex_start, hex_digits)",
    "-1 return if hex_value < 0",
    "if next_byte == 117 and hex_value >= 55296 and hex_value <= 56319:",
    "low_escape_start: usize = hex_start + hex_digits",
    "pair_codepoint: i64 = utf16_surrogate_pair_codepoint(text, low_escape_start, hex_value)",
    "-1 return if pair_codepoint < 0",
    "count <- count + 4",
    "index <- low_escape_start + 6.usize()",
    "-1 return if next_byte == 117 and hex_value >= 56320 and hex_value <= 57343",
    "index <- hex_start + hex_digits",
    "index <- next_index + 1.usize()",
), "decoded literal byte counter")
ordered_steps(source_text, "string_pattern_content_cstr", (
    "length: usize = text.len",
    "quoted: bool = length >= 2 and text[0] == 34 and text[length - 1] == 34",
    "start: usize = 1 if quoted else 0",
    "stop: usize = length - 1 if quoted else length",
    "inner: sview = text[start:stop]",
), "string pattern span")

for function_name in ("decode_string_escapes", "decoded_literal_byte_count"):
    body = compact(function_section(source_text, function_name))
    for unsafe_shape in (
        "index+1.usize()>=length",
        "index+2.usize()+hex_digits<=length",
        "index+2.usize()+hex_digits>length",
        "index+2.usize()+hex_index",
    ):
        if unsafe_shape in body:
            raise SystemExit(f"{function_name} reintroduced unchecked offset arithmetic: {unsafe_shape}")

require_model("literal_decode_escape_next_byte_is_bounded",
    "def literal_decode_escape_next_byte_is_bounded(length: usize, index: usize) -> bool:",
    ("requires index < length", "requires length - index > 1", "ensure result == true", "return index + 1 < length"))
require_model("literal_decode_guarded_next_offset_is_bounded",
    "def literal_decode_guarded_next_offset_is_bounded(length: usize, index: usize, next_index: usize) -> bool:",
    ("requires index < length and length - index > 1",
     "requires next_index > index and next_index - index == 1", "ensure result == true",
     "return next_index < length"))
require_model("literal_decode_escape_pair_advance_is_bounded",
    "def literal_decode_escape_pair_advance_is_bounded(length: usize, next_index: usize) -> bool:",
    ("requires next_index < length", "ensure result == true", "return next_index + 1 <= length"))
require_model("literal_decode_hex_start_is_bounded",
    "def literal_decode_hex_start_is_bounded(length: usize, next_index: usize, hex_start: usize) -> bool:",
    ("requires next_index < length", "requires hex_start == next_index + 1", "ensure result == true",
     "return hex_start <= length"))
require_model("literal_decode_single_byte_advance_is_bounded",
    "def literal_decode_single_byte_advance_is_bounded(length: usize, index: usize) -> bool:",
    ("requires index < length", "ensure result == true", "return index + 1 <= length"))
require_model("literal_decode_hex_digit_is_bounded",
    "def literal_decode_hex_digit_is_bounded(length: usize, start: usize, digits: usize, offset: usize) -> bool:",
    ("requires start <= length", "requires digits <= length - start", "requires offset < digits",
     "ensure result == true", "return start + offset < length"))
require_model("literal_decode_hex_advance_is_bounded",
    "def literal_decode_hex_advance_is_bounded(length: usize, start: usize, digits: usize) -> bool:",
    ("requires start <= length", "requires digits <= length - start", "ensure result == true",
     "return start + digits <= length"))
require_model("literal_pattern_quoted_last_byte_is_bounded",
    "def literal_pattern_quoted_last_byte_is_bounded(length: usize, last: usize) -> bool:",
    ("requires length >= 2", "requires last == length - 1", "ensure result == true", "return last < length"))
require_model("literal_pattern_empty_unquoted_span_is_bounded",
    "def literal_pattern_empty_unquoted_span_is_bounded(length: usize, start: usize, stop: usize) -> bool:",
    ("requires length == 0", "requires start == 0 and stop == length", "ensure result == true",
     "return start <= stop and stop <= length"))
require_model("literal_pattern_unquoted_span_is_bounded",
    "def literal_pattern_unquoted_span_is_bounded(length: usize, start: usize, stop: usize) -> bool:",
    ("requires start == 0 and stop == length", "ensure result == true",
     "return start <= stop and stop <= length"))
require_model("literal_pattern_quoted_inner_span_is_bounded",
    "def literal_pattern_quoted_inner_span_is_bounded(length: usize, start: usize, stop: usize) -> bool:",
    ("requires length >= 2", "requires start == 1 and stop == length - 1", "ensure result == true",
     "return start <= stop and stop <= length"))
require_negative("false_claim_trailing_escape_has_a_next_byte", (
    "def false_claim_trailing_escape_has_a_next_byte(length: usize, index: usize) -> bool:",
    "requires index < length", "requires length - index <= 1", "ensure result == true", "return index + 1 < length"))
require_negative("false_claim_one_past_hex_digit_is_inside_payload", (
    "def false_claim_one_past_hex_digit_is_inside_payload(length: usize, start: usize, digits: usize, offset: usize) -> bool:",
    "requires start <= length", "requires digits <= length - start", "requires offset == digits",
    "ensure result == true", "return start + offset < length"))
require_negative("false_claim_empty_pattern_has_a_last_byte", (
    "def false_claim_empty_pattern_has_a_last_byte(length: usize, last: usize) -> bool:",
    "requires length == 0", "requires last == 0", "ensure result == true", "return last < length"))
require_negative("false_claim_quoted_inner_span_exceeds_the_text", (
    "def false_claim_quoted_inner_span_exceeds_the_text(length: usize, start: usize, stop: usize) -> bool:",
    "requires length >= 2", "requires start == 1 and stop == length - 1", "ensure result == true",
    "return stop > length"))

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("literal decoder proof declaration inventory changed")
if not NEGATIVE.read_text().startswith('include "./backend_literal_decode_bounds.elisa"'):
    raise SystemExit("literal decoder false-claim controls must include the positive proofs")

if ARGS.source_only:
    print(json.dumps({
        "source_bound": True,
        "positive_theorems": len(POSITIVE_NAMES),
        "false_controls": len(NEGATIVE_NAMES),
    }, sort_keys=True))
    raise SystemExit(0)

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("literal decoder bounds proof requires a strict proof build")
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
                             text=True, timeout=90)
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
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_NAMES) + len(NEGATIVE_NAMES)
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "escape continuations, hex payload offsets, cursor advancement, and string-pattern slices",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
