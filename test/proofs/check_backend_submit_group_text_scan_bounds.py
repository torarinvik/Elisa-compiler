"""Source-bind proofs for the submit task-group raw-text byte scanner."""
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
POSITIVE = HERE / "backend_submit_group_text_scan_bounds.elisa"
NEGATIVE = HERE / "backend_submit_group_text_scan_bounds_rejected.elisa"
POSITIVE_NAMES = {
    "submit_ascii_classifier_read_is_bounded",
    "submit_raw_name_span_is_bounded",
    "submit_previous_byte_guard_is_bounded",
    "submit_end_boundary_fallback_is_bounded",
}
NEGATIVE_NAMES = {
    "false_claim_ascii_classifier_reads_one_past_view",
    "false_claim_raw_name_span_can_cross_text_end",
    "false_claim_previous_byte_exists_at_zero",
    "false_claim_end_byte_is_readable_at_view_length",
}
FUNCTION_SHA256 = {
    "submit_group_ascii_identifier_char": "4e29180e64d46f65a839cb52459669fe980a656f56809331a5d55a9f6c8c9135",
    "submit_group_raw_text_mentions_name": "a98993d8f105e5801af8b38d7f0ad774d18c7fa3854d347dfa89a0506fbd0cea",
}


def uncomment(line: str) -> str:
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
    return " ".join(uncomment(code).split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def normalized_lines(source: str) -> tuple[tuple[int, str], ...]:
    lines = []
    for raw in source.splitlines():
        code = uncomment(raw).expandtabs(4)
        if code.strip():
            lines.append((len(code) - len(code.lstrip()), normalize(code.lstrip())))
    if not lines:
        return ()
    base_indent = min(indent for indent, _ in lines)
    return tuple((indent - base_indent, code) for indent, code in lines)


def function_fingerprint(source: str, name: str) -> str:
    rows = normalized_lines(function_section(source, name))
    canonical = "\n".join(f"{indent}:{code}" for indent, code in rows)
    return hashlib.sha256(canonical.encode()).hexdigest()


def exact_steps(source: str, name: str, steps: tuple[tuple[int, str], ...], label: str) -> None:
    lines = normalized_lines(function_section(source, name))
    cursor = 0
    for indent, code in steps:
        expected = (indent, normalize(code))
        try:
            cursor = lines.index(expected, cursor) + 1
        except ValueError:
            raise SystemExit(f"{label}: missing or reordered source line: {code}") from None


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def require_model(name: str, signature: str, contracts: tuple[str, ...]) -> None:
    lines = normalized_lines(function_section(POSITIVE.read_text(), name))
    expected = [(0, normalize(signature))]
    expected.extend((4, normalize(line)) for line in contracts)
    cursor = 0
    for item in expected:
        try:
            cursor = lines.index(item, cursor) + 1
        except ValueError:
            raise SystemExit(f"proof model {name} changed its contract: {item[1]}") from None


def require_negative(name: str, contracts: tuple[str, ...]) -> None:
    lines = normalized_lines(function_section(NEGATIVE.read_text(), name))
    expected = [(0, normalize(contracts[0]))]
    expected.extend((4, normalize(line)) for line in contracts[1:])
    cursor = 0
    for item in expected:
        try:
            cursor = lines.index(item, cursor) + 1
        except ValueError:
            raise SystemExit(f"negative control {name} changed: {item[1]}") from None


if not __debug__:
    raise SystemExit("run without Python -O")

source_text = SOURCE.read_text()
for function_name, expected_sha256 in FUNCTION_SHA256.items():
    actual_sha256 = function_fingerprint(source_text, function_name)
    if actual_sha256 != expected_sha256:
        raise SystemExit(
            f"{function_name} changed since its bounds proof was source-bound; re-review the full function"
        )

# Mutation controls exercise the full-body source pin against the reviewer's two escape cases:
# an indexed read moved before its guard, and a return that skips all scanning.
classifier = function_section(source_text, "submit_group_ascii_identifier_char")
classifier_mutation = classifier.replace(
    "            return false if offset >= sview_len(text)\n",
    "            character: u8 = sview_at(text, offset)\n            return false if offset >= sview_len(text)\n",
    1,
)
if classifier_mutation == classifier or function_fingerprint(classifier_mutation, "submit_group_ascii_identifier_char") == FUNCTION_SHA256["submit_group_ascii_identifier_char"]:
    raise SystemExit("classifier mutation control did not detect a pre-guard byte read")
scanner = function_section(source_text, "submit_group_raw_text_mentions_name")
scanner_mutations = (
    scanner.replace(
        "            for offset in 0..<text_length:\n                return true if sview_at(text, offset) >= 128\n",
        "            sview_at(text, text_length)\n            for offset in 0..<text_length:\n                return true if sview_at(text, offset) >= 128\n",
        1,
    ),
    scanner.replace(
        "            name_length: usize = sview_len(name)\n",
        "            name_length: usize = sview_len(name)\n            return false\n",
        1,
    ),
)
if any(mutated == scanner or function_fingerprint(mutated, "submit_group_raw_text_mentions_name") == FUNCTION_SHA256["submit_group_raw_text_mentions_name"] for mutated in scanner_mutations):
    raise SystemExit("scanner mutation control failed to detect an early out-of-bounds read or skipped scan")
exact_steps(source_text, "submit_group_ascii_identifier_char", (
    (4, "return false if offset >= sview_len(text)"),
    (4, "character: u8 = sview_at(text, offset)"),
    (4, "return character == 95 or character == 36 or character in 48..57 or character in 65..90 or character in 97..122"),
), "submit ASCII identifier-byte classifier")
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
    (12, "end: usize = offset + name_length"),
    (12, "if sview_matches_prefix(text, name, offset.i64(), end.i64()):"),
    (16, "starts_token: mutable bool = offset == 0"),
    (16, "starts_token <- not submit_group_ascii_identifier_char(text, offset - 1.usize()) if offset > 0"),
    (16, "ends_token: bool = end == text_length or not submit_group_ascii_identifier_char(text, end)"),
    (16, "return true if starts_token and ends_token"),
    (4, "return false"),
), "raw-text name scanner")

require_model(
    "submit_ascii_classifier_read_is_bounded",
    "def submit_ascii_classifier_read_is_bounded(text_length: usize, offset: usize) -> bool:",
    ("requires offset < text_length", "ensure result == true", "return offset < text_length"),
)
require_model(
    "submit_raw_name_span_is_bounded",
    "def submit_raw_name_span_is_bounded(text_length: usize, name_length: usize, offset: usize) -> bool:",
    (
        "requires name_length > 0 and offset < text_length",
        "requires name_length <= text_length - offset",
        "ensure result == true",
        "return offset < offset + name_length and offset + name_length <= text_length",
    ),
)
require_model(
    "submit_previous_byte_guard_is_bounded",
    "def submit_previous_byte_guard_is_bounded(text_length: usize, offset: usize) -> bool:",
    ("requires offset > 0 and offset < text_length", "ensure result == true", "return offset - 1 < text_length"),
)
require_model(
    "submit_end_boundary_fallback_is_bounded",
    "def submit_end_boundary_fallback_is_bounded(text_length: usize, end: usize) -> bool:",
    ("requires end <= text_length", "ensure result == true", "return end == text_length or end < text_length"),
)

source_lines = {code for _, code in normalized_lines(source_text)}
source_bindings = {
    "offset": (
        "for offset in 0..<text_length:",
        "for offset in 0..<name_length:",
        "return false if offset >= sview_len(text)",
    ),
    "span": (
        "if name_length <= text_length - offset:",
        "end: usize = offset + name_length",
        "if sview_matches_prefix(text, name, offset.i64(), end.i64()):",
    ),
    "previous": ("starts_token <- not submit_group_ascii_identifier_char(text, offset - 1.usize()) if offset > 0",),
    "next": ("ends_token: bool = end == text_length or not submit_group_ascii_identifier_char(text, end)",),
}
for source_role, steps in source_bindings.items():
    for step in steps:
        if normalize(step) not in source_lines:
            raise SystemExit(f"scanner bound model {source_role} is not tied to source line: {step}")

require_negative("false_claim_ascii_classifier_reads_one_past_view", (
    "def false_claim_ascii_classifier_reads_one_past_view(text_length: usize, offset: usize) -> bool:",
    "requires offset == text_length",
    "ensure result == true",
    "return offset < text_length",
))
require_negative("false_claim_raw_name_span_can_cross_text_end", (
    "def false_claim_raw_name_span_can_cross_text_end(text_length: usize, name_length: usize, offset: usize) -> bool:",
    "requires offset < text_length and name_length > text_length - offset",
    "ensure result == true",
    "return offset + name_length <= text_length",
))
require_negative("false_claim_previous_byte_exists_at_zero", (
    "def false_claim_previous_byte_exists_at_zero(text_length: usize, offset: usize) -> bool:",
    "requires offset == 0 and text_length > 0",
    "ensure result == true",
    "return offset - 1 < text_length",
))
require_negative("false_claim_end_byte_is_readable_at_view_length", (
    "def false_claim_end_byte_is_readable_at_view_length(text_length: usize, end: usize) -> bool:",
    "requires end == text_length",
    "ensure result == true",
    "return end < text_length",
))

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("submit text-scan proof declaration inventory changed")
if not NEGATIVE.read_text().startswith('include "./backend_submit_group_text_scan_bounds.elisa"'):
    raise SystemExit("negative scanner controls must include the admitted models")

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("submit text-scan proof requires a strict proof build")
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
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    report = json.loads(result.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return result.returncode, report


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
    "scope": "ASCII task-group scanner byte indices, candidate spans, and token-boundary probes",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
