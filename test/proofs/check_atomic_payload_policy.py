"""Bind the atomic payload AST-shape proof to the semantic diagnostic path."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


from source_guard_compat import expand_return_if_blocks
ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
SOURCE = ROOT / "src/semantic/atomic_payload_policy.elisa"
CONSUMER = ROOT / "src/semantic/check_atomic_payload.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
SEMANTIC_LATE_CHECKS = ROOT / "src/semantic/semantic_late_checks.elisa"
POSITIVE = HERE / "atomic_payload_policy.elisa"
NEGATIVE = HERE / "atomic_payload_policy_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking the proof product")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in expand_return_if_blocks(source).splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost )?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost )?def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*(?:ghost )?def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


source_text = SOURCE.read_text()
consumer_text = CONSUMER.read_text()
semantic_text = SEMANTIC.read_text()
semantic_late_checks_text = SEMANTIC_LATE_CHECKS.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_classifier = '''
def is_invalid_payload(payload: Ast::Expr, declared_struct_payload: bool) -> bool can[Abort.Panic]:
    ensure match payload:
        Ast::Expr.Ident(_, _): result == declared_struct_payload
        Ast::Expr.Index(_, _, _): result == true
        Ast::Expr.IndexN(_, _, _): result == true
        Ast::Expr.Tuple(_, _): result == true
        Ast::Expr.Unary(operator, _, _): result == (operator == TokenKind.Question)
        _: result == false
    can Abort.Panic:
        return match payload:
            Ast::Expr.Ident(_, _): declared_struct_payload
            Ast::Expr.Index(_, _, _): true
            Ast::Expr.IndexN(_, _, _): true
            Ast::Expr.Tuple(_, _): true
            Ast::Expr.Unary(operator, _, _): operator == TokenKind.Question
            _: false
'''
if "moduleSemanticAtomicPayloadPolicy:" not in compact(source_text):
    raise SystemExit("atomic payload policy moved outside its source-linked module")
if compact(function_section(source_text, "is_invalid_payload")) != compact(expected_classifier):
    raise SystemExit("atomic payload shape classifier changed without updating its proof contract")
if consumer_text.count('include "./atomic_payload_policy.elisa"') != 1:
    raise SystemExit("atomic semantic checker must include the proved payload policy exactly once")
consumer = compact(function_section(consumer_text, "check_atomic_annotation"))
head_gate = 'ifident_name_of(head)=="atomic"orident_name_of(head)=="AtomicSlot":'
struct_fact = "declared_struct_payload:bool=matchpayload:Expr.Ident(payload_name,payload_line):declared_struct_name(payload_name,table)_:false"
policy_call = "invalid:bool=SemanticAtomicPayloadPolicy::is_invalid_payload(payload,declared_struct_payload)"
diagnostic_gate = 'table.diagnostics<-table.diagnostics.push(Diagnostic{kind:DiagnosticKind.AtomicUnsafePayload,name:atomic_payload_name(payload),line:line,expected:"",actual:""})ifinvalid'
if any(fragment not in consumer for fragment in (head_gate, struct_fact, policy_call, diagnostic_gate)) or \
        not consumer.index(head_gate) < consumer.index(struct_fact) < consumer.index(policy_call) < consumer.index(diagnostic_gate):
    raise SystemExit("atomic checker no longer supplies the resolved-struct fact to the proved shape policy")
if semantic_text.count('include "./semantic_late_checks.elisa"') != 1 or \
        semantic_late_checks_text.count('include "./check_atomic_payload.elisa"') != 1:
    raise SystemExit("semantic root must load the atomic payload checker through late checks exactly once")
if 'include "../../src/parser/parser_tokens.elisa"' not in positive_text or \
        'include "../../src/semantic/atomic_payload_policy.elisa"' not in positive_text or \
        'include "./atomic_payload_policy.elisa"' not in negative_text:
    raise SystemExit("atomic payload proofs must import the production policy through their fixtures")

positive_names = {
    "classifier_matches_the_closed_ast_shape_spec",
    "declared_struct_identifiers_are_invalid_payloads",
    "indexed_and_tuple_payloads_are_invalid",
    "optional_payloads_are_invalid_and_mutable_payloads_are_not",
    "unrelated_payload_expressions_are_not_rejected_by_shape_policy",
}
negative_names = {
    "false_claim_declared_struct_is_a_valid_atomic_payload",
    "false_claim_index_payload_is_valid",
    "false_claim_optional_payload_is_valid",
}
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("atomic payload proof inventory changed")

positive_cases = {
    "classifier_matches_the_closed_ast_shape_spec": '''
def classifier_matches_the_closed_ast_shape_spec(payload: Expr, declared_struct_payload: bool) -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return match payload:
            Expr.Ident(_, _): (SemanticAtomicPayloadPolicy::is_invalid_payload(payload, declared_struct_payload)) == (declared_struct_payload)
            Expr.Index(_, _, _): (SemanticAtomicPayloadPolicy::is_invalid_payload(payload, declared_struct_payload)) == (true)
            Expr.IndexN(_, _, _): (SemanticAtomicPayloadPolicy::is_invalid_payload(payload, declared_struct_payload)) == (true)
            Expr.Tuple(_, _): (SemanticAtomicPayloadPolicy::is_invalid_payload(payload, declared_struct_payload)) == (true)
            Expr.Unary(operator, _, _): (SemanticAtomicPayloadPolicy::is_invalid_payload(payload, declared_struct_payload)) == (operator == TokenKind.Question)
            _: (SemanticAtomicPayloadPolicy::is_invalid_payload(payload, declared_struct_payload)) == (false)
''',
    "declared_struct_identifiers_are_invalid_payloads": '''
def declared_struct_identifiers_are_invalid_payloads() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticAtomicPayloadPolicy::is_invalid_payload(Expr.Ident("Record", ZERO_POS), true)
            and not SemanticAtomicPayloadPolicy::is_invalid_payload(Expr.Ident("i32", ZERO_POS), false)
''',
    "indexed_and_tuple_payloads_are_invalid": '''
def indexed_and_tuple_payloads_are_invalid() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticAtomicPayloadPolicy::is_invalid_payload(Expr.Index(Expr.Ident("items", ZERO_POS), Expr.IntLit(0, ZERO_POS), ZERO_POS), false)
            and SemanticAtomicPayloadPolicy::is_invalid_payload(Expr.IndexN(Expr.Ident("matrix", ZERO_POS), [Expr.IntLit(0, ZERO_POS)], ZERO_POS), false)
            and SemanticAtomicPayloadPolicy::is_invalid_payload(Expr.Tuple([Expr.IntLit(1, ZERO_POS)], ZERO_POS), false)
''',
    "optional_payloads_are_invalid_and_mutable_payloads_are_not": '''
def optional_payloads_are_invalid_and_mutable_payloads_are_not() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticAtomicPayloadPolicy::is_invalid_payload(Expr.Unary(TokenKind.Question, Expr.Ident("i32", ZERO_POS), ZERO_POS), false)
            and not SemanticAtomicPayloadPolicy::is_invalid_payload(Expr.Unary(TokenKind.Mutable, Expr.Ident("i32", ZERO_POS), ZERO_POS), false)
''',
    "unrelated_payload_expressions_are_not_rejected_by_shape_policy": '''
def unrelated_payload_expressions_are_not_rejected_by_shape_policy() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return not SemanticAtomicPayloadPolicy::is_invalid_payload(Expr.IntLit(32, ZERO_POS), false)
            and not SemanticAtomicPayloadPolicy::is_invalid_payload(Expr.Call(Expr.Ident("T", ZERO_POS), [], [], ZERO_POS), false)
''',
}
negative_cases = {
    "false_claim_declared_struct_is_a_valid_atomic_payload": '''
def false_claim_declared_struct_is_a_valid_atomic_payload() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return not SemanticAtomicPayloadPolicy::is_invalid_payload(Expr.Ident("Record", ZERO_POS), true)
''',
    "false_claim_index_payload_is_valid": '''
def false_claim_index_payload_is_valid() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return not SemanticAtomicPayloadPolicy::is_invalid_payload(Expr.Index(Expr.Ident("items", ZERO_POS), Expr.IntLit(0, ZERO_POS), ZERO_POS), false)
''',
    "false_claim_optional_payload_is_valid": '''
def false_claim_optional_payload_is_valid() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return not SemanticAtomicPayloadPolicy::is_invalid_payload(Expr.Unary(TokenKind.Question, Expr.Ident("i32", ZERO_POS), ZERO_POS), false)
''',
}
for name, expected in positive_cases.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"positive proof {name} changed without updating the source-bound gate")
for name, expected in negative_cases.items():
    if compact(function_section(negative_text, name)) != compact(expected):
        raise SystemExit(f"false-claim control {name} changed without updating the source-bound gate")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive": len(positive_names),
                      "false_claim_controls": len(negative_names)}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("atomic payload proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, CONSUMER, SEMANTIC,
    SEMANTIC_LATE_CHECKS,
    POSITIVE, NEGATIVE, *source_closure,
]))
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
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "atomic payload proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_after == hashes_before, "proof inputs changed during admission"
