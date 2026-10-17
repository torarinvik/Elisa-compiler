"""Bind full-width scalar hash bijection proofs to the collection runtime."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
COLLECTIONS = ROOT / "elisacore_std/collections.elisa"
POSITIVE = HERE / "ctx_hash_u64_bijection.elisa"
NEGATIVE = HERE / "ctx_hash_u64_bijection_rejected.elisa"
MUL_1 = 0xbf58476d1ce4e5b9
MUL_1_INV = 0x96de1b173f119089
MUL_2 = 0x94d049bb133111eb
MUL_2_INV = 0x319642b2d24d8ec3
MASK_64 = (1 << 64) - 1

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking Elisa-Proof")
ARGS = parser.parse_args()
if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(
        rf"(?m)^{re.escape(indent)}(?:ghost[ \t]+)?def [A-Za-z_][A-Za-z0-9_]*\(",
        source[match.end():],
    )
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


collections_text = COLLECTIONS.read_text()
hash_body = compact(function_section(collections_text, "ctx_hash_u64"))
if compact("ensure ctx_unhash_u64(result) == value") not in hash_body:
    raise SystemExit("ctx_hash_u64 lost its production left-inverse postcondition")
if compact("const CTX_HASH_U64_INV_MUL_1: u64 = 0x96de1b173f119089") not in compact(collections_text) \
        or compact("const CTX_HASH_U64_INV_MUL_2: u64 = 0x319642b2d24d8ec3") not in compact(collections_text):
    raise SystemExit("production scalar-hash inverse constants changed without updating the proof")
steps = (
    "h: mutable u64 = value",
    "h <- (h ^ (h >> 30)) * 0xbf58476d1ce4e5b9",
    "h <- (h ^ (h >> 27)) * 0x94d049bb133111eb",
    "h <- h ^ (h >> 31)",
    "return h",
)
positions = [hash_body.find(compact(step)) for step in steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("ctx_hash_u64 no longer has the specified ordered SplitMix finalizer stages")
if MUL_1 * MUL_1_INV & MASK_64 != 1 or MUL_2 * MUL_2_INV & MASK_64 != 1:
    raise SystemExit("the proof's odd-multiplier inverses are invalid modulo 2^64")

inverse_body = compact(function_section(collections_text, "ctx_unhash_u64"))
inverse_steps = (
    "ensure result == ctx_unhash_xor_30(ctx_unhash_mul_1(ctx_unhash_xor_27(ctx_unhash_mul_2(ctx_unhash_xor_31(hash)))))",
    "return ctx_unhash_xor_30(ctx_unhash_mul_1(ctx_unhash_xor_27(ctx_unhash_mul_2(ctx_unhash_xor_31(hash)))))",
)
inverse_positions = [inverse_body.find(compact(step)) for step in inverse_steps]
if any(position < 0 for position in inverse_positions) or inverse_positions != sorted(inverse_positions):
    raise SystemExit("scalar inverse no longer reverses the hash stages in reverse order")
for name, relation in (
    ("ctx_unhash_xor_31", "ensure result == (value ^ (value >> 31) ^ (value >> 62))"),
    ("ctx_unhash_xor_31", "ensure result ^ (result >> 31) == value"),
    ("ctx_unhash_xor_27", "ensure result == (value ^ (value >> 27) ^ (value >> 54))"),
    ("ctx_unhash_xor_27", "ensure result ^ (result >> 27) == value"),
    ("ctx_unhash_xor_30", "ensure result == (value ^ (value >> 30) ^ (value >> 60))"),
    ("ctx_unhash_xor_30", "ensure result ^ (result >> 30) == value"),
    ("ctx_unhash_mul_1", "ensure result == value * CTX_HASH_U64_INV_MUL_1"),
    ("ctx_unhash_mul_1", "ensure result * 0xbf58476d1ce4e5b9 == value"),
    ("ctx_unhash_mul_2", "ensure result == value * CTX_HASH_U64_INV_MUL_2"),
    ("ctx_unhash_mul_2", "ensure result * 0x94d049bb133111eb == value"),
):
    if compact(relation) not in compact(function_section(collections_text, name)):
        raise SystemExit(f"{name} lost its one-round inverse contract")
for name, cutpoints in (
    ("ctx_unhash_xor_31", ("assert first_shift >> 31 == second_shift", "assert second_shift >> 31 == 0", "assert candidate >> 31 == shifted_candidate", "assert candidate ^ shifted_candidate == value", "assert candidate ^ (candidate >> 31) == value", "assert candidate == (value ^ (value >> 31) ^ (value >> 62))")),
    ("ctx_unhash_xor_27", ("assert first_shift >> 27 == second_shift", "assert second_shift >> 27 == 0", "assert candidate >> 27 == shifted_candidate", "assert candidate ^ shifted_candidate == value", "assert candidate ^ (candidate >> 27) == value", "assert candidate == (value ^ (value >> 27) ^ (value >> 54))")),
    ("ctx_unhash_xor_30", ("assert first_shift >> 30 == second_shift", "assert second_shift >> 30 == 0", "assert candidate >> 30 == shifted_candidate", "assert candidate ^ shifted_candidate == value", "assert candidate ^ (candidate >> 30) == value", "assert candidate == (value ^ (value >> 30) ^ (value >> 60))")),
):
    section = compact(function_section(collections_text, name))
    if any(compact(cutpoint) not in section for cutpoint in cutpoints):
        raise SystemExit(f"{name} lost its one-round XOR proof cutpoints")

positive_claims = {
    "inverse_multipliers_are_units_modulo_64_bits": "0xbf58476d1ce4e5b9 * CTX_HASH_U64_INV_MUL_1 == 1 and 0x94d049bb133111eb * CTX_HASH_U64_INV_MUL_2 == 1",
    "scalar_hash_finalizer_roundtrips_every_word": "ctx_unhash_u64(ctx_hash_u64(value)) == value",
    "equal_scalar_hashes_imply_equal_words": "left == right",
}
positive_requirements = {
    "equal_scalar_hashes_imply_equal_words": "requires ctx_hash_u64(left) == ctx_hash_u64(right)",
}
negative_claims = {
    "distinct_words_can_share_a_scalar_hash": "ctx_hash_u64(left) == ctx_hash_u64(right)",
    "the_inverse_can_miss_a_scalar_hash_input": "ctx_unhash_u64(ctx_hash_u64(value)) != value",
}
negative_requirements = {
    "distinct_words_can_share_a_scalar_hash": "requires left != right",
}
for path, claims, requirements, label in (
    (POSITIVE, positive_claims, positive_requirements, "positive"),
    (NEGATIVE, negative_claims, negative_requirements, "negative"),
):
    source = path.read_text()
    if declarations(source) != set(claims):
        raise SystemExit(f"{label} scalar-hash theorem inventory changed")
    if 'include "../../elisacore_std/elisacore_runtime_prelude.elisa"' not in source \
            or 'include "../../elisacore_std/collections.elisa"' not in source:
        raise SystemExit(f"{label} scalar-hash proof no longer includes the production collection runtime")
    for name, claim in claims.items():
        section = compact(function_section(source, name))
        if compact("ensure result == true") not in section \
                or compact(claim) not in section \
                or (name in requirements and compact(requirements[name]) not in section):
            raise SystemExit(f"{label} scalar-hash theorem {name} lost its claim or precondition")
        if name != "inverse_multipliers_are_units_modulo_64_bits" and "ctx_hash_u64(" not in section:
            raise SystemExit(f"{label} scalar-hash theorem {name} is no longer bound to production")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if COLLECTIONS not in source_closure:
    raise SystemExit("proof include closure no longer contains ctx_hash_u64 production source")
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive": len(positive_claims),
                      "false_claim_controls": len(negative_claims),
                      "source_closure_files": len(source_closure)}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("scalar-hash bijection proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", COLLECTIONS, POSITIVE, NEGATIVE, *source_closure,
]))
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
assert positive["summary"]["declarations"] == len(positive_claims)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == set(positive_claims)

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == set(negative_claims)
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not set(negative_claims) & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "ctx_hash_u64 is inverted for every u64, proving full-width injectivity",
    "positive_claims_proved": sorted(positive_claims),
    "false_claims_refused": sorted(negative_claims),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
