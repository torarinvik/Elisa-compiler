"""Admit source-linked proofs for signed and unsigned bit-int endpoints."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
ENDPOINTS = ROOT / "src/semantic/bit_int_endpoints.elisa"
PARSER = ROOT / "src/semantic/check_const_enum_value_fits.elisa"
POSITIVE = HERE / "bit_int_width_endpoints.elisa"
NEGATIVE = HERE / "bit_int_width_endpoints_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def function_source(text: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*def\s+{re.escape(name)}(?=\[|\()", text)
    if not match:
        raise SystemExit(f"missing production or proof function: {name}")
    tail = text[match.end():]
    following = re.search(r"(?m)^\s*(?:def\s+|public:|private:|module\s+|extend\s+)", tail)
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


def require_endpoint_contracts(source: str) -> list[str]:
    errors: list[str] = []
    contracts = {
        "unsigned_high_from_span": (
            "requires span >= 1 and span <= I64_MAX",
            "ensure result == span - 1",
            "ensure result >= 0",
            "ensure result <= I64_MAX",
            "return span - 1",
        ),
        "signed_low_from_span": (
            "requires span >= 1 and span <= SIGNED_SPAN_MAX",
            "ensure result == 0 - span",
            "ensure result >= SIGNED_LOW_MIN",
            "ensure result < 0",
            "return 0 - span",
        ),
        "signed_high_from_span": (
            "requires span >= 1 and span <= SIGNED_SPAN_MAX",
            "ensure result == span - 1",
            "ensure result >= 0",
            "ensure result <= I64_MAX",
            "return span - 1",
        ),
    }
    for name, clauses in contracts.items():
        body = compact(function_source(source, name))
        for clause in clauses:
            normalized = compact(clause)
            if body.count(normalized) != 1:
                errors.append(f"{name} must state and implement exactly once: {clause}")

    for name, value in (
        ("I64_MAX", "9223372036854775807"),
        ("SIGNED_SPAN_MAX", "4611686018427387904"),
        ("SIGNED_LOW_MIN", "0 - SIGNED_SPAN_MAX"),
    ):
        declaration = compact(f"const {name}: i64 = {value}")
        if compact(source).count(declaration) != 1:
            errors.append(f"endpoint bound changed or duplicated: {name}")
    if source.count("module SemanticBitIntEndpoints:") != 1:
        errors.append("endpoint helper module is missing or duplicated")
    return errors


ENDPOINT_TEXT = ENDPOINTS.read_text()
PARSER_TEXT = PARSER.read_text()
source_errors = require_endpoint_contracts(ENDPOINT_TEXT)
if source_errors:
    raise SystemExit("\n".join(source_errors))
if 'include "./bit_int_endpoints.elisa"' not in PARSER_TEXT:
    raise SystemExit("production bit-int parser no longer imports endpoint helpers")

unsigned_steps = (
    "span: i64 = 1 << bits.usize()",
    "(false, 0, 0) return if span < SemanticBitIntWidth::BIT_INT_MIN_WIDTH or span > SemanticBitIntEndpoints::I64_MAX",
    "high: i64 = SemanticBitIntEndpoints::unsigned_high_from_span(span)",
    "return (true, SemanticBitIntWidth::BIT_INT_PREFIX_MIN, high)",
)
signed_steps = (
    "span: i64 = 1 << (bits - SemanticBitIntWidth::BIT_INT_MIN_WIDTH).usize()",
    "(false, 0, 0) return if span < SemanticBitIntWidth::BIT_INT_MIN_WIDTH or span > SemanticBitIntEndpoints::SIGNED_SPAN_MAX",
    "low: i64 = SemanticBitIntEndpoints::signed_low_from_span(span)",
    "high: i64 = SemanticBitIntEndpoints::signed_high_from_span(span)",
    "return (true, low, high)",
)


def require_parser_routes(source: str) -> list[str]:
    parser = compact(function_source(source, "bit_int_window"))
    errors = []
    for label, fragments in (("unsigned", unsigned_steps), ("signed", signed_steps)):
        positions = [parser.find(compact(fragment)) for fragment in fragments]
        if any(position < 0 for position in positions) or positions != sorted(positions):
            errors.append(f"production {label} bit-int window must guard spans before calling endpoint helpers")
    return errors


parser_errors = require_parser_routes(PARSER_TEXT)
if parser_errors:
    raise SystemExit("\n".join(parser_errors))

# Confirm that the source gate fails if an endpoint contract or a production route is weakened.
mutations = (
    (
        "unsigned representability postcondition",
        ENDPOINT_TEXT.replace("ensure result <= I64_MAX", "ensure result < I64_MAX", 1),
        PARSER_TEXT,
    ),
    (
        "signed low representability postcondition",
        ENDPOINT_TEXT.replace("ensure result >= SIGNED_LOW_MIN", "ensure result > SIGNED_LOW_MIN", 1),
        PARSER_TEXT,
    ),
    (
        "unsigned helper route",
        ENDPOINT_TEXT,
        PARSER_TEXT.replace("SemanticBitIntEndpoints::unsigned_high_from_span(span)", "span - 1", 1),
    ),
    (
        "signed low helper route",
        ENDPOINT_TEXT,
        PARSER_TEXT.replace("SemanticBitIntEndpoints::signed_low_from_span(span)", "0 - span", 1),
    ),
    (
        "signed high helper route",
        ENDPOINT_TEXT,
        PARSER_TEXT.replace("SemanticBitIntEndpoints::signed_high_from_span(span)", "span - 1", 1),
    ),
    (
        "signed span upper guard",
        ENDPOINT_TEXT,
        PARSER_TEXT.replace("span > SemanticBitIntEndpoints::SIGNED_SPAN_MAX", "span >= SemanticBitIntEndpoints::SIGNED_SPAN_MAX", 1),
    ),
)
for label, endpoint_mutation, parser_mutation in mutations:
    if endpoint_mutation == ENDPOINT_TEXT and parser_mutation == PARSER_TEXT:
        raise SystemExit(f"mutation fixture for {label} did not change its input")
    if endpoint_mutation != ENDPOINT_TEXT and not require_endpoint_contracts(endpoint_mutation):
        raise SystemExit(f"source checker failed to catch mutation of {label}")
    if parser_mutation != PARSER_TEXT and not require_parser_routes(parser_mutation):
        raise SystemExit(f"source checker failed to catch mutation of {label}")

if 'include "../../src/semantic/bit_int_endpoints.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive endpoint proof no longer imports the production helpers")
if 'include "./bit_int_width_endpoints.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("endpoint false controls no longer import the positive proof suite")

expected_positive = {
    "signed_low_endpoint_is_representable",
    "signed_high_endpoint_is_representable",
    "every_signed_window_is_ordered",
    "every_signed_window_contains_zero",
    "signed_one_bit_window_is_minus_one_through_zero",
    "signed_sixty_three_bit_window_has_exact_endpoints",
    "every_unsigned_window_is_ordered",
    "unsigned_one_bit_window_has_zero_high",
    "largest_unsigned_span_has_representable_high",
}
expected_negative = {
    "false_signed_low_is_nonnegative",
    "false_signed_high_reaches_the_span",
    "false_unsigned_high_reaches_the_span",
    "false_signed_sixty_three_high_is_i64_max",
    "false_unsigned_one_bit_high_is_one",
}
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
positive_names = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", positive_text))
negative_names = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", negative_text))
if positive_names != expected_positive:
    raise SystemExit(f"positive endpoint theorem inventory changed: {sorted(positive_names)}")
if negative_names != expected_negative:
    raise SystemExit(f"endpoint false-control inventory changed: {sorted(negative_names)}")

positive_shapes = {
    "signed_low_endpoint_is_representable": (
        "requires span >= 1 and span <= SemanticBitIntEndpoints::SIGNED_SPAN_MAX",
        "low: i64 = SemanticBitIntEndpoints::signed_low_from_span(span)",
        "return low >= SemanticBitIntEndpoints::SIGNED_LOW_MIN and low >= (0 - 9223372036854775807 - 1) and low < 0",
    ),
    "signed_high_endpoint_is_representable": (
        "high: i64 = SemanticBitIntEndpoints::signed_high_from_span(span)",
        "return high >= 0 and high <= SemanticBitIntEndpoints::I64_MAX",
    ),
    "every_signed_window_is_ordered": (
        "low: i64 = SemanticBitIntEndpoints::signed_low_from_span(span)",
        "high: i64 = SemanticBitIntEndpoints::signed_high_from_span(span)",
        "return low <= high",
    ),
    "every_signed_window_contains_zero": (
        "return low <= 0 and 0 <= high",
    ),
    "signed_one_bit_window_is_minus_one_through_zero": (
        "SemanticBitIntEndpoints::signed_low_from_span(1)",
        "SemanticBitIntEndpoints::signed_high_from_span(1)",
        "return low == (0 - 1) and high == 0",
    ),
    "signed_sixty_three_bit_window_has_exact_endpoints": (
        "SemanticBitIntEndpoints::SIGNED_SPAN_MAX",
        "return low == (0 - 4611686018427387904) and high == 4611686018427387903",
    ),
    "every_unsigned_window_is_ordered": (
        "requires span >= 1 and span <= SemanticBitIntEndpoints::I64_MAX",
        "high: i64 = SemanticBitIntEndpoints::unsigned_high_from_span(span)",
        "return 0 <= high and high <= SemanticBitIntEndpoints::I64_MAX",
    ),
    "unsigned_one_bit_window_has_zero_high": (
        "SemanticBitIntEndpoints::unsigned_high_from_span(1)",
        "return high == 0",
    ),
    "largest_unsigned_span_has_representable_high": (
        "SemanticBitIntEndpoints::I64_MAX",
        "return high == SemanticBitIntEndpoints::I64_MAX - 1",
    ),
}
for theorem, fragments in positive_shapes.items():
    body = compact(function_source(positive_text, theorem))
    if "ensureresult==true" not in body or any(compact(fragment) not in body for fragment in fragments):
        raise SystemExit(f"endpoint theorem {theorem} no longer states its intended arithmetic result")
    if "SemanticBitIntEndpoints::" not in body:
        raise SystemExit(f"endpoint theorem {theorem} no longer exercises production helpers")

negative_shapes = {
    "false_signed_low_is_nonnegative": "SemanticBitIntEndpoints::signed_low_from_span(span)>=0",
    "false_signed_high_reaches_the_span": "SemanticBitIntEndpoints::signed_high_from_span(span)>=span",
    "false_unsigned_high_reaches_the_span": "SemanticBitIntEndpoints::unsigned_high_from_span(span)>=span",
    "false_signed_sixty_three_high_is_i64_max": "SemanticBitIntEndpoints::signed_high_from_span(SemanticBitIntEndpoints::SIGNED_SPAN_MAX)==SemanticBitIntEndpoints::I64_MAX",
    "false_unsigned_one_bit_high_is_one": "SemanticBitIntEndpoints::unsigned_high_from_span(1)==1",
}
for theorem, expression in negative_shapes.items():
    body = compact(function_source(negative_text, theorem))
    if "ensureresult==true" not in body or f"return{expression}" not in body:
        raise SystemExit(f"false control {theorem} no longer challenges its endpoint boundary")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("bit-int endpoint proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    ENDPOINTS, PARSER, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE, PARSER]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
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
assert positive == run(POSITIVE)[1], "endpoint proof report changed across identical runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert verified == expected_positive

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] in {"failed", "disproved"}
assert negative["summary"]["unproven"] == len(expected_negative)
assert {row["name"] for row in negative["findings"]} == expected_negative
assert all(row["kind"] == "ensure-unproven" and row["status"] in {"unknown", "disproved"}
           for row in negative["findings"])
assert all(not row.get("counterexample_found") or row["status"] == "disproved"
           for row in negative["findings"])
negative_verified = {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert expected_positive <= negative_verified
assert not expected_negative & negative_verified
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "source-bound signed and unsigned bit-int span-to-endpoint arithmetic, including i63 and the largest representable unsigned span",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
