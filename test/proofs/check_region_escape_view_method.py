"""Admit source-linked proofs of receiver methods that preserve region provenance."""
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
POSITIVE = HERE / "region_escape_view_method.elisa"
NEGATIVE = HERE / "region_escape_view_method_rejected.elisa"
HELPER = ROOT / "src/semantic/region_escape_view_method.elisa"
PROVENANCE = ROOT / "src/semantic/region_escape_provenance.elisa"
INTEGRATION = ROOT / "src/semantic/check_region_escape.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")

methods = ("as_sview", "as_cstr", "as_view", "as_slice", "as_str")
helper = HELPER.read_text()

def match_names(block: str, description: str) -> None:
    arms = [line.strip() for line in block.splitlines() if line.strip()]
    if len(arms) != 2 or arms[-1] != "_ -> false":
        raise SystemExit(f"{description} must have one literal arm and one false fallback")
    if not re.fullmatch(r'"[^"\\]+"(?:\s*\|\s*"[^"\\]+")*\s*->\s*true', arms[0]):
        raise SystemExit(f"{description} contains a non-literal or non-true arm")
    names = re.findall(r'"([^"\\]+)"', arms[0])
    if names != list(methods):
        raise SystemExit(f"{description} arms differ from the proved method set")


def extract_contract_match(text: str, description: str) -> str:
    match = re.search(
        r"ensure\s+result\s*==\s*\(\s*when\s+method:\s*\n(.*?)^\s*\)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise SystemExit(f"{description} must specify the closed method set with pattern matching")
    return match.group(1)


production_contract_match = extract_contract_match(helper, "production view-method contract")
proof_contract_match = extract_contract_match(POSITIVE.read_text(), "view-method proof contract")
match_names(production_contract_match, "production view-method contract")
match_names(proof_contract_match, "view-method proof contract")
body_match = re.search(
    r"(?m)^\s*return\s+when\s+method:\s*\n(.*?)(?=^\s*def\s|\Z)",
    helper,
    re.DOTALL,
)
if not body_match:
    raise SystemExit("production view-method classifier lost its exhaustive pattern match")
match_names(body_match.group(1), "production view-method implementation")

provenance = PROVENANCE.read_text()
if 'include "./region_escape_view_method.elisa"' not in provenance:
    raise SystemExit("region provenance module no longer imports the proved classifier")
for callsite in (
    "SemanticRegionEscapeViewMethod::is_view_method(method)",
    "SemanticRegionEscapeViewMethod::is_view_method(view_method)",
):
    if callsite not in provenance:
        raise SystemExit(f"region provenance no longer uses the proved classifier: {callsite}")
if 'include "./region_escape_provenance.elisa"' not in INTEGRATION.read_text():
    raise SystemExit("region escape checker no longer imports the provenance analysis")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("region view-method proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
          *source_include_closure([POSITIVE, NEGATIVE, INTEGRATION])]
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
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
expected = {
    "is_view_method",
    "source_classifier_has_exact_view_method_set",
    "every_region_view_method_is_recognized",
    "ordinary_or_unlisted_methods_do_not_propagate_receiver_region",
}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "ordinary_count_method_is_view"),
    ("ensure-unproven", "unlisted_view_method_is_borrowed"),
]
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact receiver-method whitelist for region alias provenance",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": ["ordinary_count_method_is_view", "unlisted_view_method_is_borrowed"],
    "sources_sha256": hashes_before,
}, sort_keys=True))
