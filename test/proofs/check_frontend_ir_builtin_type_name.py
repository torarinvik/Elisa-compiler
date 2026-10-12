"""Admit source-linked proofs of the frontend IR builtin type classifier."""
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
source_text = HELPER.read_text()
proof_text = POSITIVE.read_text()


def match_names(block, description):
    arms = [line.strip() for line in block.splitlines() if line.strip()]
    if not arms or arms[-1] != "_ -> false":
        raise SystemExit(f"{description} lost its false fallback")
    found_names = []
    for arm in arms[:-1]:
        if not re.fullmatch(r'"[^"\\]+"(?:\s*\|\s*"[^"\\]+")*\s*->\s*true', arm):
            raise SystemExit(f"{description} contains a non-literal or non-true arm")
        found_names.extend(re.findall(r'"([^"\\]+)"', arm))
    if found_names != list(names):
        raise SystemExit(f"{description} arms differ from the ordered closed set")


def require_spec_match(text, description):
    match = re.search(
        r"ensure\s+result\s*==\s*\(\s*when\s+name:\s*\n(.*?)^\s*\)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise SystemExit(f"{description} must specify the closed set with pattern matching")
    match_names(match.group(1), description)


require_spec_match(source_text, "production classifier contract")
require_spec_match(proof_text, "proof contract")
classifier = re.search(
    r"(?m)^\s*def is_builtin_type_name\([^\n]*\n(.*?)(?=^\s*def |\Z)",
    source_text,
    re.DOTALL,
)
if not classifier:
    raise SystemExit("production builtin classifier is missing")
dispatch = re.search(
    r"return\s+when\s+name:\s*\n(.*)",
    classifier.group(1),
    re.DOTALL,
)
if not dispatch:
    raise SystemExit("production builtin classifier lost its exhaustive literal match")
match_names(dispatch.group(1), "production builtin match")
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
source_closure = source_include_closure([POSITIVE, NEGATIVE, WRITER, TYPE_WRITER])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    *source_closure,
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
