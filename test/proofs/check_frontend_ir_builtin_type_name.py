"""Admit source-linked proofs of the frontend IR builtin type classifier."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
POSITIVE = HERE / "frontend_ir_builtin_type_name.elisa"
NEGATIVE = HERE / "frontend_ir_builtin_type_name_rejected.elisa"
HELPER = ROOT / "src/driver/frontend_ir_builtin_type_name.elisa"
WRITER = ROOT / "src/driver/frontend_ir_write.elisa"
TYPE_WRITER = ROOT / "src/driver/frontend_ir_types.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")

names = ("darray", "view", "sview", "dict", "set", "deque", "array", "slice", "optional")
predicate = " or ".join(f'name == "{name}"' for name in names)
contract = f"ensure result == ({predicate})"
source_text = HELPER.read_text()
proof_text = POSITIVE.read_text()
# Line wrapping and an outer grouping do not change the exact contract clauses.
compact_contract = "".join(contract.split())
def compact_source(text):
    # Preserve whitespace inside string literals: "da rray" is not "darray".
    compact = re.sub(r'"(?:\\.|[^"\\])*"|\s+',
                     lambda match: match.group(0) if match.group(0).startswith('"') else "",
                     text)
    return compact.replace("ensure(result", "ensureresult")

if compact_contract not in compact_source(source_text):
    raise SystemExit("production classifier contract is not the complete closed builtin set")
if compact_contract not in compact_source(proof_text):
    raise SystemExit("proof no longer states the complete production classifier contract")
if 'include "./frontend_ir_builtin_type_name.elisa"' not in WRITER.read_text():
    raise SystemExit("frontend IR writer no longer imports the classifier")
if "FrontendIrBuiltinTypeName::is_builtin_type_name(name)" not in TYPE_WRITER.read_text():
    raise SystemExit("type writer no longer uses the proved classifier")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("frontend IR classifier proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POSITIVE, NEGATIVE, HELPER, WRITER, TYPE_WRITER,
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
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
expected = {
    "is_builtin_type_name",
    "source_classifier_has_exact_builtin_set",
    "every_builtin_type_head_is_recognized",
    "nearby_named_types_remain_generic",
}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == {
    "array_must_remain_generic", "ordinary_type_must_be_builtin"
}
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "closed builtin-type classification used by frontend IR type writing",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": ["array_must_remain_generic", "ordinary_type_must_be_builtin"],
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
