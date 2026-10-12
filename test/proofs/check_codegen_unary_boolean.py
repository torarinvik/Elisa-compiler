"""Admit the source-bound Boolean truth table for unary logical `not`."""
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
BACKEND = ROOT / "src/backend/codegen_expr_unary.elisa"
PARSER = ROOT / "src/parser/parser_expr_binary.elisa"
IDENTIFIERS = ROOT / "src/lexer/lexer_identifiers.elisa"
LEXER = ROOT / "src/lexer/lexer_tokens.elisa"
TOKENS = ROOT / "src/lexer/tokens.elisa"
POSITIVE = HERE / "codegen_unary_boolean.elisa"
NEGATIVE = HERE / "codegen_unary_boolean_rejected.elisa"
MODEL = HERE / "codegen_unary_boolean_model.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return "\n".join(line for line in source[start:end].splitlines()
                      if not line.lstrip().startswith("#"))


backend = compact(function_section(BACKEND.read_text(), "emit_expression_unary"))
bang = "ifunary_operator==TokenKind.Bang:"
logical_not = "ifunary_operator==TokenKind.Not:"
numeric_fallback = "operand_type:ValueType=resolve_type(unary_operand,expected,local_scope,fns,structs,generics)"
if not (bang in backend and logical_not in backend and numeric_fallback in backend and
        backend.index(bang) < backend.index(logical_not) < backend.index(numeric_fallback)):
    raise SystemExit("unary backend no longer keeps `!`, `not`, and numeric operators on distinct paths")

not_branch = backend[backend.index(logical_not):backend.index(numeric_fallback)]
backend_requirements = (
    "bool_type_n:ValueType=ValueType{kind:TypeKind.Bool,bits:1}",
    "emit_expression(unary_operand,bool_type_n,local_scope,fns,structs,generics,runtime,m,ctx,builder)",
    "LLVMBuildXor(builder,bool_operand,LLVMConstInt(LLVMInt1TypeInContext(ctx),1,0),\"not\")",
    "returnnull",
)
if any(requirement not in not_branch for requirement in backend_requirements):
    raise SystemExit("logical `not` must emit its operand as i1 and XOR it with the i1 constant one")
if not_branch.index(backend_requirements[0]) > not_branch.index(backend_requirements[1]) or not_branch.index(backend_requirements[1]) > not_branch.index(backend_requirements[2]):
    raise SystemExit("logical `not` operand typing and LLVM XOR emission order changed")

tokens = TOKENS.read_text()
enum = re.search(r"(?ms)^\s{8}const enum TokenKind of u8:\n(.*?)(?=^\s{8}struct Token:)", tokens)
if enum is None:
    raise SystemExit("could not locate the TokenKind declaration")
token_names = [line.strip() for line in enum.group(1).splitlines()
               if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", line.strip())]
if token_names.count("Not") != 1 or token_names.count("Bang") != 1 or token_names.index("Not") == token_names.index("Bang"):
    raise SystemExit("TokenKind must retain separate Not and Bang cases")

identifier_code = compact(function_section(IDENTIFIERS.read_text(), "frontend_lookup_keyword"))
if '"not"->TokenKind.Not' not in identifier_code:
    raise SystemExit("the `not` keyword no longer lexes as TokenKind.Not")

parser = compact(function_section(PARSER.read_text(), "unary_expression"))
parser_not = "ifkind==TokenKind.Not:rebindnot_token:Token,parser=parser.advance()"
parser_not_ast = "Ast::Expr.Unary(TokenKind.Not,not_operand,Ast::pos_of_token(not_token))"
parser_bang = "is_prefix:bool=kind==TokenKind.Bang"
parser_bang_ast = "Ast::Expr.Unary(operator_kind,operand,Ast::pos_of_token(token))"
if any(fragment not in parser for fragment in (parser_not, parser_not_ast, parser_bang, parser_bang_ast)):
    raise SystemExit("parser no longer constructs distinct Not and Bang unary AST nodes")

lexer = compact(LEXER.read_text())
bang_lexing = "lexer.eq_suffix_token(position,start,TokenKind.BangEq,TokenKind.Bang)"
if "'!'" not in lexer or bang_lexing not in lexer:
    raise SystemExit("the `!` punctuation token no longer remains distinct from keyword `not`")

positive_names = {
    "i1_xor_one_matches_logical_not",
    "lowering_not_false_produces_true",
    "lowering_not_true_produces_false",
}
negative_names = {
    "lowering_not_false_stays_false",
    "lowering_not_true_stays_true",
    "lowered_not_is_identity",
}


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


if declarations(POSITIVE) != positive_names or declarations(NEGATIVE) != negative_names:
    raise SystemExit("unary Boolean proof declaration inventory changed")
pointwise_code = compact(function_section(POSITIVE.read_text(), "i1_xor_one_matches_logical_not"))
if pointwise_code.count("(falseifvalueelsetrue)==(notvalue)") != 2:
    raise SystemExit("pointwise proof no longer checks XOR-one's result against logical `not` in both Boolean branches")
if "returnfalseiffalseelsetrue" not in compact(function_section(POSITIVE.read_text(), "lowering_not_false_produces_true")):
    raise SystemExit("false-input truth-table case changed")
if "ensureresult==false" not in compact(function_section(POSITIVE.read_text(), "lowering_not_true_produces_false")) or \
        "returnfalseiftrueelsetrue" not in compact(function_section(POSITIVE.read_text(), "lowering_not_true_produces_false")):
    raise SystemExit("true-input truth-table case changed")
model_code = compact(MODEL.read_text())
if "defcodegen_unary_model_i1_xor_one(value:bool)->bool:" not in model_code or \
        "returnfalseifvalueelsetrue" not in model_code:
    raise SystemExit("the formal Boolean model no longer states the i1 XOR-one truth table")
for path in (POSITIVE, NEGATIVE):
    if 'include "./codegen_unary_boolean_model.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} must include the source-bound i1 XOR model")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("unary Boolean proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", BACKEND, PARSER, IDENTIFIERS,
    LEXER, TOKENS, MODEL, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = replay(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["semantic_diagnostics"]
positive_declarations = positive_names | {"codegen_unary_model_i1_xor_one"}
assert positive_declarations == {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive == replay(POSITIVE)[1], "unary Boolean proof report changed across repeated runs"

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["failed"] == len(negative_names)
assert not negative["semantic_diagnostics"]
assert {finding["name"] for finding in negative["findings"]} == negative_names
assert all(finding["kind"] == "ensure-unproven" for finding in negative["findings"])
assert {"codegen_unary_model_i1_xor_one"}.issubset({row["name"] for row in negative["declaration_details"] if row.get("verified")})
assert negative_names.isdisjoint({row["name"] for row in negative["declaration_details"] if row.get("verified")})

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product, "proof product or pinned source tree changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "Boolean `not` parser-to-backend path and LLVM i1 XOR-one truth table",
    "positive_theorems": len(positive_names),
    "producer_proven": positive["summary"]["proven"],
    "independently_replayed": positive["replay"]["replayed"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
}, sort_keys=True))
