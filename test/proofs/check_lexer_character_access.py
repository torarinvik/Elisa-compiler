"""Replay the source-linked proofs for the lexer's bounded character accessor."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import textwrap

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "lexer_character_access.elisa"
NEGATIVE = HERE / "lexer_character_access_rejected.elisa"
HELPER = ROOT / "src/lexer/lexer_character_access.elisa"
STRINGS = ROOT / "src/lexer/lexer_strings.elisa"
FACADE = ROOT / "src/lexer/lexer.elisa"
FALSE_CLAIM_TACTIC = HERE / "lexer_character_access_false_claim.json"

if not __debug__:
    raise SystemExit("run without Python -O")


helper_text = HELPER.read_text()
strings_text = STRINGS.read_text()
facade_text = FACADE.read_text()
if 'include "../../src/lexer/lexer_character_access.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer includes the production byte selectors")
if 'include "./lexer_character_access.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative control no longer includes the positive source-linked proofs")
if 'include "./lexer_character_access.elisa"' not in facade_text:
    raise SystemExit("lexer facade no longer includes the proved byte selectors")
if 'include "./lexer_strings.elisa"' not in facade_text:
    raise SystemExit("lexer facade no longer includes the checked character accessor")

char_at_body = strings_text.split(
    "def char_at(source: u8&, source_length: usize, index: usize) -> char:", 1
)[1].split(
    "def current_char(", 1
)[0].split("@inline(always)", 1)[0]
current_char_body = strings_text.split("def current_char(lexer: Lexer&", 1)[1].split(
    "def match_char(", 1
)[0]
guard = "if index < source_length:"
guarded_read = "byte: u8 = source[index]"
in_range_call = "return lexer_byte_if_in_range(byte, source_length, index).char()"
out_of_range_call = "return lexer_sentinel_if_out_of_range(NULL_CHAR, source_length, index).char()"
expected_char_at = "\n".join((
    guard,
    f"    {guarded_read}",
    f"    {in_range_call}",
    out_of_range_call,
))
if textwrap.dedent(char_at_body).strip() != expected_char_at:
    raise SystemExit("Lexer.char_at no longer has the exact guarded-read and proved-return branches")
if char_at_body.count("source[") != 1:
    raise SystemExit("Lexer.char_at gained an additional source load outside the audited guard")
if "return char_at(lexer.source, lexer.source_length, lexer.position)" not in current_char_body:
    raise SystemExit("Lexer.current_char no longer delegates to the checked character accessor")
in_range_helper = helper_text.split("def lexer_byte_if_in_range(", 1)[1].split(
    "@inline(always)", 1
)[0]
out_of_range_helper = helper_text.split("def lexer_sentinel_if_out_of_range(", 1)[1]
if not all(fragment in in_range_helper for fragment in (
    "requires index < source_length", "ensure result == byte", "return byte")):
    raise SystemExit("in-range byte selector no longer has its proved bounded identity contract")
if not all(fragment in out_of_range_helper for fragment in (
    "requires index >= source_length", "ensure result == sentinel", "return sentinel")):
    raise SystemExit("out-of-range selector no longer has its proved sentinel contract")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("lexer character-access proof requires a strict proof build")

compiler = manifest["compiler"]
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if compiler_head != compiler["source_revision"]:
    raise SystemExit("proof product compiler revision does not match the checked-out compiler HEAD")

stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    MANIFEST,
    MANIFEST_CHECKSUM,
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    HELPER,
    STRINGS,
    FACADE,
    FALSE_CLAIM_TACTIC,
    *source_include_closure([POSITIVE, NEGATIVE, FACADE, STRINGS]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["semantic_diagnostics"], report["semantic_diagnostics"]
    assert not report["trust"]["trusted_assumptions"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == 5
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 13
assert positive["replay"] == {"certificates": 13, "replayed": 13, "gaps": 0}
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "positive proof report changed across identical runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
expected = {
    "lexer_byte_if_in_range",
    "lexer_sentinel_if_out_of_range",
    "exactly_at_source_end_returns_the_sentinel",
    "past_source_end_returns_the_sentinel",
    "in_range_access_preserves_the_selected_byte",
}
assert verified == expected
summary_goals = [goal for goal in positive["goals"] if goal["dependencies"]]
assert [goal["name"] for goal in summary_goals] == [
    "exactly_at_source_end_returns_the_sentinel",
    "past_source_end_returns_the_sentinel",
    "in_range_access_preserves_the_selected_byte",
]
expected_dependencies = [
    "lexer_sentinel_if_out_of_range",
    "lexer_sentinel_if_out_of_range",
    "lexer_byte_if_in_range",
]
assert all(goal["proven"] and goal["replay_status"] == "replayed" and
           goal["dependencies_complete"] and len(goal["dependencies"]) == 1 and
           goal["dependencies"][0]["kind"] == "function-summary" and
           goal["dependencies"][0]["name"] == dependency
           for goal, dependency in zip(summary_goals, expected_dependencies, strict=True))

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] == 16
assert negative["summary"]["proven"] == 15 and negative["summary"]["unproven"] == 1
assert negative["replay"] == {"certificates": 15, "replayed": 15, "gaps": 0}
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "out_of_range_access_returns_a_non_sentinel_byte")]
false_goal = next(goal for goal in negative["goals"]
                  if goal["name"] == "out_of_range_access_returns_a_non_sentinel_byte")
assert false_goal["goal_id"] == 15 and false_goal["replay_status"] == "not_certified"
assert not false_goal["proven"] and false_goal["dependencies_complete"]

tactic_source = json.loads(FALSE_CLAIM_TACTIC.read_text())
assert tactic_source["format"] == "elisa-proof-tactics-v1"
assert tactic_source["target"] == {"goal_id": false_goal["goal_id"]}
assert tactic_source["actions"] == [{"action": "decide"}]
process = subprocess.run([str(BIN), "--tactics", str(FALSE_CLAIM_TACTIC), str(NEGATIVE)],
                         capture_output=True, text=True, timeout=60)
tactic_result = json.loads(process.stdout)
assert tactic_result["format"] == "elisa-proof-tactic-result-v1"
assert tactic_result["admission_scope"] == "target"
assert tactic_result["source_goal_binding"]["bound"]
assert tactic_result["source_goal_binding"]["goal_id"] == false_goal["goal_id"]
assert tactic_result["source_goal_binding"]["fingerprint_match"]
assert tactic_result["tactic"]["status"] == "failed"
assert not tactic_result["tactic"]["solved"]
assert not tactic_result["tactic"]["kernel_replayed"]
assert not tactic_result["tactic"]["certificate_replayed"]
assert tactic_result["source_goal_binding"]["previously_proven"] is False
assert tactic_result == json.loads(subprocess.run(
    [str(BIN), "--tactics", str(FALSE_CLAIM_TACTIC), str(NEGATIVE)],
    capture_output=True, text=True, timeout=60).stdout), "false-claim tactic result changed"

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
assert subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                      capture_output=True, text=True).stdout.strip() == compiler_head, \
    "compiler HEAD changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "proof_status": positive["status"],
    "positive_obligations": positive["summary"]["obligations"],
    "positive_replayed_certificates": positive["replay"]["replayed"],
    "replay_gaps": 0,
    "scope": "byte selection in range, at EOF, and beyond EOF; char_at guarded-load integration",
    "false_claim_rejected": "out_of_range_access_returns_a_non_sentinel_byte",
    "false_claim_tactic_rejected": True,
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "compiler_source_tree_sha256": compiler.get("source_tree_sha256"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
