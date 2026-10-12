"""Admit source-bound proofs for postfix `else` and bracket-context classifiers."""
from __future__ import annotations

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
SOURCE = ROOT / "src/parser/parser_expr_postfix.elisa"
TOKENS = ROOT / "src/lexer/tokens.elisa"
POSITIVE = HERE / "parser_subscript_else_classification.elisa"
NEGATIVE = HERE / "parser_subscript_else_classification_rejected.elisa"

POSITIVE_SHAPES = {
    "recovery_classifier_is_exact": (
        "ensure result == (current_is_else and (is_transfer or (is_identifier and after_identifier_is_colon))) "
        "return current_is_else and (is_transfer or (is_identifier and after_identifier_is_colon))"
    ),
    "transfer_after_else_is_recovery": (
        "requires current_is_else and is_transfer ensure result == true "
        "return current_is_else and (is_transfer or (is_identifier and after_identifier_is_colon))"
    ),
    "identifier_colon_after_else_is_recovery": (
        "requires current_is_else and not is_transfer and is_identifier and after_identifier_is_colon "
        "ensure result == true "
        "return current_is_else and (is_transfer or (is_identifier and after_identifier_is_colon))"
    ),
    "identifier_without_colon_after_else_is_subscript_fallback": (
        "requires current_is_else and not is_transfer and is_identifier and not after_identifier_is_colon "
        "ensure result == false "
        "return current_is_else and (is_transfer or (is_identifier and after_identifier_is_colon))"
    ),
    "non_else_is_never_recovery": (
        "requires not current_is_else ensure result == false "
        "return current_is_else and (is_transfer or (is_identifier and after_identifier_is_colon))"
    ),
    "subscript_type_argument_classifier_is_exact": (
        "ensure result == (receiver_is_field and (is_cast or is_call_as)) "
        "return receiver_is_field and (is_cast or is_call_as)"
    ),
    "cast_field_uses_type_argument_context": (
        "requires receiver_is_field and is_cast ensure result == true "
        "return receiver_is_field and (is_cast or is_call_as)"
    ),
    "call_as_field_uses_type_argument_context": (
        "requires receiver_is_field and not is_cast and is_call_as ensure result == true "
        "return receiver_is_field and (is_cast or is_call_as)"
    ),
    "ordinary_field_stays_in_value_context": (
        "requires receiver_is_field and not is_cast and not is_call_as ensure result == false "
        "return receiver_is_field and (is_cast or is_call_as)"
    ),
    "non_field_receiver_stays_in_value_context": (
        "requires not receiver_is_field ensure result == false "
        "return receiver_is_field and (is_cast or is_call_as)"
    ),
}
NEGATIVE_SHAPES = {
    "false_claim_identifier_without_colon_is_recovery": (
        "requires current_is_else and not is_transfer and is_identifier and not after_identifier_is_colon "
        "ensure result == true "
        "return current_is_else and (is_transfer or (is_identifier and after_identifier_is_colon))"
    ),
    "false_claim_generic_field_uses_type_argument_context": (
        "requires receiver_is_field and not is_cast and not is_call_as "
        "ensure result == true "
        "return receiver_is_field and (is_cast or is_call_as)"
    ),
}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


source = SOURCE.read_text()
classifier = compact(function_section(source, "else_introduces_recovery_clause"))
type_classifier = compact(function_section(source, "subscript_base_is_type_argument"))
accept_else = compact(function_section(source, "accept_subscript_else"))
subscript = compact(function_section(source, "subscript_suffix"))
required_classifier = (
    "false return if parser.peek() != TokenKind.Else",
    "after: TokenKind = parser.peek_at(1)",
    "true return if after == TokenKind.Return or after == TokenKind.Raise or after == TokenKind.Break or after == TokenKind.Continue",
    "return after == TokenKind.Ident and parser.peek_at(2) == TokenKind.Colon",
)
classifier_positions = [classifier.find(compact(fragment)) for fragment in required_classifier]
if any(position < 0 for position in classifier_positions) or classifier_positions != sorted(classifier_positions):
    raise SystemExit("recovery `else` must recognize the four transfers, then only identifier-colon bindings")
if classifier.count("parser.peek_at(1)") != 1 or classifier.count("parser.peek_at(2)") != 1:
    raise SystemExit("recovery classification must use exactly the immediate and identifier-following token probes")

required_type_classifier = (
    "match active:",
    "Expr.Field(base_object,base_method,base_method_line):",
    "return when base_method:",
    '"cast" | "call_as" -> true',
    "_ -> false",
    "_:return false",
)
type_positions = [type_classifier.find(compact(fragment)) for fragment in required_type_classifier]
if any(position < 0 for position in type_positions) or type_positions != sorted(type_positions):
    raise SystemExit("only field selections named cast/call_as may enter type-argument context")
if set(re.findall(r'"([^"]*)"', type_classifier)) != {"cast", "call_as"}:
    raise SystemExit("the reinterpret method allowlist must remain closed")

required_accept = (
    "false return if parser.peek() != TokenKind.Else",
    "false return if parser.else_introduces_recovery_clause()",
    "parser, _ <- parser.advance()",
    "return true",
)
accept_positions = [accept_else.find(compact(fragment)) for fragment in required_accept]
if any(position < 0 for position in accept_positions) or accept_positions != sorted(accept_positions):
    raise SystemExit("subscript parsing may consume `else` only after the recovery classifier returns false")
if compact("rebind accepted_fallback: bool, parser = parser.accept_subscript_else()") not in subscript:
    raise SystemExit("single-index parsing must route its fallback through accept_subscript_else")
if compact("return (Ast::Expr.Binary(indexed, TokenKind.Else, fallback, Ast::pos_of_token(token)))") not in subscript:
    raise SystemExit("a consumed subscript fallback must remain represented in the returned AST")
if compact("parser.in_type_annotation <- true if subscript_base_is_type_argument(active)") not in subscript or \
        subscript.count("parser.in_type_annotation<-saved_type_annotation") != 3:
    raise SystemExit("type-argument context must follow the classifier and be restored on every bracket exit")

token_text = TOKENS.read_text()
enum_match = re.search(r"(?ms)^\s*const enum TokenKind of u8:\s*(.*?)(?=^\s*struct Token:|\Z)", token_text)
if enum_match is None:
    raise SystemExit("could not find the production TokenKind declaration")
token_variants = set(re.findall(r"(?m)^\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", enum_match.group(1)))
if not {"Else", "Break", "Continue", "Return", "Raise", "Ident", "Colon"} <= token_variants:
    raise SystemExit("the proof abstraction no longer maps to the required production token variants")

positive_names = set(POSITIVE_SHAPES)
negative_names = set(NEGATIVE_SHAPES)
if declarations(POSITIVE) != positive_names or declarations(NEGATIVE) != negative_names:
    raise SystemExit("subscript-else proof inventory is incomplete or contains extras")
for path, shapes in ((POSITIVE, POSITIVE_SHAPES), (NEGATIVE, NEGATIVE_SHAPES)):
    proof_text = path.read_text()
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(proof_text, name)):
            raise SystemExit(f"{name} no longer proves its intended classification")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("subscript-else proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    SOURCE,
    TOKENS,
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 20
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["obligations"] == 24 and negative["summary"]["proven"] == 22
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "source-bound postfix else ownership and closed bracket type-argument selection",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
