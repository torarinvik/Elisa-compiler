"""Admit source-linked endpoint laws for the contradictory-requires interval analyzer."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
ANALYZER = ROOT / "src/semantic/check_requires_contradictory.elisa"
POSITIVE = HERE / "requires_interval_extrema.elisa"
NEGATIVE = HERE / "requires_interval_extrema_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


analyzer_text = ANALYZER.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
expected_bodies = {
    "rc_max": "return a if a > b else b",
    "rc_min": "return a if a < b else b",
}
for name, body in expected_bodies.items():
    section = function_section(analyzer_text, name)
    if body not in section:
        raise SystemExit(f"production {name} changed; review and update its endpoint proof")
    proof_model = function_section(positive_text, f"proof_{name}")
    if body not in proof_model:
        raise SystemExit(f"proof model for {name} no longer mirrors the production branch")
try:
    apply_atom = function_section(analyzer_text, "rc_apply_atom")
except SystemExit as error:
    raise SystemExit("contradictory-requires interval update function is missing") from error
for fragment in (
    "los[index] <- rc_max(los[index], successor.value)",
    "los[index] <- rc_max(los[index], value) if operator == TokenKind.GtEq",
    "his[index] <- rc_min(his[index], predecessor.value)",
    "his[index] <- rc_min(his[index], value) if operator == TokenKind.LtEq",
    "los[index] <- rc_max(los[index], value) if operator == TokenKind.EqEq",
    "his[index] <- rc_min(his[index], value) if operator == TokenKind.EqEq",
):
    if fragment not in apply_atom:
        raise SystemExit("interval fact accumulation no longer uses the proved lower/upper endpoint operations")

positive_names = {
    "proof_rc_max", "proof_rc_min", "rc_min_is_lower_bound", "rc_max_is_upper_bound",
    "rc_min_selects_an_operand", "rc_max_selects_an_operand", "rc_min_is_commutative",
    "rc_max_is_commutative", "rc_min_is_idempotent", "rc_max_is_idempotent",
    "rc_min_precedes_rc_max", "rc_min_is_monotone_in_each_operand",
    "rc_max_is_monotone_in_each_operand",
}
negative_names = {"proof_rc_min", "proof_rc_max", "min_strictly_exceeds_left_is_refused",
                  "max_strictly_precedes_right_is_refused"}
if set(re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_text, re.MULTILINE)) != positive_names:
    raise SystemExit("positive endpoint proof contains a missing or unreviewed theorem")
if set(re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", negative_text, re.MULTILINE)) != negative_names:
    raise SystemExit("negative endpoint controls contain a missing or unreviewed claim")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("interval endpoint proofs require a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
    stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    ANALYZER, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE, ANALYZER]),
]))
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
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 28
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "endpoint theorem report changed across identical runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert verified == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(negative_names)
assert negative["summary"]["obligations"] == 10 and negative["summary"]["proven"] == 8
assert [(row["kind"], row["status"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "unknown", "min_strictly_exceeds_left_is_refused"),
    ("ensure-unproven", "unknown", "max_strictly_precedes_right_is_refused"),
]
assert not {"min_strictly_exceeds_left_is_refused", "max_strictly_precedes_right_is_refused"} & {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "int64 endpoint min/max bounds, selection, order, commutativity, idempotence and monotonicity",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names - {"proof_rc_min", "proof_rc_max"}),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
