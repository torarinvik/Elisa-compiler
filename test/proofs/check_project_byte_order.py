"""Replay source-linked properties for the project system's byte ordering."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
PROJECT = ROOT / "src/driver/project.elisa"
RESOLVE = ROOT / "src/driver/project_resolve.elisa"
REPORT = ROOT / "src/driver/project_report_text.elisa"
ABI_SCAN = ROOT / "src/driver/abi_lint_scan.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
POSITIVE = HERE / "project_byte_order.elisa"
NEGATIVE = HERE / "project_byte_order_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")

project_text = PROJECT.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
order_signature = "def bytes_less(left: darray[u8]&, right: darray[u8]&) -> bool:"
if order_signature not in project_text:
    raise SystemExit("production project byte comparator is missing")
order_body = project_text.split(order_signature, 1)[1].split("\n    def ", 1)[0]
for fragment in (
    "limit: usize = left.count if left.count < right.count else right.count",
    "for index in 0..<limit |left, right|",
    "true return if left[index] < right[index]",
    "false return if left[index] > right[index]",
    "return left.count < right.count",
):
    if fragment not in order_body:
        raise SystemExit(f"production byte comparator lost lexicographic step: {fragment}")
if 'include "../../src/driver/project.elisa"' not in positive_text or 'include "../../src/driver/project.elisa"' not in negative_text:
    raise SystemExit("byte-order proofs no longer include the production project system")
if 'include "./project.elisa"' not in DRIVER.read_text():
    raise SystemExit("compiler driver no longer imports the production project system")
if 'break if not bytes_less(right, left)' not in ABI_SCAN.read_text():
    raise SystemExit("ABI scan no longer uses the proved byte comparator")
if 'best <- index if bytes_less(project.targets[index].name, project.targets[best].name)' not in RESOLVE.read_text():
    raise SystemExit("project target selection no longer uses the proved byte comparator")
if 'bytes_less(project.targets[order[inner + 1.usize()]].name, project.targets[order[inner]].name)' not in REPORT.read_text():
    raise SystemExit("project report sorting no longer uses the proved byte comparator")

positive_names = {
    "singleton_bytes_use_unsigned_order",
    "first_differing_byte_decides_before_the_suffix",
    "equal_prefixes_compare_the_next_byte",
    "a_proper_byte_prefix_sorts_first",
    "equal_two_byte_strings_are_not_less",
}
for name in positive_names:
    if f"def {name}(" not in positive_text:
        raise SystemExit(f"positive byte-order theorem is missing: {name}")
negative_names = {
    "a_greater_single_byte_sorts_before_a_smaller_byte",
    "a_proper_byte_extension_sorts_before_its_prefix",
}
for name in negative_names:
    if f"def {name}(" not in negative_text:
        raise SystemExit(f"negative byte-order control is missing: {name}")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("project byte-order proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if compiler_head != product_manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, ABI_SCAN, RESOLVE, REPORT])
INPUTS = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py", DRIVER,
          *source_closure]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in INPUTS}


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
assert positive == run(POSITIVE)[1], "byte-order proof report changed across identical runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "a_greater_single_byte_sorts_before_a_smaller_byte"),
    ("ensure-unproven", "a_proper_byte_extension_sorts_before_its_prefix"),
]
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in INPUTS}
assert require_current_product(BIN, PROVER) == product_manifest
print(json.dumps({
    "admitted": True,
    "scope": "unsigned byte order, first-difference precedence, and proper-prefix ordering",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
