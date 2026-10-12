"""Admit the source-linked proof of the semantic self-assignment policy."""
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
POLICY = ROOT / "src/semantic/self_assignment_policy.elisa"
CHECK = ROOT / "src/semantic/check_self_assignment.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
TOKENS = ROOT / "src/lexer/tokens.elisa"
TOKEN_PROJECTION = HERE / "parser_token_kind_projection.elisa"
POSITIVE = HERE / "self_assignment_policy.elisa"
NEGATIVE = HERE / "self_assignment_policy_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
PROOF_TIMEOUT_SECONDS = 120

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*def {re.escape(name)}\([^\n]*\n(.*?)(?=^\s*def |\Z)", text, re.DOTALL)
    if not match:
        raise SystemExit(f"missing source function {name}")
    return match.group(1)


def validate_policy(text: str) -> None:
    operator_function = compact(function_section(text, "is_mutation_operator"))
    operator_contract = compact("ensure result == (operator == Lexer::TokenKind.LArrow)")
    operator_body = compact(
        "matches: bool = when operator: Lexer::TokenKind.LArrow -> true _ -> false "
        "assert(matches == (operator == Lexer::TokenKind.LArrow)) return matches"
    )
    if operator_contract not in operator_function or operator_body not in operator_function:
        raise SystemExit("production mutation-operator classifier differs from its exact enum match")
    policy_function = compact(function_section(text, "should_report"))
    policy_body = compact(
        "report: bool = when operator: Lexer::TokenKind.LArrow -> target_name == value_name _ -> false "
        "assert(report == (operator == Lexer::TokenKind.LArrow and target_name == value_name)) return report"
    )
    if policy_body not in policy_function:
        raise SystemExit("production self-assignment policy differs from its proved name condition")


policy_text = POLICY.read_text()
validate_policy(policy_text)
check_text = CHECK.read_text()
if 'include "./self_assignment_policy.elisa"' not in check_text:
    raise SystemExit("semantic checker no longer imports the proved self-assignment policy")
if 'include "./check_self_assignment.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("self-assignment checker is no longer in the semantic pipeline")

statement_checker = compact(function_section(check_text, "check_self_assignment_statements"))
production_flow = compact(
    "Stmt.Assign(target, operator, value, line): match target: "
    "Expr.Ident(target_name, tl): match value: Expr.Ident(value_name, vl): "
    "table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.SelfAssignment, "
    "name: target_name, pos: tl, line: line.line, expected: \"\", actual: \"\"}) "
    "if SelfAssignmentPolicy::should_report(operator, target_name, value_name)"
)
if production_flow not in statement_checker:
    raise SystemExit("semantic diagnostic no longer applies the policy to two identifier operands")
if "operator == TokenKind.LArrow" in check_text or "target_name == value_name" in check_text:
    raise SystemExit("semantic diagnostic still contains an inline copy of the proved predicate")

token_text = TOKENS.read_text()
projection_text = TOKEN_PROJECTION.read_text()


def enum_variants(text: str) -> list[str]:
    match = re.search(r"(?ms)^\s*const enum TokenKind of u8:\n(.*?)(?=^\s*(?:struct|const enum|def) |\Z)", text)
    if not match:
        raise SystemExit("complete TokenKind enum projection is missing")
    return [line.strip() for line in match.group(1).splitlines()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", line.strip())]


if enum_variants(token_text) != enum_variants(projection_text):
    raise SystemExit("proof TokenKind projection differs from the production enum order")
if 'include "./parser_token_kind_projection.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer imports the complete TokenKind projection")
if 'include "../../src/semantic/self_assignment_policy.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer imports the production policy")
if 'include "./self_assignment_policy.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative claims no longer challenge the source-linked proof")

positive_names = {
    "source_operator_match_is_exact",
    "source_policy_matches_the_operator_and_name_condition",
    "mutation_of_the_same_name_is_reported",
    "mutation_of_a_different_name_is_not_reported",
    "a_new_binding_of_the_same_name_is_not_reported",
    "another_operator_on_the_same_name_is_not_reported",
}
negative_names = {
    "a_new_binding_of_the_same_name_is_reported",
    "mutation_of_a_different_name_is_reported",
    "another_operator_on_the_same_name_is_reported",
}
proof_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
for name in positive_names:
    if not re.search(rf"(?m)^def {re.escape(name)}\(", proof_text):
        raise SystemExit(f"positive proof is missing {name}")
for name in negative_names:
    if not re.search(rf"(?m)^def {re.escape(name)}\(", negative_text):
        raise SystemExit(f"negative proof is missing {name}")

mutations = (
    policy_text.replace("Lexer::TokenKind.LArrow", "Lexer::TokenKind.Assign", 1),
    policy_text.replace("target_name == value_name", "target_name != value_name", 1),
    policy_text.replace("_ -> false", "_ -> true", 1),
)
for mutated in mutations:
    try:
        validate_policy(mutated)
    except SystemExit:
        pass
    else:
        raise SystemExit("policy source mutation escaped the exact match checker")
mutated_callsite = check_text.replace(
    "SelfAssignmentPolicy::should_report(operator, target_name, value_name)",
    "target_name == value_name",
    1,
)
if production_flow in compact(function_section(mutated_callsite, "check_self_assignment_statements")):
    raise SystemExit("production call-site mutation fixture is ineffective")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("self-assignment proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, CHECK, SEMANTIC])
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", TOKENS, TOKEN_PROJECTION, *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["obligations"] == len(positive_names)
assert positive["summary"]["proven"] == len(positive_names)
assert not positive["findings"]
assert positive_names <= {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive == run(POSITIVE)[1], "self-assignment proof report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "self-assignment enum and identifier policy used by semantic diagnostics",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
