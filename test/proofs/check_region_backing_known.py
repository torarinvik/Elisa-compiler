"""Source-bind the exact region-backing classifier contract and integration."""
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
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
COMPILER_PIN = PROVER / "ELISA_COMPILER_REV"
SOURCE = ROOT / "src/semantic/region_backing_known.elisa"
CONSUMER = ROOT / "src/semantic/check_region_backing.elisa"
INTEGRATION = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "region_backing_known.elisa"
NEGATIVE = HERE / "region_backing_known_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")
if not MANIFEST.is_file():
    raise SystemExit(f"missing proof build manifest: {MANIFEST}")


def compact(text: str) -> str:
    return "".join(text.split())


def function_body(text: str, name: str) -> str:
    try:
        return text.split(f"def {name}(", 1)[1].split("\n        def ", 1)[0]
    except IndexError as error:
        raise SystemExit(f"missing production function {name}") from error


source = SOURCE.read_text()
consumer = CONSUMER.read_text()
integration = INTEGRATION.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_body = """
def is_known(name: sview) -> bool can[Abort.Panic]:
    ensure result == (when name: "malloc" -> true "reserve_commit" -> true "fixed" -> true "chained" -> true "scratch" -> true _ -> false)
    return when name:
        "malloc" -> true
        "reserve_commit" -> true
        "fixed" -> true
        "chained" -> true
        "scratch" -> true
        _ -> false
"""
production = compact("def is_known(" + function_body(source, "is_known"))
if production != compact(expected_body):
    raise SystemExit("production strategy classifier or its exact-set contract changed")
if "module RegionBackingKnown:" not in source or "public:" not in source:
    raise SystemExit("region-backing classifier must remain a directly proofable public module")
if 'include "./region_backing_known.elisa"' not in integration or 'include "./check_region_backing.elisa"' not in integration:
    raise SystemExit("semantic integration lost the classifier or its consuming checker")
if integration.index('include "./region_backing_known.elisa"') > integration.index('include "./check_region_backing.elisa"'):
    raise SystemExit("region strategy classifier must be integrated before its consumer")
if compact('not RegionBackingKnown::is_known(annotation.owner)') not in compact(consumer):
    raise SystemExit("region checker no longer rejects strategies through the proved classifier")
if 'annotation.name == "__region_strategy"' not in consumer or "DiagnosticKind.UnknownRegionBacking" not in consumer:
    raise SystemExit("region strategy validation no longer reports parser-classified unknown names")
if "def region_backing_known(" in consumer:
    raise SystemExit("a duplicate private classifier could bypass the proved production helper")

positive_names = {
    "region_strategy_classifier_matches_its_complete_specification",
    "every_supported_region_strategy_is_recognized",
    "unsupported_examples_are_rejected",
    "classifier_is_case_sensitive",
}
negative_names = {
    "arbitrary_strategy_is_known",
    "supported_strategy_is_unknown",
    "classifier_ignores_case",
}
declarations = lambda text: set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", text))
if declarations(positive_text) != positive_names:
    raise SystemExit("positive classifier theorem inventory changed")
if declarations(negative_text) != negative_names:
    raise SystemExit("false classifier claim inventory changed")
if 'include "../../src/semantic/region_backing_known.elisa"' not in positive_text or \
        'include "../../src/semantic/region_backing_known.elisa"' not in negative_text:
    raise SystemExit("both proof files must include the exact production classifier")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("region strategy proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [*source_include_closure([POSITIVE, NEGATIVE]), BIN, MANIFEST, MANIFEST_CHECKSUM,
          COMPILER_PIN, stage1_product, stage1_provenance, Path(__file__),
          HERE / "proof_product_gate.py", SOURCE, CONSUMER, INTEGRATION, POSITIVE, NEGATIVE]
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
assert positive == run(POSITIVE)[1], "region strategy proof report changed across identical runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "arbitrary_strategy_is_known"),
    ("ensure-unproven", "supported_strategy_is_unknown"),
    ("ensure-unproven", "classifier_ignores_case"),
]
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest, "proof product provenance changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact finite accepted-set contract of the production region-backing classifier and semantic checker integration",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [row["name"] for row in negative["findings"]],
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
