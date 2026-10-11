"""Admit source-linked proofs of the project system's exact suffix checks."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
PROJECT = ROOT / "src/driver/project.elisa"
RESOLVE = ROOT / "src/driver/project_resolve.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
POSITIVE = HERE / "project_suffix.elisa"
NEGATIVE = HERE / "project_suffix_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")

project_text = PROJECT.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
signature = "def bytes_ends_with_view(value: darray[u8]&, suffix: sview) -> bool:"
if signature not in project_text:
    raise SystemExit("production project suffix matcher is missing")
matcher_body = project_text.split(signature, 1)[1].split("\n    def ", 1)[0]
for fragment in (
    "ensure sview_len(suffix).i64() >= 0 or result == false",
    "want: i64 = sview_len(suffix).i64()",
    "false return if want < 0",
    "false return if value.count.i64() < want",
    "offset: usize = value.count - want.usize()",
    "for index in 0..<want |value, suffix, offset|",
    "false return if value[offset + index.usize()] != sview_at(suffix, index)",
    "return true",
):
    if fragment not in matcher_body:
        raise SystemExit(f"production suffix matcher lost a bounds or byte check: {fragment}")
if 'include "../../src/driver/project.elisa"' not in positive_text or 'include "../../src/driver/project.elisa"' not in negative_text:
    raise SystemExit("suffix proofs no longer include the production project system")
if 'include "./project.elisa"' not in DRIVER.read_text():
    raise SystemExit("compiler driver no longer imports the production project system")
resolve_text = RESOLVE.read_text()
for fragment in (
    'true return if bytes_ends_with_view(path, ".elisa")',
    'return bytes_ends_with_view(path, ".elisai")',
):
    if fragment not in resolve_text:
        raise SystemExit(f"surface-source classification no longer uses the proved suffix matcher: {fragment}")

positive_names = {
    "empty_suffix_matches_every_path",
    "a_path_shorter_than_elisa_cannot_match",
    "any_leading_byte_before_elisa_is_accepted",
    "elisa_suffix_match_depends_on_its_final_byte",
    "elisai_suffix_match_depends_on_its_final_byte",
    "an_earlier_suffix_byte_mismatch_is_rejected",
    "negative_length_suffix_views_never_match",
}
for name in positive_names:
    if f"def {name}(" not in positive_text:
        raise SystemExit(f"positive suffix theorem is missing: {name}")
negative_names = {
    "uppercase_elisa_suffix_is_accepted",
    "a_byte_after_elisa_does_not_prevent_a_match",
    "a_short_path_matches_elisa",
}
for name in negative_names:
    if f"def {name}(" not in negative_text:
        raise SystemExit(f"negative suffix control is missing: {name}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("project suffix proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py", POSITIVE,
          NEGATIVE, PROJECT, RESOLVE, DRIVER]
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
assert positive == run(POSITIVE)[1], "suffix proof report changed across identical runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "uppercase_elisa_suffix_is_accepted"),
    ("ensure-unproven", "a_byte_after_elisa_does_not_prevent_a_match"),
    ("ensure-unproven", "a_short_path_matches_elisa"),
]
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest
print(json.dumps({
    "admitted": True,
    "scope": "exact project path suffix matching and surface-source callsites",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
