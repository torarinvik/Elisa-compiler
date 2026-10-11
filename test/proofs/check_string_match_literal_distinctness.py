"""Admit exact proofs that string match arms keep numeric-looking literals distinct."""
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
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "string_match_literal_distinctness.elisa"
NEGATIVE = HERE / "string_match_literal_distinctness_rejected.elisa"
STMT_PATTERN_PARSER = ROOT / "src/parser/parser_stmt_pattern.elisa"
STMT_MATCH = ROOT / "src/backend/codegen_stmt_match.elisa"
STMT_MATCH_SCALAR = ROOT / "src/backend/codegen_stmt_match_scalar.elisa"
LITERAL_DECODE = ROOT / "src/backend/codegen_literals_decode.elisa"
SVIEW_EQUALITY = ROOT / "src/backend/codegen_expr_binary_tail.elisa"
PROOF_CHECK = PROVER / "src/proof/check.elisa"
PROOF_PATTERN_LOWERING = PROVER / "src/proof/check/pattern_lowering.elisa"
PROOF_RETURN_MATCHES = PROVER / "src/proof/check/returns/matches.elisa"
PROOF_REPLAY = PROVER / "src/proof/replay.elisa"
PROOF_REPLAY_PATTERN_FACTS = PROVER / "src/proof/replay/boundary_pattern_fact_sources.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")

positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
stmt_match_text = STMT_MATCH.read_text()
stmt_pattern_parser_text = STMT_PATTERN_PARSER.read_text()
stmt_match_scalar_text = STMT_MATCH_SCALAR.read_text()
literal_decode_text = LITERAL_DECODE.read_text()
sview_equality_text = SVIEW_EQUALITY.read_text()
proof_check_text = PROOF_CHECK.read_text()
proof_pattern_lowering_text = PROOF_PATTERN_LOWERING.read_text()
proof_return_matches_text = PROOF_RETURN_MATCHES.read_text()
proof_replay_text = PROOF_REPLAY.read_text()
proof_replay_pattern_facts_text = PROOF_REPLAY_PATTERN_FACTS.read_text()
if 'include "./string_match_literal_distinctness.elisa"' not in negative_text:
    raise SystemExit("negative control no longer imports the positive string-match proofs")
for spelling in ('"01"', '"1"'):
    if spelling not in positive_text or spelling not in negative_text:
        raise SystemExit(f"string-match fixture lost literal {spelling}")
positive_names = {
    "string_01_selects_its_exact_arm",
    "string_01_selects_its_exact_arm_when_second",
    "string_1_selects_its_exact_arm",
    "boolean_true_selects_its_exact_arm",
    "integer_one_selects_its_exact_arm",
}
for name in positive_names:
    if f"def {name}(" not in positive_text:
        raise SystemExit(f"positive string-match proof missing: {name}")

# Keep the proof fixtures on the statement-match path they claim to exercise. Checking
# function bodies prevents an if-expression rewrite from leaving the AST/backend guard green.
def compact_function(name: str) -> str:
    start = positive_text.find(f"def {name}(")
    if start < 0:
        raise SystemExit(f"positive string-match proof missing: {name}")
    end = positive_text.find("\ndef ", start + 1)
    body = positive_text[start:] if end < 0 else positive_text[start:end]
    return re.sub(r"\s+", " ", body)


expected_match_bodies = {
    "string_01_selects_its_exact_arm": 'match value: "01": return true "1": return false _:',
    "string_01_selects_its_exact_arm_when_second": 'match value: "1": return false "01": return true _:',
    "string_1_selects_its_exact_arm": 'match value: "01": return false "1": return true _:',
}
for name, expected in expected_match_bodies.items():
    if expected not in compact_function(name):
        raise SystemExit(f"{name} no longer proves the intended ordered statement-match arms")
if "def false_claim_string_1_selects_the_true_arm(" not in negative_text:
    raise SystemExit("false string-match claim missing")

if "TokenKind.StringLit" not in stmt_pattern_parser_text or \
        "lit_text: mutable sview = Lexer::text_or_empty(token, parser.source)" not in stmt_pattern_parser_text or \
        "return (Ast::Pattern.Literal(lit_text))" not in stmt_pattern_parser_text:
    raise SystemExit("statement-pattern parser no longer preserves literal payload text in Pattern.Literal")

# These proof fixtures use statement-form matches whose arms `return`. Tie them
# to that production lowering: Stmt.Match must reach the scalar sview matcher,
# which builds each literal's decoded byte length and compares through the same
# content-equality helper used by `sview ==`.
if "emit_statement_match_scalar(" not in stmt_match_text:
    raise SystemExit("statement-match dispatcher no longer routes scalar matches through its sview-aware path")
if "if sm_scrutinee_type.kind == TypeKind.SView" not in stmt_match_scalar_text or \
        "Pattern.Literal(sview_lit_text)" not in stmt_match_scalar_text:
    raise SystemExit("statement-match lowering no longer handles sview literal arms")
if "sview_lit_len: usize = sview_lit_storage.count - 1" not in stmt_match_scalar_text or \
        "sview_equality_callee(runtime, ctx, builder, structs.target.target_pointer_bits)" not in stmt_match_scalar_text:
    raise SystemExit("statement sview literal lowering no longer preserves decoded length and uses content equality")
if "LLVMBuildICmp(helper_builder, 32, left_length, right_length" not in sview_equality_text or \
        "LLVMBuildCall2(helper_builder, memcmp_type, memcmp_fn" not in sview_equality_text:
    raise SystemExit("sview equality helper no longer compares lengths and then literal bytes")

# The proof checker must model the same source-shaped Stmt.Match with authenticated direct
# string type information, then apply those typed facts during boundary replay.
if 'include "./check/pattern_lowering.elisa"' not in proof_check_text or \
        'include "./check/returns/matches.elisa"' not in proof_check_text:
    raise SystemExit("proof checker no longer wires in typed pattern and return-match analysis")
if 'include "./replay/boundary_pattern_fact_sources.elisa"' not in proof_replay_text:
    raise SystemExit("proof replay no longer wires in typed pattern boundary validation")
if "Ast::Stmt.Match(scrutinee, arms, match_position):" not in proof_return_matches_text or \
        "proof_pattern_condition_using_type(arm.pattern, scrutinee_value, match_position, pattern_type)" not in proof_return_matches_text:
    raise SystemExit("return proof checker no longer derives typed conditions for statement matches")
if "def proof_pattern_condition_typed(" not in proof_pattern_lowering_text or \
        '"sview" | "cstr" -> true' not in proof_pattern_lowering_text or \
        "proof_pattern_condition_typed(pattern, symbolic_scrutinee, position, type_expression)" not in proof_pattern_lowering_text:
    raise SystemExit("proof pattern lowering no longer turns directly typed string literals into equality conditions")
if "def proof_replay_control_pattern_type_is_direct_string(" not in proof_replay_pattern_facts_text or \
        "proof_replay_control_pattern_typed_payload_unambiguous(pattern, type_expression)" not in proof_replay_pattern_facts_text or \
        "proof_pattern_condition_typed(pattern, scrutinee, position, type_expression)" not in proof_replay_pattern_facts_text or \
        "proof_source_expression_has_overloaded_operator(expression, report.source_primitive_operator_mask, 0)" not in proof_replay_pattern_facts_text:
    raise SystemExit("boundary replay no longer constrains string-pattern facts to direct typed primitive equality")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("string-match literal proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != product_manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    STMT_PATTERN_PARSER,
    STMT_MATCH,
    STMT_MATCH_SCALAR,
    LITERAL_DECODE,
    SVIEW_EQUALITY,
    PROOF_CHECK,
    PROOF_PATTERN_LOWERING,
    PROOF_RETURN_MATCHES,
    PROOF_REPLAY,
    PROOF_REPLAY_PATTERN_FACTS,
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


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "positive string-match report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + 1 == negative["summary"]["obligations"]
assert negative == run(NEGATIVE)[1], "negative string-match report changed across repeated runs"
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "false_claim_string_1_selects_the_true_arm")
]
assert "false_claim_string_1_selects_the_true_arm" not in {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product_manifest
print(json.dumps({
    "admitted": True,
    "scope": "numeric-looking string patterns stay distinct while boolean/integer arms remain provable",
    "positive_obligations": positive["summary"]["proven"],
    "false_claim_rejected": "false_claim_string_1_selects_the_true_arm",
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
