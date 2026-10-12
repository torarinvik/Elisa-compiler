"""Admit source-linked decimal digit and separator policy proofs for capacity spans."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/backend/codegen_const_capacity_digits.elisa"
CAPACITY = ROOT / "src/backend/codegen_const_capacity.elisa"
POSITIVE = HERE / "backend_capacity_digits.elisa"
NEGATIVE = HERE / "backend_capacity_digits_rejected.elisa"

POSITIVE_NAMES = {
    "capacity_digit_classifier_matches_the_exact_byte_interval",
    "digit_separator_classifier_matches_both_neighbors",
    "separator_accepts_the_decimal_interval_boundaries",
    "separator_rejects_a_non_digit_on_either_side",
}
NEGATIVE_NAMES = {
    "separator_accepts_a_non_digit_before_the_separator",
    "separator_accepts_a_non_digit_after_the_separator",
}

if not __debug__:
    raise SystemExit("run without Python -O")


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
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


policy = POLICY.read_text()
if declarations(POLICY) != {"is_ascii_digit", "is_valid_digit_separator"}:
    raise SystemExit("capacity digit policy declaration inventory changed")
for name, value in (("ASCII_DIGIT_ZERO", 48), ("ASCII_DIGIT_NINE", 57)):
    if compact(f"const {name}: u8 = {value}") not in compact(policy):
        raise SystemExit(f"capacity digit boundary constant {name} changed")
expected_policy = {
    "is_ascii_digit": """
        def is_ascii_digit(byte: u8) -> bool:
            ensure result == (byte >= ASCII_DIGIT_ZERO and byte <= ASCII_DIGIT_NINE)
            return byte >= ASCII_DIGIT_ZERO and byte <= ASCII_DIGIT_NINE
    """,
    "is_valid_digit_separator": """
        def is_valid_digit_separator(previous: u8, following: u8) -> bool:
            ensure result == (is_ascii_digit(previous) and is_ascii_digit(following))
            return is_ascii_digit(previous) and is_ascii_digit(following)
    """,
}
for name, expected in expected_policy.items():
    if not re.search(rf"(?m)^[ \t]*@inline\(always\)[ \t]*\n[ \t]*def {re.escape(name)}\(", policy):
        raise SystemExit(f"hot capacity digit predicate lost its forced-inline contract: {name}")
    if compact(function_section(policy, name)) != compact(expected):
        raise SystemExit(f"capacity digit policy changed: {name}")

capacity = CAPACITY.read_text()
if 'include "./codegen_const_capacity_digits.elisa"' not in capacity:
    raise SystemExit("production capacity parser no longer imports the proved digit policy")
primary = compact(function_section(capacity, "capacity_span_parse_primary"))
for required in (
    "if BackendCapacityDigits::is_ascii_digit(sview_at(text, cursor)):",
    "if BackendCapacityDigits::is_ascii_digit(byte):",
    "elif byte == 95 and cursor > start and sview_len(text) - cursor > 1:",
    "break if not BackendCapacityDigits::is_valid_digit_separator(previous, following)",
):
    if compact(required) not in primary:
        raise SystemExit(f"capacity literal parser lost digit-policy wiring: {required}")
fold = compact(function_section(capacity, "fold_const_capacity_text"))
if compact("false return if cursor != sview_len(text)") not in fold:
    raise SystemExit("capacity parser no longer rejects a trailing malformed separator or suffix")

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("capacity digit proof inventory changed")
if 'include "../../src/backend/codegen_const_capacity_digits.elisa"' not in POSITIVE.read_text() or \
        'include "./backend_capacity_digits.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("capacity digit proofs must include the production policy and positive proof")

expected_positive = {
    "capacity_digit_classifier_matches_the_exact_byte_interval": """
        def capacity_digit_classifier_matches_the_exact_byte_interval(byte: u8) -> bool:
            ensure result == true
            return BackendCapacityDigits::is_ascii_digit(byte) == (
                byte >= BackendCapacityDigits::ASCII_DIGIT_ZERO and
                byte <= BackendCapacityDigits::ASCII_DIGIT_NINE
            )
    """,
    "digit_separator_classifier_matches_both_neighbors": """
        def digit_separator_classifier_matches_both_neighbors(previous: u8, following: u8) -> bool:
            ensure result == true
            return BackendCapacityDigits::is_valid_digit_separator(previous, following) == (
                BackendCapacityDigits::is_ascii_digit(previous) and
                BackendCapacityDigits::is_ascii_digit(following)
            )
    """,
    "separator_accepts_the_decimal_interval_boundaries": """
        def separator_accepts_the_decimal_interval_boundaries() -> bool:
            ensure result == true
            return BackendCapacityDigits::is_valid_digit_separator(
                BackendCapacityDigits::ASCII_DIGIT_ZERO,
                BackendCapacityDigits::ASCII_DIGIT_NINE
            )
    """,
    "separator_rejects_a_non_digit_on_either_side": """
        def separator_rejects_a_non_digit_on_either_side() -> bool:
            ensure result == true
            return (
                not BackendCapacityDigits::is_valid_digit_separator(
                    BackendCapacityDigits::ASCII_DIGIT_ZERO - 1,
                    BackendCapacityDigits::ASCII_DIGIT_ZERO
                ) and
                not BackendCapacityDigits::is_valid_digit_separator(
                    BackendCapacityDigits::ASCII_DIGIT_NINE,
                    BackendCapacityDigits::ASCII_DIGIT_NINE + 1
                )
            )
    """,
}
expected_negative = {
    "separator_accepts_a_non_digit_before_the_separator": """
        def separator_accepts_a_non_digit_before_the_separator() -> bool:
            ensure result == true
            return BackendCapacityDigits::is_valid_digit_separator(
                BackendCapacityDigits::ASCII_DIGIT_ZERO - 1,
                BackendCapacityDigits::ASCII_DIGIT_ZERO
            )
    """,
    "separator_accepts_a_non_digit_after_the_separator": """
        def separator_accepts_a_non_digit_after_the_separator() -> bool:
            ensure result == true
            return BackendCapacityDigits::is_valid_digit_separator(
                BackendCapacityDigits::ASCII_DIGIT_NINE,
                BackendCapacityDigits::ASCII_DIGIT_NINE + 1
            )
    """,
}
for path, expected in ((POSITIVE, expected_positive), (NEGATIVE, expected_negative)):
    source = path.read_text()
    for name, theorem in expected.items():
        if compact(function_section(source, name)) != compact(theorem):
            raise SystemExit(f"{path.name} theorem {name} changed its exact claim")

manifest = require_current_product(BIN, PROVER)
if manifest.get("compile_mode") != "strict":
    raise SystemExit("capacity digit proof requires a strict proof build")
stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"), PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POLICY, CAPACITY, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE]),
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = replay(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in NEGATIVE_NAMES
}
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({
    "admitted": True,
    "scope": "capacity decimal-byte classification and separator rejection",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(NEGATIVE_NAMES),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
