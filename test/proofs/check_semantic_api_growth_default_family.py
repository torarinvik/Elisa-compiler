"""Admit the source-linked semantic API growth-family mapping proof."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "semantic_api_growth_default_family.elisa"
NEGATIVE = HERE / "semantic_api_growth_default_family_rejected.elisa"
SOURCE = ROOT / "src/semantic/semantic_api_growth_default_family.elisa"
CALLER = ROOT / "src/semantic/semantic_api_message_3.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


source_text = compact(SOURCE.read_text())
caller_text = compact(CALLER.read_text())
positive_text = compact(POSITIVE.read_text())
negative_text = compact(NEGATIVE.read_text())
expected_dispatch = (
    'returnwhenmethod:"add"->"set"'
    '"put"|"get_or_insert"->"dict"'
    '_->"darray"'
)
if expected_dispatch not in source_text:
    raise SystemExit("production growth-family helper no longer matches its exact pattern table")
pattern_arms = source_text.count("->") - source_text.count("->sview")
if pattern_arms != 3:
    raise SystemExit("production growth-family helper has extra or missing pattern arms")
contract_clauses = (
    'ensure(result=="set")== (method=="add")',
    'ensure(result=="dict")== (method=="put"ormethod=="get_or_insert")',
    'ensure(result=="darray")== (method!="add"andmethod!="put"andmethod!="get_or_insert")',
)
# Whitespace is removed before checking so equivalent source formatting is accepted.
contract_clauses = tuple(clause.replace(" ", "") for clause in contract_clauses)
if any(source_text.count(clause) != 1 or positive_text.count(clause) != 1
       for clause in contract_clauses):
    raise SystemExit("production growth-family contract and proof specification have diverged")
if 'include"./semantic_api_growth_default_family.elisa"' not in caller_text:
    raise SystemExit("semantic API diagnostic formatter no longer imports the proved helper")
if "returnSemanticApiGrowthDefaultFamily::growth_default_family(method)" not in caller_text:
    raise SystemExit("semantic API wrapper no longer delegates to the proved mapping")
if 'growth_default_family(diagnostic.name)' not in caller_text:
    raise SystemExit("container-growth diagnostic no longer uses the proved method mapping")
for proof in (POSITIVE, NEGATIVE):
    if 'include"../../src/semantic/semantic_api_growth_default_family.elisa"' not in compact(proof.read_text()):
        raise SystemExit(f"{proof.name} no longer includes the production helper")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("growth-family mapping proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, CALLER])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POSITIVE, NEGATIVE, SOURCE, CALLER, *source_closure,
]
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
assert positive == run(POSITIVE)[1], "growth-family report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {
    "growth_default_family",
    "source_mapping_is_exact",
    "known_growth_methods_map_to_their_families",
    "other_methods_use_the_darray_fallback",
} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert {row["name"] for row in negative["findings"]} == {
    "add_is_not_a_dictionary_growth_method",
    "unknown_methods_do_not_become_sets",
}
assert all(row["kind"] == "ensure-unproven" and row["status"] == "disproved" and
           row["counterexample_found"] for row in negative["findings"])
negative_verified = {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert "growth_default_family" in negative_verified
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact container growth method mapping used in semantic diagnostics",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": ["add_is_not_a_dictionary_growth_method", "unknown_methods_do_not_become_sets"],
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
