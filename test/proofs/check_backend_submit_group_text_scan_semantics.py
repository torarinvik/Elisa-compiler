"""Source-bind semantic proofs for submit scanner fail-closed and token rules."""
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
SOURCE = ROOT / "src/backend/codegen_submit_store_capture.elisa"
POSITIVE = HERE / "backend_submit_group_text_scan_semantics.elisa"
NEGATIVE = HERE / "backend_submit_group_text_scan_semantics_rejected.elisa"
POSITIVE_NAMES = {
    "non_ascii_text_fails_closed",
    "non_ascii_name_fails_closed",
    "empty_name_short_circuits_non_ascii",
    "exact_name_at_both_text_edges_is_accepted",
    "delimited_name_inside_text_is_accepted",
    "identifier_byte_before_name_rejects_prefix_only_match",
    "identifier_byte_after_name_rejects_prefix_only_match",
    "punctuation_bytes_are_token_boundaries",
    "every_ascii_digit_is_an_identifier_byte",
    "every_ascii_uppercase_letter_is_an_identifier_byte",
    "every_ascii_lowercase_letter_is_an_identifier_byte",
    "underscore_and_dollar_are_identifier_bytes",
    "non_ascii_bytes_are_not_identifier_bytes",
}
NEGATIVE_NAMES = {
    "false_claim_ascii_text_is_reported_as_non_ascii",
    "false_claim_identifier_before_name_is_a_boundary",
    "false_claim_identifier_after_name_is_a_boundary",
    "false_claim_nonmatching_prefix_is_a_token",
    "false_claim_non_ascii_byte_is_an_identifier_byte",
    "false_claim_hyphen_is_an_identifier_byte",
    "false_claim_delete_is_an_identifier_byte",
}
FUNCTION_SHA256 = {
    "submit_group_ascii_identifier_char": "4e29180e64d46f65a839cb52459669fe980a656f56809331a5d55a9f6c8c9135",
    "submit_group_raw_text_mentions_name": "a98993d8f105e5801af8b38d7f0ad774d18c7fa3854d347dfa89a0506fbd0cea",
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


def normalize(code: str) -> str:
    return " ".join(strip_comment(code).split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost )?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one declaration named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost )?def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def normalized_lines(source: str) -> tuple[tuple[int, str], ...]:
    rows = []
    for raw in source.splitlines():
        line = strip_comment(raw).expandtabs(4)
        if line.strip():
            rows.append((len(line) - len(line.lstrip()), normalize(line.lstrip())))
    if not rows:
        return ()
    base_indent = min(indent for indent, _ in rows)
    return tuple((indent - base_indent, code) for indent, code in rows)


def function_fingerprint(source: str, name: str) -> str:
    rows = normalized_lines(function_section(source, name))
    canonical = "\n".join(f"{indent}:{code}" for indent, code in rows)
    return hashlib.sha256(canonical.encode()).hexdigest()


def exact_steps(source: str, name: str, steps: tuple[tuple[int, str], ...], label: str) -> None:
    rows = normalized_lines(function_section(source, name))
    cursor = 0
    for indent, code in steps:
        expected = (indent, normalize(code))
        try:
            cursor = rows.index(expected, cursor) + 1
        except ValueError:
            raise SystemExit(f"{label}: missing or reordered source line: {code}") from None


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^ghost def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def require_model(name: str, signature: str, contracts: tuple[str, ...]) -> None:
    rows = normalized_lines(function_section(POSITIVE.read_text(), name))
    expected = [(0, normalize(signature))]
    expected.extend((4, normalize(row)) for row in contracts)
    cursor = 0
    for item in expected:
        try:
            cursor = rows.index(item, cursor) + 1
        except ValueError:
            raise SystemExit(f"proof model {name} changed its source-bound contract: {item[1]}") from None


def require_negative(name: str, contracts: tuple[str, ...]) -> None:
    rows = normalized_lines(function_section(NEGATIVE.read_text(), name))
    expected = [(0, normalize(contracts[0]))]
    expected.extend((4, normalize(row)) for row in contracts[1:])
    cursor = 0
    for item in expected:
        try:
            cursor = rows.index(item, cursor) + 1
        except ValueError:
            raise SystemExit(f"negative control {name} changed: {item[1]}") from None


if not __debug__:
    raise SystemExit("run without Python -O")

source_text = SOURCE.read_text()
for name, expected in FUNCTION_SHA256.items():
    if function_fingerprint(source_text, name) != expected:
        raise SystemExit(f"{name} changed since semantic proofs were source-bound; re-review the whole function")
exact_steps(source_text, "submit_group_ascii_identifier_char", (
    (4, "return false if offset >= sview_len(text)"),
    (4, "character: u8 = sview_at(text, offset)"),
    (4, "return character == 95 or character == 36 or character in 48..57 or character in 65..90 or character in 97..122"),
), "ASCII identifier classifier")
exact_steps(source_text, "submit_group_raw_text_mentions_name", (
    (4, 'return false if name == ""'),
    (4, "text_length: usize = sview_len(text)"),
    (4, "name_length: usize = sview_len(name)"),
    (4, "for offset in 0..<text_length:"),
    (8, "return true if sview_at(text, offset) >= 128"),
    (4, "for offset in 0..<name_length:"),
    (8, "return true if sview_at(name, offset) >= 128"),
    (4, "for offset in 0..<text_length:"),
    (8, "if name_length <= text_length - offset:"),
    (12, "if sview_matches_prefix(text, name, offset.i64(), end.i64()):"),
    (16, "starts_token: mutable bool = offset == 0"),
    (16, "starts_token <- not submit_group_ascii_identifier_char(text, offset - 1.usize()) if offset > 0"),
    (16, "ends_token: bool = end == text_length or not submit_group_ascii_identifier_char(text, end)"),
    (16, "return true if starts_token and ends_token"),
    (4, "return false"),
), "raw scanner token and non-ASCII rules")

require_model("non_ascii_text_fails_closed",
    "ghost def non_ascii_text_fails_closed(name_length: usize, text_has_non_ascii: bool) -> bool:",
    ("requires name_length > 0 and text_has_non_ascii", "ensure result == true",
     "return name_length > 0 and text_has_non_ascii"))
require_model("non_ascii_name_fails_closed",
    "ghost def non_ascii_name_fails_closed(name_length: usize, name_has_non_ascii: bool) -> bool:",
    ("requires name_length > 0 and name_has_non_ascii", "ensure result == true",
     "return name_length > 0 and name_has_non_ascii"))
require_model("empty_name_short_circuits_non_ascii",
    "ghost def empty_name_short_circuits_non_ascii(name_has_non_ascii: bool) -> bool:",
    ("ensure result == false", "return false"))
require_model("exact_name_at_both_text_edges_is_accepted",
    "ghost def exact_name_at_both_text_edges_is_accepted(prefix_matches: bool, at_start: bool, at_end: bool, previous_is_identifier: bool, next_is_identifier: bool) -> bool:",
    ("requires prefix_matches and at_start and at_end", "ensure result == true",
     "return prefix_matches and (at_start or not previous_is_identifier) and (at_end or not next_is_identifier)"))
require_model("delimited_name_inside_text_is_accepted",
    "ghost def delimited_name_inside_text_is_accepted(prefix_matches: bool, text_length: usize, offset: usize, end: usize, previous_is_identifier: bool, next_is_identifier: bool) -> bool:",
    ("requires prefix_matches and offset > 0 and end < text_length", "requires not previous_is_identifier and not next_is_identifier",
     "ensure result == true", "return prefix_matches and (offset == 0 or not previous_is_identifier) and (end == text_length or not next_is_identifier)"))
require_model("identifier_byte_before_name_rejects_prefix_only_match",
    "ghost def identifier_byte_before_name_rejects_prefix_only_match(prefix_matches: bool, text_length: usize, offset: usize, previous_is_identifier: bool) -> bool:",
    ("requires prefix_matches and offset > 0 and offset < text_length", "requires previous_is_identifier",
     "ensure result == false", "return prefix_matches and (offset == 0 or not previous_is_identifier)"))
require_model("identifier_byte_after_name_rejects_prefix_only_match",
    "ghost def identifier_byte_after_name_rejects_prefix_only_match(prefix_matches: bool, at_end: bool, next_is_identifier: bool) -> bool:",
    ("requires prefix_matches and not at_end and next_is_identifier", "ensure result == false",
     "return prefix_matches and (at_end or not next_is_identifier)"))
require_model("punctuation_bytes_are_token_boundaries",
    "ghost def punctuation_bytes_are_token_boundaries(prefix_matches: bool, text_length: usize, offset: usize, end: usize, previous_is_identifier: bool, next_is_identifier: bool) -> bool:",
    ("requires prefix_matches and offset > 0 and offset < end and end < text_length",
     "requires not previous_is_identifier and not next_is_identifier", "ensure result == true",
     "return prefix_matches and (offset == 0 or not previous_is_identifier) and (end == text_length or not next_is_identifier)"))
for name, signature, range_contract in (
    ("every_ascii_digit_is_an_identifier_byte", "ghost def every_ascii_digit_is_an_identifier_byte(byte: u8) -> bool:", "byte >= 48 and byte <= 57"),
    ("every_ascii_uppercase_letter_is_an_identifier_byte", "ghost def every_ascii_uppercase_letter_is_an_identifier_byte(byte: u8) -> bool:", "byte >= 65 and byte <= 90"),
    ("every_ascii_lowercase_letter_is_an_identifier_byte", "ghost def every_ascii_lowercase_letter_is_an_identifier_byte(byte: u8) -> bool:", "byte >= 97 and byte <= 122"),
):
    require_model(name, signature, (
        f"requires {range_contract}", "ensure result == true",
        "return byte == 95 or byte == 36 or (byte >= 48 and byte <= 57) or (byte >= 65 and byte <= 90) or (byte >= 97 and byte <= 122)",
    ))
require_model("underscore_and_dollar_are_identifier_bytes",
    "ghost def underscore_and_dollar_are_identifier_bytes(byte: u8) -> bool:",
    ("requires byte == 95 or byte == 36", "ensure result == true",
     "return byte == 95 or byte == 36 or (byte >= 48 and byte <= 57) or (byte >= 65 and byte <= 90) or (byte >= 97 and byte <= 122)"))
require_model("non_ascii_bytes_are_not_identifier_bytes",
    "ghost def non_ascii_bytes_are_not_identifier_bytes(byte: u8) -> bool:",
    ("requires byte >= 128", "ensure result == false",
     "return byte == 95 or byte == 36 or (byte >= 48 and byte <= 57) or (byte >= 65 and byte <= 90) or (byte >= 97 and byte <= 122)"))

require_negative("false_claim_ascii_text_is_reported_as_non_ascii", (
    "ghost def false_claim_ascii_text_is_reported_as_non_ascii(name_length: usize, text_has_non_ascii: bool) -> bool:",
    "requires name_length > 0 and not text_has_non_ascii", "ensure result == true",
    "return name_length > 0 and text_has_non_ascii"))
require_negative("false_claim_identifier_before_name_is_a_boundary", (
    "ghost def false_claim_identifier_before_name_is_a_boundary(prefix_matches: bool, at_start: bool, previous_is_identifier: bool) -> bool:",
    "requires prefix_matches and not at_start and previous_is_identifier", "ensure result == true",
    "return prefix_matches and (at_start or not previous_is_identifier)"))
require_negative("false_claim_identifier_after_name_is_a_boundary", (
    "ghost def false_claim_identifier_after_name_is_a_boundary(prefix_matches: bool, at_end: bool, next_is_identifier: bool) -> bool:",
    "requires prefix_matches and not at_end and next_is_identifier", "ensure result == true",
    "return prefix_matches and (at_end or not next_is_identifier)"))
require_negative("false_claim_nonmatching_prefix_is_a_token", (
    "ghost def false_claim_nonmatching_prefix_is_a_token(prefix_matches: bool, at_start: bool, at_end: bool, previous_is_identifier: bool, next_is_identifier: bool) -> bool:",
    "requires not prefix_matches and at_start and at_end", "ensure result == true",
    "return prefix_matches and (at_start or not previous_is_identifier) and (at_end or not next_is_identifier)"))
require_negative("false_claim_non_ascii_byte_is_an_identifier_byte", (
    "ghost def false_claim_non_ascii_byte_is_an_identifier_byte(byte: u8) -> bool:",
    "requires byte >= 128", "ensure result == true",
    "return byte == 95 or byte == 36 or (byte >= 48 and byte <= 57) or (byte >= 65 and byte <= 90) or (byte >= 97 and byte <= 122)"))
require_negative("false_claim_hyphen_is_an_identifier_byte", (
    "ghost def false_claim_hyphen_is_an_identifier_byte() -> bool:",
    "ensure result == true",
    "return 45 == 95 or 45 == 36 or (45 >= 48 and 45 <= 57) or (45 >= 65 and 45 <= 90) or (45 >= 97 and 45 <= 122)"))
require_negative("false_claim_delete_is_an_identifier_byte", (
    "ghost def false_claim_delete_is_an_identifier_byte(byte: u8) -> bool:",
    "requires byte == 127", "ensure result == true",
    "return byte == 95 or byte == 36 or (byte >= 48 and byte <= 57) or (byte >= 65 and byte <= 90) or (byte >= 97 and byte <= 122)"))

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("submit semantic proof declaration inventory changed")
if not NEGATIVE.read_text().startswith('include "./backend_submit_group_text_scan_semantics.elisa"'):
    raise SystemExit("negative submit semantic controls must include the positive models")

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("submit semantic proof requires a strict proof build")
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
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_NAMES) + len(NEGATIVE_NAMES)
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "conservative non-ASCII handling and exact ASCII identifier token boundaries",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
