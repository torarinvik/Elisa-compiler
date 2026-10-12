"""Admit source-linked proofs of the compiler progress direction rules."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "progress_direction.elisa"
NEGATIVE = HERE / "progress_direction_rejected.elisa"
PROJECTION = HERE / "parser_token_kind_projection.elisa"
CLASSIFIER = ROOT / "src/driver/progress_direction.elisa"
PROGRESS = ROOT / "src/driver/elisac_emit_progress.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


classifier = compact(CLASSIFIER.read_text())
progress = compact(PROGRESS.read_text())
driver = compact(DRIVER.read_text())
positive = compact(POSITIVE.read_text())
negative = compact(NEGATIVE.read_text())
for fragment in (
    "constenumDirectionofu8:NoDirectionIncreaseDecrease",
    "returnwhenoperator:Lexer::TokenKind.Lt|Lexer::TokenKind.LtEq->Direction.IncreaseLexer::TokenKind.Gt|Lexer::TokenKind.GtEq->Direction.Decrease_->Direction.NoDirection",
    "returnwhendirection:Direction.Increase->operator==increase_operatorDirection.Decrease->operator==decrease_operator_->false",
    "ensureresult==(",
):
    if fragment not in classifier:
        raise SystemExit("production progress direction module lost its closed enum match or contract")
if 'include"./progress_direction.elisa"' not in progress:
    raise SystemExit("progress emitter no longer imports the proved direction classifier")
if "ProgressDirection::from_comparison_operator(pc_op)" not in progress:
    raise SystemExit("progress emitter no longer delegates comparison classification")
if progress.count("ProgressDirection::advances(") != 2:
    raise SystemExit("progress emitter no longer uses the proved update-direction rule at both sites")
if 'include"./elisac_emit_progress.elisa"' not in driver or "emit_progress_report(" not in driver:
    raise SystemExit("compiler driver no longer connects the proved progress rule to reporting")
if 'include"../../src/driver/progress_direction.elisa"' not in positive:
    raise SystemExit("positive proof no longer imports the production direction classifier")
if 'include"./progress_direction.elisa"' not in negative:
    raise SystemExit("negative claims no longer depend on the source-linked classifier proof")
for declaration in (
    "source_comparison_operator_mapping_is_exact",
    "all_loop_bound_comparisons_have_the_expected_direction",
    "unrelated_comparisons_have_no_progress_direction",
    "source_directional_update_rule_is_exact",
    "accepted_updates_match_their_bound_direction",
):
    if f"def{declaration}(" not in positive:
        raise SystemExit(f"positive proof lost {declaration}")
for fragment in (
    "ensureresult==(whenoperator:Lexer::TokenKind.Lt|Lexer::TokenKind.LtEq->ProgressDirection::Direction.IncreaseLexer::TokenKind.Gt|Lexer::TokenKind.GtEq->ProgressDirection::Direction.Decrease_->ProgressDirection::Direction.NoDirection)",
    "ensureresult==(whendirection:ProgressDirection::Direction.Increase->operator==increase_operatorProgressDirection::Direction.Decrease->operator==decrease_operator_->false)",
):
    if fragment not in positive:
        raise SystemExit("positive proof no longer states the production direction match exactly")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("progress direction proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, PROGRESS, DRIVER])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    PROJECTION, CLASSIFIER, PROGRESS, DRIVER, *source_closure,
]
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


code, proved = run(POSITIVE)
assert code == 0 and proved["status"] == proved["verification_state"] == "proved"
assert proved["summary"]["proven"] == proved["summary"]["obligations"]
assert not proved["findings"]
assert proved == run(POSITIVE)[1], "progress direction proof changed across repeated runs"
verified = {row["name"] for row in proved["declaration_details"] if row.get("verified")}
assert {
    "Direction",
    "from_comparison_operator",
    "advances",
    "source_comparison_operator_mapping_is_exact",
    "all_loop_bound_comparisons_have_the_expected_direction",
    "unrelated_comparisons_have_no_progress_direction",
    "source_directional_update_rule_is_exact",
    "accepted_updates_match_their_bound_direction",
} <= verified

code, rejected = run(NEGATIVE)
negative_names = {
    "less_than_must_not_mean_decrease",
    "addition_must_not_advance_a_decreasing_bound",
}
assert code == 1 and rejected["status"] == rejected["verification_state"] == "failed"
assert {row["name"] for row in rejected["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in rejected["findings"])
assert require_current_product(BIN, PROVER) == manifest
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "closed loop comparison and update direction rules used by -emit progress",
    "positive_obligations": proved["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
