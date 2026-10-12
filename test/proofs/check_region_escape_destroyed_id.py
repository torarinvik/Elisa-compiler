"""Source-bind and replay the destroyed-region binding-ID membership refinement."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "region_escape_destroyed_id.elisa"
NEGATIVE = HERE / "region_escape_destroyed_id_rejected.elisa"
SOURCE = ROOT / "src/semantic/check_destroyed_region.elisa"
INTEGRATION = ROOT / "src/semantic/semantic.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")
if not MANIFEST.is_file():
    raise SystemExit(f"missing proof build manifest: {MANIFEST}")

source = SOURCE.read_text()
integration = INTEGRATION.read_text()
positive_text = POSITIVE.read_text()


def compact(text: str) -> str:
    return "".join(text.split())


def function_body(text: str, name: str) -> str:
    try:
        return text.split(f"def {name}(", 1)[1].split("\n        def ", 1)[0]
    except IndexError as error:
        raise SystemExit(f"missing production function {name}") from error


for name, value in (
    ("NO_REGION_BINDING", "0"),
    ("DESTROYED_REGION_ALL", "0"),
    ("UNKNOWN_REGION_DEPENDENCY", "4294967293"),
):
    if f"const {name}: u32 = {value}" not in source:
        raise SystemExit(f"production destroyed-region sentinel changed: {name}")

production = compact("def destroyed_region_id_contains(" + function_body(source, "destroyed_region_id_contains"))
for fragment in (
    "false return if candidate == NO_REGION_BINDING",
    "true return if candidate == UNKNOWN_REGION_DEPENDENCY and regions.count > 0",
    "for region in regions:",
    "true return if region == candidate or region == DESTROYED_REGION_ALL",
    "return false",
):
    if compact(fragment) not in production:
        raise SystemExit(f"production invalidation predicate changed without updating its proof: {fragment}")
if 'include "./check_destroyed_region.elisa"' not in integration:
    raise SystemExit("semantic integration no longer includes the destroyed-region predicate")
for caller in (
    "destroyed_mark_region_binding",
    "destroyed_region_of_statement",
    "destroyed_region_of_expression",
):
    if f"def {caller}(" not in source:
        raise SystemExit(f"destroyed-region proof integration lost caller {caller}")
if source.count("destroyed_region_id_contains(") < 7:
    raise SystemExit("destroyed-region predicate no longer feeds its downstream safety checks")

positive_names = {
    "proof_destroyed_region_member_from",
    "proof_destroyed_region_id_reference",
    "proof_destroyed_region_id_model",
    "no_region_binding_is_never_reported_destroyed",
    "unknown_dependency_with_any_nonempty_set_fails_closed",
    "matching_binding_id_is_reported_destroyed",
    "all_region_marker_invalidates_nonzero_binding",
    "unmatched_nonzero_binding_is_not_reported_destroyed",
}
for name in positive_names:
    if f"def {name}(" not in positive_text:
        raise SystemExit(f"destroyed-region proof is missing declaration {name}")
for fragment in (
    "decreases regions.count - index",
    "invariant index <= regions.count",
    "invariant proof_destroyed_region_member_from(regions, candidate, index) == proof_destroyed_region_member_from(regions, candidate, 0)",
    "ensure result == proof_destroyed_region_id_reference(regions, candidate)",
):
    if fragment not in positive_text:
        raise SystemExit(f"destroyed-region proof lost its loop-refinement obligation: {fragment}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("destroyed-region membership proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [*source_include_closure([POSITIVE, NEGATIVE]), BIN, MANIFEST, MANIFEST_CHECKSUM,
          PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance, Path(__file__),
          HERE / "proof_product_gate.py", SOURCE, INTEGRATION, POSITIVE, NEGATIVE]
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
assert positive == run(POSITIVE)[1], "destroyed-region proof report changed across identical runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + 3 == negative["summary"]["obligations"]
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "no_region_binding_is_reported_destroyed"),
    ("ensure-unproven", "empty_unknown_dependency_is_reported_destroyed"),
    ("ensure-unproven", "unmatched_nonzero_binding_is_reported_destroyed"),
]

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest, "proof product provenance changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "all-input refinement of destroyed-region binding-ID invalidation, including no-binding, unknown-dependency, exact-match, and global-invalidation sentinels",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [row["name"] for row in negative["findings"]],
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
