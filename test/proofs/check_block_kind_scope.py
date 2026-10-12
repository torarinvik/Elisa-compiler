"""Admit source-linked proofs of semantic lexical-scope block classification."""
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
POSITIVE = HERE / "block_kind_scope.elisa"
NEGATIVE = HERE / "block_kind_scope_rejected.elisa"
HELPER = ROOT / "src/semantic/block_kind_scope.elisa"
INTEGRATION = ROOT / "src/semantic/resolve_flow.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")

names = ("region", "in", "can", "trusted", "with", "pool", "nursery", "scope", "lock")
match_contract = 'ensure result == (when kind: ' + ' | '.join(f'"{name}"' for name in names) + ' -> true _ -> false)'
compact_helper = "".join(HELPER.read_text().split())
compact_proof = "".join(POSITIVE.read_text().split())
if "".join(match_contract.split()) not in compact_helper or "".join(match_contract.split()) not in compact_proof:
    raise SystemExit("production classifier or proof lost the exact scope-block match contract")
if '"region"|"in"|"can"|"trusted"|"with"|"pool"|"nursery"|"scope"|"lock"->true' not in compact_helper:
    raise SystemExit("production classifier pattern set changed")
integration = INTEGRATION.read_text()
if 'include "./block_kind_scope.elisa"' not in integration:
    raise SystemExit("semantic resolver no longer includes the proved classifier")
if "SemanticBlockKindScope::block_kind_is_scope(kind)" not in integration:
    raise SystemExit("semantic resolver no longer uses the proved classifier")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("block-kind scope proof requires a strict proof build")

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
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
assert not positive["findings"]
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {"block_kind_is_scope", "source_classifier_matches_the_exact_scope_block_set",
        "every_scope_block_kind_is_recognized", "ordinary_control_blocks_are_not_scope_prefixes"} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "ordinary_if_block_must_introduce_a_scope")]
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}, \
    "proof inputs changed during replay"
print(json.dumps({"admitted": True,
                  "scope": "exact semantic block-kind set that introduces lexical scope",
                  "positive_obligations": positive["summary"]["proven"],
                  "false_claims_rejected": ["ordinary_if_block_must_introduce_a_scope"],
                  "sources_sha256": hashes_before}, sort_keys=True))
