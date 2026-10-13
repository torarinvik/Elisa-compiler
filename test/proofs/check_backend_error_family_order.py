"""Replay the source-bound proof for backend error-family ordering."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure

if not __debug__:
    raise SystemExit("run without Python -O")

ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
BACKEND = ROOT / "src/backend/codegen.elisa"
ERROR_UNIONS = ROOT / "src/backend/codegen_error_union_reg.elisa"
POSITIVE = HERE / "backend_error_family_order.elisa"
NEGATIVE = HERE / "backend_error_family_order_rejected.elisa"
BYTE_ORDER = HERE / "backend_error_family_byte_order.elisa"
POSITIVE_NAMES = {
    "error_family_order_is_asymmetric",
    "error_family_order_is_total",
    "error_family_order_is_transitive",
    "equal_names_are_not_ordered_before_themselves",
    "the_first_differing_byte_decides_before_the_suffix",
    "a_later_differing_byte_decides_after_an_equal_prefix",
    "a_proper_prefix_precedes_its_extension",
    "empty_name_precedes_a_nonempty_name",
}
NEGATIVE_NAMES = {
    "a_proper_extension_does_not_precede_its_prefix",
    "a_greater_first_byte_does_not_precede_a_smaller_one",
    "a_smaller_byte_is_not_preceded_by_a_larger_byte",
    "a_concrete_byte_order_chain_can_break_transitivity",
}
BYTE_ORDER_NAMES = {
    "byte_less_is_asymmetric",
    "byte_less_is_transitive",
    "byte_order_is_total",
}


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost )?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost )?def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^\s*def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def ghost_declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^\s*ghost def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


production_text = ERROR_UNIONS.read_text()
expected_production = """
def error_family_precedes(left: sview, right: sview) -> bool:
    left_length: usize = left.len
    right_length: usize = right.len
    shared_length: usize = left_length if left_length < right_length else right_length
    for index in 0..<shared_length |left, right|:
        return left[index] < right[index] if left[index] != right[index]
    return left_length < right_length
"""
if compact(function_section(production_text, "error_family_precedes")) != compact(expected_production):
    raise SystemExit("the production error-family comparator changed without updating its proof")

proof_text = POSITIVE.read_text()
expected_reference = """
ghost def error_family_precedes_from(left: sview, right: sview, index: usize) -> bool:
    requires index <= left.len and index <= right.len
    decreases (left.len if left.len < right.len else right.len) - index
    left_length: usize = left.len
    right_length: usize = right.len
    shared_length: usize = left_length if left_length < right_length else right_length
    return left_length < right_length if index == shared_length
    return left[index] < right[index] if left[index] != right[index]
    return error_family_precedes_from(left, right, index + 1)
"""
if compact(function_section(proof_text, "error_family_precedes_from")) != compact(expected_reference):
    raise SystemExit("the recursive lexicographic specification changed without updating its proof")

expected_asymmetry_lemma = """
ghost def error_family_order_pair_not_both_from(left: sview, right: sview, index: usize) -> bool:
    requires index <= left.len and index <= right.len
    decreases (left.len if left.len < right.len else right.len) - index
    ensures result == not (
        error_family_precedes_at(left, right, index)
        and error_family_precedes_at(right, left, index)
    )
    ensures result == true
    left_length: usize = left.len
    right_length: usize = right.len
    if index < left_length and index < right_length:
        return byte_less_is_asymmetric(left[index], right[index]) if left[index] != right[index]
        return error_family_order_pair_not_both_from(left, right, index + 1)
    return not (left_length < right_length and right_length < left_length)
"""
if compact(function_section(proof_text, "error_family_order_pair_not_both_from")) != compact(expected_asymmetry_lemma):
    raise SystemExit("the recursive strict-order asymmetry lemma changed without updating its proof")

byte_order_text = BYTE_ORDER.read_text()
expected_byte_order_laws = {
    "byte_less_is_asymmetric": "ghost def byte_less_is_asymmetric(left: u8, right: u8) -> bool: ensure result == true return not (left < right and right < left)",
    "byte_less_is_transitive": "ghost def byte_less_is_transitive(left: u8, middle: u8, right: u8) -> bool: ensure result == true return not (left < middle and middle < right) or left < right",
    "byte_order_is_total": "ghost def byte_order_is_total(left: u8, right: u8) -> bool: ensure result == true return left < right or right < left or left == right",
}
if declarations(BYTE_ORDER) or ghost_declarations(BYTE_ORDER) != BYTE_ORDER_NAMES:
    raise SystemExit("the primitive byte-order proof inventory changed")
for name, shape in expected_byte_order_laws.items():
    if compact(function_section(byte_order_text, name)) != compact(shape):
        raise SystemExit(f"{name} no longer proves the byte ordering law used by error-family comparison")
if 'include "./backend_error_family_byte_order.elisa"' not in proof_text:
    raise SystemExit("the error-family comparator proof no longer imports its byte-order laws")
expected_total_wrappers = {
    "error_family_precedes_at": "ghost def error_family_precedes_at(left: sview, right: sview, index: usize) -> bool: left_length: usize = left.len right_length: usize = right.len if index <= left.len and index <= right.len: return error_family_precedes_from(left, right, index) return left_length < right_length",
    "error_family_equal_at": "ghost def error_family_equal_at(left: sview, right: sview, index: usize) -> bool: left_length: usize = left.len right_length: usize = right.len if index <= left.len and index <= right.len: return error_family_equal_from(left, right, index) return left_length == right_length",
}
for wrapper_name, wrapper_shape in expected_total_wrappers.items():
    if compact(function_section(proof_text, wrapper_name)) != compact(wrapper_shape):
        raise SystemExit(f"{wrapper_name} no longer guards its recursive precondition explicitly")

expected_model = """
def error_family_precedes(left: sview, right: sview) -> bool:
    ensure result == error_family_precedes_at(left, right, 0)
    left_length: usize = left.len
    right_length: usize = right.len
    shared_length: usize = left_length if left_length < right_length else right_length
    index: mutable usize = 0
    while index < shared_length |index, left, right|:
        decreases shared_length - index
        invariant index <= shared_length
        invariant error_family_precedes_at(left, right, index) == error_family_precedes_at(left, right, 0)
        if index < left_length and index < right_length:
            return left[index] < right[index] if left[index] != right[index]
            index <- index + 1
        else:
            return left_length < right_length
    return left_length < right_length
"""
if compact(function_section(proof_text, "error_family_precedes")) != compact(expected_model):
    raise SystemExit("the proved comparator model no longer mirrors the production comparator")
expected_asymmetry_theorem = """
ghost def error_family_order_is_asymmetric(left: sview, right: sview) -> bool:
    ensure result == not (error_family_precedes_at(left, right, 0) and error_family_precedes_at(right, left, 0))
    ensure result == true
    return error_family_order_pair_not_both_from(left, right, 0)
"""
if compact(function_section(proof_text, "error_family_order_is_asymmetric")) != compact(expected_asymmetry_theorem):
    raise SystemExit("the universal strict-order asymmetry theorem changed without updating its proof")
expected_total_theorem = "ghost def error_family_order_is_total(left: sview, right: sview) -> bool: ensure result == (error_family_precedes_at(left, right, 0) or error_family_precedes_at(right, left, 0) or error_family_equal_at(left, right, 0)) ensure result == true return error_family_order_total_from(left, right, 0)"
if compact(function_section(proof_text, "error_family_order_is_total")) != compact(expected_total_theorem):
    raise SystemExit("the universal error-family totality theorem changed without updating its proof")
expected_transitive_theorem = "ghost def error_family_order_is_transitive(left: sview, middle: sview, right: sview) -> bool: ensure result == (not (error_family_precedes_at(left, middle, 0) and error_family_precedes_at(middle, right, 0)) or error_family_precedes_at(left, right, 0)) ensure result == true return error_family_order_transitive_from(left, middle, right, 0)"
if compact(function_section(proof_text, "error_family_order_is_transitive")) != compact(expected_transitive_theorem):
    raise SystemExit("the universal error-family transitivity theorem changed without updating its proof")

if 'include "../../src/backend/codegen_error_union_reg.elisa"' in proof_text:
    raise SystemExit("proof model must stay isolated from the full LLVM backend module")
if 'include "./backend_error_family_order.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer reuse the positive ordering model")
negative_byte_shape = "def a_smaller_byte_is_not_preceded_by_a_larger_byte(left: u8, right: u8) -> bool: requires left < right ensure result == true return right < left"
if compact(function_section(NEGATIVE.read_text(), "a_smaller_byte_is_not_preceded_by_a_larger_byte")) != compact(negative_byte_shape):
    raise SystemExit("the false reverse-byte-order control changed")
negative_transitivity_shape = "def a_concrete_byte_order_chain_can_break_transitivity() -> bool: ensure result == true return error_family_precedes(\"a\", \"b\") and error_family_precedes(\"b\", \"c\") and not error_family_precedes(\"a\", \"c\")"
if compact(function_section(NEGATIVE.read_text(), "a_concrete_byte_order_chain_can_break_transitivity")) != compact(negative_transitivity_shape):
    raise SystemExit("the false lexicographic transitivity control changed")
if compact(function_section(production_text, "register_error_union_row")).find("whilecursor>0anderror_family_precedes(") < 0:
    raise SystemExit("error-union ABI registration no longer orders families with the proved comparator")
if 'include "./codegen_error_union_reg.elisa"' not in BACKEND.read_text():
    raise SystemExit("the backend facade no longer includes error-union registration")
if declarations(POSITIVE) != (POSITIVE_NAMES - {
    "error_family_order_is_asymmetric",
    "error_family_order_is_total",
    "error_family_order_is_transitive",
}) | {"error_family_precedes"}:
    raise SystemExit("the positive error-family ordering proof inventory changed")
if ghost_declarations(POSITIVE) != {
    "error_family_precedes_from",
    "error_family_equal_from",
    "error_family_precedes_at",
    "error_family_equal_at",
    "error_family_order_pair_not_both_from",
    "error_family_order_total_from",
    "error_family_order_transitive_from",
    "error_family_order_is_asymmetric",
    "error_family_order_is_total",
    "error_family_order_is_transitive",
}:
    raise SystemExit("the ghost error-family ordering lemma inventory changed")
if declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("the negative error-family ordering proof inventory changed")
if ghost_declarations(NEGATIVE):
    raise SystemExit("the error-family negative controls unexpectedly changed ghost inventory")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("error-family ordering proofs require a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if compiler_head != product["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", BACKEND, ERROR_UNIONS,
    POSITIVE, NEGATIVE, BYTE_ORDER, *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = replay(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert POSITIVE_NAMES | {"error_family_precedes"} <= verified
assert BYTE_ORDER_NAMES <= verified
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert NEGATIVE_NAMES.isdisjoint({row["name"] for row in negative["declaration_details"] if row.get("verified")})
assert require_current_product(BIN, PROVER) == product
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "error-family proof inputs changed during replay or provenance validation"
print(json.dumps({
    "admitted": True,
    "scope": "unsigned-byte laws and universal asymmetry, totality, and transitivity of error-family lexicographic ordering",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
