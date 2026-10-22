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


def top_level_function(source: str, name: str) -> str:
    lines = source.splitlines()
    start = next((index for index, line in enumerate(lines)
                  if line.startswith(f"def {name}(")), None)
    if start is None:
        return ""
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end][0].isspace()):
        end += 1
    return compact("\n".join(lines[start:end]))


classifier = compact(CLASSIFIER.read_text())
progress_source = PROGRESS.read_text()
progress = compact(progress_source)
driver = compact(DRIVER.read_text())
positive = compact(POSITIVE.read_text())
negative = compact(NEGATIVE.read_text())
for fragment in (
    "constenumDirectionofu8:NoDirectionIncreaseDecrease",
    "returnwhenoperator:Lexer::TokenKind.Lt|Lexer::TokenKind.LtEq->Direction.IncreaseLexer::TokenKind.Gt|Lexer::TokenKind.GtEq->Direction.Decrease_->Direction.NoDirection",
    "returnwhendirection:Direction.Increase->operator==increase_operatorDirection.Decrease->operator==decrease_operator_->false",
    "defadvances_by_step(direction:Direction,operator:Lexer::TokenKind,step_direction:Direction,increase_operator:Lexer::TokenKind,decrease_operator:Lexer::TokenKind)->bool:",
    "returnfalseifstep_direction!=Direction.Increase",
    "ensureresult==(",
):
    if fragment not in classifier:
        raise SystemExit("production progress direction module lost its closed enum match or contract")
if 'include"./progress_direction.elisa"' not in progress:
    raise SystemExit("progress emitter no longer imports the proved direction classifier")
if "ProgressDirection::from_comparison_operator(pc_op)" not in progress:
    raise SystemExit("progress emitter no longer delegates comparison classification")
if progress.count("ProgressDirection::advances_by_step(direction,operator,step_direction,plus_operator,minus_operator)") != 1:
    raise SystemExit("progress emitter no longer delegates signed-step decisions to the proved rule")
if progress.count("returntrueifprogress_update_advances(direction,pb_operator,pb_value,") != 1 or progress.count("returntrueifprogress_update_advances(direction,pv_op,pv_right,") != 1:
    raise SystemExit("progress emitter no longer checks both compound and explicit updates through the signed-step rule")
explicit_update_gate = "continueifpb_operator!=Lexer::TokenKind.LArrow"
explicit_update_match = "ifpb_valueisExpr.Binary(pv_left,pv_op,pv_right,pv_line)"
if explicit_update_gate not in progress or progress.index(explicit_update_gate) > progress.index(explicit_update_match):
    raise SystemExit("progress emitter can reinterpret a compound assignment RHS as an explicit update")
expected_step_direction = compact("""
def progress_step_direction(expression: Ast::Expr) -> ProgressDirection::Direction:
    if expression is Expr.IntLit(step_value, _):
        return ProgressDirection::Direction.Increase if step_value > 0
    return ProgressDirection::Direction.NoDirection
""")
if top_level_function(progress_source, "progress_step_direction") != expected_step_direction:
    raise SystemExit("progress emitter step classifier is no longer closed to bare positive integer literals")
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
    "source_signed_step_update_rule_is_exact",
    "accepted_updates_match_their_bound_direction",
    "signed_steps_match_the_canonical_rule",
):
    if f"def{declaration}(" not in positive:
        raise SystemExit(f"positive proof lost {declaration}")
for fragment in (
    "ensurewhenoperator:Lexer::TokenKind.Lt|Lexer::TokenKind.LtEq->result==(ProgressDirection::Direction.Increase)Lexer::TokenKind.Gt|Lexer::TokenKind.GtEq->result==(ProgressDirection::Direction.Decrease)_->result==(ProgressDirection::Direction.NoDirection)",
    "ensurewhendirection:ProgressDirection::Direction.Increase->result==(operator==increase_operator)ProgressDirection::Direction.Decrease->result==(operator==decrease_operator)_->result==(false)",
    "ensureresult==((direction==ProgressDirection::Direction.Increaseandoperator==increase_operatorandstep_direction==ProgressDirection::Direction.Increase)or(direction==ProgressDirection::Direction.Decreaseandoperator==decrease_operatorandstep_direction==ProgressDirection::Direction.Increase))",
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
    "advances_by_step",
    "source_comparison_operator_mapping_is_exact",
    "all_loop_bound_comparisons_have_the_expected_direction",
    "unrelated_comparisons_have_no_progress_direction",
    "source_directional_update_rule_is_exact",
    "source_signed_step_update_rule_is_exact",
    "accepted_updates_match_their_bound_direction",
    "signed_steps_match_the_canonical_rule",
} <= verified

code, rejected = run(NEGATIVE)
negative_names = {
    "less_than_must_not_mean_decrease",
    "addition_must_not_advance_a_decreasing_bound",
    "zero_step_must_not_advance",
    "negative_step_must_not_advance_an_increasing_bound",
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
