"""Admit source-linked proofs for ABI lint's ASCII and assembly token boundaries."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
PROJECT = ROOT / "src/driver/project.elisa"
ABI = ROOT / "src/driver/abi_lint.elisa"
ABI_SCAN = ROOT / "src/driver/abi_lint_scan.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
POSITIVE = HERE / "abi_lint_byte_classification.elisa"
NEGATIVE = HERE / "abi_lint_byte_classification_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return " ".join(text.split())


abi_text = ABI.read_text()
scan_text = ABI_SCAN.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()


def function_body(source: str, name: str, signature: str) -> str:
    if signature not in source:
        raise SystemExit(f"production ABI helper is missing: {name}")
    return source.split(signature, 1)[1].split("\n    def ", 1)[0]


def require_in_order(source: str, name: str, signature: str, fragments: tuple[str, ...]) -> None:
    body = compact(function_body(source, name, signature))
    positions = [body.find(compact(fragment)) for fragment in fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{name} lost a required guard-before-indexing order: {fragments}")


word_signature = "def abi_is_word_byte(value: u8) -> bool:"
lower_signature = "def abi_lower(value: u8) -> u8:"
word_body = function_body(abi_text, "abi_is_word_byte", word_signature)
lower_body = function_body(abi_text, "abi_lower", lower_signature)
word_spec = "((value >= ProjectSystemAbiAscii::ASCII_DIGIT_ZERO and value <= ProjectSystemAbiAscii::ASCII_DIGIT_NINE) or (value >= ProjectSystemAbiAscii::ASCII_UPPER_A and value <= ProjectSystemAbiAscii::ASCII_UPPER_Z) or (value >= ProjectSystemAbiAscii::ASCII_LOWER_A and value <= ProjectSystemAbiAscii::ASCII_LOWER_Z) or value == ProjectSystemAbiAscii::ASCII_UNDERSCORE)"
lower_spec = "(value + ProjectSystemAbiAscii::ASCII_CASE_FOLD_DELTA if value >= ProjectSystemAbiAscii::ASCII_UPPER_A and value <= ProjectSystemAbiAscii::ASCII_UPPER_Z else value)"
expected_constants = {
    "ASCII_DIGIT_ZERO": 48,
    "ASCII_DIGIT_NINE": 57,
    "ASCII_UPPER_A": 65,
    "ASCII_UPPER_Z": 90,
    "ASCII_LOWER_A": 97,
    "ASCII_LOWER_Z": 122,
    "ASCII_UNDERSCORE": 95,
    "ASCII_CASE_FOLD_DELTA": 32,
}
for name, value in expected_constants.items():
    if not re.search(rf"\b{name}: u8 = {value}\b", abi_text):
        raise SystemExit(f"ABI ASCII constant is missing or changed: {name} = {value}")
if compact(f"ensure result == {word_spec}") not in compact(word_body):
    raise SystemExit("ABI word-byte helper lacks its exact ASCII membership contract")
if compact(f"return {word_spec}") not in compact(word_body):
    raise SystemExit("ABI word-byte implementation differs from its ASCII contract")
if compact(f"ensure result == {lower_spec}") not in compact(lower_body):
    raise SystemExit("ABI case-fold helper lacks its exact ASCII mapping contract")
if compact(f"return {lower_spec}") not in compact(lower_body):
    raise SystemExit("ABI case-fold implementation differs from its ASCII contract")
require_in_order(abi_text, "abi_span_is", "def abi_span_is(text: darray[u8]&, start: usize, needle: sview) -> bool:", (
    "false return if start > text.count",
    "false return if sview_len(needle) > text.count - start",
    "for index in 0..<sview_len(needle) |text, needle, start|",
    "text[start + index]",
))
require_in_order(abi_text, "abi_span_is_ci", "def abi_span_is_ci(text: darray[u8]&, start: usize, needle: sview) -> bool:", (
    "false return if start > text.count",
    "false return if sview_len(needle) > text.count - start",
    "for index in 0..<sview_len(needle) |text, needle, start|",
    "text[start + index]",
))
require_in_order(abi_text, "abi_word_in_span", "def abi_word_in_span(text: darray[u8]&, span_start: usize, span_stop: usize, needle: sview) -> bool:", (
    "stop: usize = span_stop if span_stop <= text.count else text.count",
    "false return if span_start > stop",
    "for start in span_start..<stop |text, needle, length, stop, span_start|",
    "continue if length > stop - start",
    "continue if not abi_span_is(text, start, needle)",
    "before_ok: bool = start == span_start or not abi_is_word_byte(text[start - 1.usize()])",
    "after_ok: bool = length == stop - start or not abi_is_word_byte(text[start + length])",
))
require_in_order(abi_text, "abi_register_in_span", "def abi_register_in_span(text: darray[u8]&, span_start: usize, span_stop: usize, spelling: sview) -> bool:", (
    "stop: usize = span_stop if span_stop <= text.count else text.count",
    "false return if span_start > stop",
    "for start in span_start..<stop |text, spelling, length, stop|",
    "continue if length > stop - start",
    "continue if not abi_span_is(text, start, spelling)",
    "text[start + length]",
))
require_in_order(abi_text, "abi_has_indirect", "def abi_has_indirect(text: darray[u8]&, keyword: sview) -> bool:", (
    "for start in 0..<text.count |text, keyword, length|",
    "continue if length > text.count - start",
    "continue if not abi_span_is(text, start, keyword)",
    "cursor: mutable usize = start + length",
))
for fragment in (
    "return abi_word_in_span(text, 0.usize(), text.count, needle)",
):
    if compact(fragment) not in compact(abi_text):
        raise SystemExit(f"ABI matcher no longer routes assembly token checks through the proved boundary logic: {fragment}")
if compact('continue if not abi_word_in_span(text, starts[line_index], line_stop, "__asm__") and not abi_word_in_span(text, starts[line_index], line_stop, "asm")') not in compact(scan_text):
    raise SystemExit("native ABI scanner no longer uses the proved whole-word matcher to find assembly")
native_body = function_body(scan_text, "abi_is_native_source", "def abi_is_native_source(path: darray[u8]&) -> bool:")
for fragment in (
    "dot: mutable usize = path.count",
    "for index in 0..<path.count |dot, path|",
    "dot <- index if path[index] == 46",
    "for index in dot..<path.count |extension, path|",
    "extension.push(abi_lower(path[index]))",
    'true return if bytes_equal_view(extension, ".c")',
    'true return if bytes_equal_view(extension, ".cc")',
    'true return if bytes_equal_view(extension, ".cpp")',
    'true return if bytes_equal_view(extension, ".cxx")',
    'true return if bytes_equal_view(extension, ".h")',
    'true return if bytes_equal_view(extension, ".hpp")',
    'true return if bytes_equal_view(extension, ".hh")',
    "return false",
):
    if compact(fragment) not in compact(native_body):
        raise SystemExit(f"native ABI extension classifier lost a whitelist step: {fragment}")
for fragment in (
    "if abi_is_native_source(absolute):",
    "continue if not abi_is_native_source(joined)",
):
    if compact(fragment) not in compact(scan_text):
        raise SystemExit(f"native ABI scanner no longer uses the proved extension classifier: {fragment}")
if 'include "./abi_lint.elisa"' not in DRIVER.read_text():
    raise SystemExit("compiler driver no longer imports ABI lint")
for path, label, text in (
    (POSITIVE, "positive", positive_text),
    (NEGATIVE, "negative", negative_text),
):
    if 'include "../../src/driver/project.elisa"' not in text or 'include "../../src/driver/abi_lint.elisa"' not in text:
        raise SystemExit(f"{label} ABI proofs no longer include the production matcher sources")

positive_names = {
    "abi_is_word_byte",
    "abi_lower",
    "word_byte_predicate_matches_ascii_definition",
    "lowercase_matches_ascii_casefold_definition",
    "ascii_casefold_preserves_word_byte_membership",
    "asm_token_match_obeys_both_word_boundaries",
    "extended_asm_token_obeys_both_word_boundaries",
    "byte_span_rejects_a_start_past_the_text",
    "case_insensitive_span_rejects_a_start_past_the_text",
    "byte_span_rejects_a_needle_beyond_the_remaining_text",
    "case_insensitive_span_rejects_a_needle_beyond_the_remaining_text",
    "word_span_rejects_a_start_past_the_text",
    "register_span_rejects_a_start_past_the_text",
    "word_span_rejects_a_needle_beyond_the_remaining_text",
    "register_span_rejects_a_spelling_beyond_the_remaining_text",
    "indirect_call_match_rejects_a_keyword_longer_than_the_text",
    "all_c_and_cpp_source_extensions_are_accepted",
    "all_c_and_cpp_header_extensions_are_accepted",
    "native_extension_matching_is_ascii_case_insensitive",
}
for name in positive_names - {"abi_is_word_byte", "abi_lower"}:
    if f"def {name}(" not in positive_text:
        raise SystemExit(f"positive ABI-byte theorem is missing: {name}")
negative_names = {
    "ascii_exclamation_mark_is_an_assembly_word_byte",
    "lowercase_ascii_a_is_changed_by_casefolding",
    "asm_after_an_ascii_word_prefix_is_a_whole_token",
    "asm_before_an_underscore_is_a_whole_token",
    "a_span_start_past_end_can_match",
    "a_word_span_start_past_end_can_match",
    "a_keyword_longer_than_the_text_can_be_an_indirect_call",
    "a_rust_source_is_a_native_abi_input",
    "a_c_suffix_before_a_later_extension_is_native",
    "a_dotless_path_is_a_native_abi_input",
}
for name in negative_names:
    if f"def {name}(" not in negative_text:
        raise SystemExit(f"negative ABI-byte control is missing: {name}")


def include_closure(roots: list[Path]) -> list[Path]:
    include = re.compile(r'^\s*include\s+"([^"]+)"', re.MULTILINE)
    pending = list(roots)
    seen: set[Path] = set()
    while pending:
        path = pending.pop().resolve(strict=True)
        if path in seen:
            continue
        seen.add(path)
        for relative in include.findall(path.read_text()):
            child = (path.parent / relative).resolve(strict=True)
            if child not in seen:
                pending.append(child)
    return sorted(seen)


try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("ABI lint byte-classification proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py", PROJECT, ABI,
          ABI_SCAN, DRIVER, *include_closure([POSITIVE, NEGATIVE, PROJECT, ABI])]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "ABI lint proof report changed across identical runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "ascii_exclamation_mark_is_an_assembly_word_byte"),
    ("ensure-unproven", "lowercase_ascii_a_is_changed_by_casefolding"),
    ("ensure-unproven", "asm_after_an_ascii_word_prefix_is_a_whole_token"),
    ("ensure-unproven", "asm_before_an_underscore_is_a_whole_token"),
    ("ensure-unproven", "a_span_start_past_end_can_match"),
    ("ensure-unproven", "a_word_span_start_past_end_can_match"),
    ("ensure-unproven", "a_keyword_longer_than_the_text_can_be_an_indirect_call"),
    ("ensure-unproven", "a_rust_source_is_a_native_abi_input"),
    ("ensure-unproven", "a_c_suffix_before_a_later_extension_is_native"),
    ("ensure-unproven", "a_dotless_path_is_a_native_abi_input"),
]
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest
print(json.dumps({
    "admitted": True,
    "scope": "ABI ASCII classification, overflow-safe span guards, and production whole-word asm boundaries",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
