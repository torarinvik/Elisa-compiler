"""Admit source-linked proofs of the scalar-kind policy used by semantic diagnostics."""
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
HELPER = ROOT / "src/semantic/scalar_value_kind.elisa"
CONSUMER = ROOT / "src/semantic/resolve_types_initializers.elisa"
POSITIVE = HERE / "scalar_value_kind.elisa"
NEGATIVE = HERE / "scalar_value_kind_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
PROOF_TIMEOUT_SECONDS = 60
PRODUCTION_CLASSIFIER_MATCH_COUNT = 2

if not __debug__:
    raise SystemExit("run without Python -O")

names = ("int", "float", "bool", "char", "string")


def compact(text: str) -> str:
    return "".join(text.split())


def require_exact_match(text: str, description: str) -> None:
    blocks = re.findall(r"(?m)^\s*when kind:\s*\n(.*?)(?=^\s*\))", text, re.DOTALL)
    for block in blocks:
        arms = [line.strip() for line in block.splitlines() if line.strip()]
        if not arms or arms[-1] != "_ -> false":
            raise SystemExit(f"{description} lost its false fallback")
        found = []
        for arm in arms[:-1]:
            if not re.fullmatch(r'"[^"\\]+"(?:\s*\|\s*"[^"\\]+")*\s*->\s*true', arm):
                raise SystemExit(f"{description} contains a nonliteral match arm")
            found.extend(re.findall(r'"([^"\\]+)"', arm))
        if found == list(names):
            return
    raise SystemExit(f"{description} differs from the exact scalar-kind set")


source_text = HELPER.read_text()
proof_text = POSITIVE.read_text()
require_exact_match(source_text, "production scalar-kind classifier")
require_exact_match(proof_text, "source-linked proof contract")
exact_arms = compact('"int" | "float" | "bool" | "char" | "string" -> true _ -> false')
if compact(source_text).count(exact_arms) != PRODUCTION_CLASSIFIER_MATCH_COUNT:
    raise SystemExit("production classifier contract and implementation must use the same exact match")
if compact(proof_text).count(exact_arms) != 1:
    raise SystemExit("proof must state the exact scalar-kind match contract")
consumer_text = CONSUMER.read_text()
if 'include "./scalar_value_kind.elisa"' not in consumer_text:
    raise SystemExit("semantic initializer checker no longer imports the classifier")
if consumer_text.count("ScalarValueKind::is_scalar_value_kind(") != PRODUCTION_CLASSIFIER_MATCH_COUNT:
    raise SystemExit("container assignment and return checks must both use the classifier")
for obsolete in (
    'assigned_kind == "int" or assigned_kind == "float"',
    'returned_kind == "int" or returned_kind == "float"',
):
    if obsolete in consumer_text:
        raise SystemExit("semantic consumer still contains an inline scalar-kind chain")
for name in (
    "source_classifier_has_exact_scalar_set",
    "every_scalar_value_kind_is_recognized",
    "non_scalar_types_remain_unclassified",
):
    if not re.search(rf"(?m)^def {re.escape(name)}\(", proof_text):
        raise SystemExit(f"positive proof is missing {name}")
negative_text = NEGATIVE.read_text()
negative_names = {
    "an_integer_type_is_a_scalar_value_kind",
    "a_container_is_a_scalar_value_kind",
}
for name in negative_names:
    if not re.search(rf"(?m)^def {re.escape(name)}\(", negative_text):
        raise SystemExit(f"negative proof is missing {name}")
if 'include "../../src/semantic/scalar_value_kind.elisa"' not in proof_text:
    raise SystemExit("positive proof no longer imports the production classifier")
if 'include "./scalar_value_kind.elisa"' not in negative_text:
    raise SystemExit("negative claims no longer challenge the source-linked proof")

mutations = (
    source_text.replace('"int" | "float"', '"i64" | "float"', 1),
    source_text.replace('_ -> false', '_ -> true', 1),
    source_text.replace('"char"', '"byte"', 1),
)
for mutated in mutations:
    try:
        require_exact_match(mutated, "mutated classifier")
    except SystemExit:
        pass
    else:
        raise SystemExit("scalar-kind source mutation escaped the closed-set check")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("scalar-kind proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, CONSUMER])
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
positive_names = {
    "source_classifier_has_exact_scalar_set",
    "every_scalar_value_kind_is_recognized",
    "non_scalar_types_remain_unclassified",
}
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == len(positive_names)
assert not positive["findings"]
assert positive_names <= {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive == run(POSITIVE)[1], "scalar-kind proof report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "closed scalar-kind classification shared by assignment and return diagnostics",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
