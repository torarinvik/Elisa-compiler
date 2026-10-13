"""Bind expression-position proofs to the sealed AST and its production accessor."""
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
AST_NODES = ROOT / "src/parser/ast_nodes.elisa"
PARSER_TOKENS = ROOT / "src/parser/parser_tokens.elisa"
POSITIVE = HERE / "ast_expr_position.elisa"
NEGATIVE = HERE / "ast_expr_position_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


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


ast_text = AST_NODES.read_text()
enum_start = ast_text.find("enum Expr is Node:")
enum_end = ast_text.find("enum Stmt is Node:", enum_start)
if enum_start < 0 or enum_end < 0:
    raise SystemExit("sealed AST expression enum or its statement boundary disappeared")
enum_block = ast_text[enum_start:enum_end]
variant_rows = []
for line in enum_block.splitlines():
    match = re.match(r"\s{8}([A-Z][A-Za-z0-9_]*)(?:\((.*)\))?\s*$", line)
    if match:
        fields = match.group(2)
        has_position = bool(fields) and fields.rsplit(",", 1)[-1].strip() == "pos: Pos"
        variant_rows.append((match.group(1), has_position))
variants = [name for name, _ in variant_rows]
if not variants or variants[:2] != ["Invalid", "Absent"] or \
        any(has_position != (name not in {"Invalid", "Absent"}) for name, has_position in variant_rows):
    raise SystemExit("every non-sentinel Expr variant must carry its own final Pos field")

pos_equal_source = function_section(ast_text, "pos_equal")
expected_pos_equal = """def pos_equal(left: Pos, right: Pos) -> bool:
    ensure result == (left.line == right.line and left.column == right.column and left.offset == right.offset and left.end_line == right.end_line and left.end_column == right.end_column and left.end_offset == right.end_offset)
    return left.line == right.line and left.column == right.column and left.offset == right.offset and left.end_line == right.end_line and left.end_column == right.end_column and left.end_offset == right.end_offset"""
if compact(pos_equal_source) != compact(expected_pos_equal):
    raise SystemExit("Ast.pos_equal must compare every start and end coordinate field")

expr_pos_source = function_section(ast_text, "expr_pos")
match_markers = list(re.finditer(r"match expression:", expr_pos_source))
if len(match_markers) != 2 or "ensure pos_equal(result, (match expression:" not in expr_pos_source:
    raise SystemExit("Ast.expr_pos must pair its executable match with one exhaustive position contract")
contract_match = expr_pos_source[match_markers[0].start():match_markers[1].start()]
implementation_match = expr_pos_source[match_markers[1].start():]
contract_arms = re.findall(r"(?m)^[ \t]*Expr\.([A-Za-z][A-Za-z0-9_]*)\s*(?:\([^\n)]*\))?:", contract_match)
implementation_arms = re.findall(r"(?m)^[ \t]*Expr\.([A-Za-z][A-Za-z0-9_]*)\s*(?:\([^\n)]*\))?:", implementation_match)
if contract_arms != variants or implementation_arms != variants:
    raise SystemExit("Ast.expr_pos contract and implementation must each cover every sealed Expr constructor in declaration order")
zero_position = "Pos{line: 0, column: 0, offset: 0, end_line: 0, end_column: 0, end_offset: 0}"
for name, has_position in variant_rows:
    if has_position:
        contract_arm = re.search(
            rf"(?m)^[ \t]*Expr\.{re.escape(name)}\([^\n)]*,[ \t]*node_pos\):[ \t]*node_pos\b",
            contract_match,
        )
        implementation_arm = re.search(
            rf"(?m)^[ \t]*Expr\.{re.escape(name)}\([^\n)]*,[ \t]*node_pos\):[ \t]*\n[ \t]*return node_pos\b",
            implementation_match,
        )
        if not contract_arm or not implementation_arm:
            raise SystemExit(f"Ast.expr_pos contract and implementation must preserve Expr.{name}'s stored position")
    else:
        expected_spec = compact(f"Expr.{name}: {zero_position}")
        expected_body = compact(f"Expr.{name}: pass")
        if expected_spec not in compact(contract_match) or expected_body not in compact(implementation_match):
            raise SystemExit(f"Ast.expr_pos must use the zero position for positionless Expr.{name}")
zero_return = compact(f"return {zero_position}")
if compact(implementation_match).count(zero_return) != 1:
    raise SystemExit("Ast.expr_pos must use exactly one all-zero fallback for the two positionless sentinels")

positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
if 'include "../../src/parser/parser_tokens.elisa"' not in positive_text or \
        'include "../../src/parser/ast_nodes.elisa"' not in positive_text:
    raise SystemExit("positive position proof must import the production AST definitions")
if 'include "./ast_expr_position.elisa"' not in negative_text:
    raise SystemExit("negative control must reuse the same source-linked position model")

POSITIVE_NAMES = {"expr_pos_matches_the_owned_span_for_every_variant"}
NEGATIVE_NAMES = {"false_claim_integer_literal_position_is_discarded"}
if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("expression-position proof declaration inventory changed")

theorem = function_section(positive_text, "expr_pos_matches_the_owned_span_for_every_variant")
proof_arms = re.findall(r"(?m)^[ \t]*Expr\.([A-Za-z][A-Za-z0-9_]*)\s*(?:\([^\n)]*\))?:", theorem)
if proof_arms != variants:
    raise SystemExit("universal expression-position theorem must cover every current Expr variant")
if "Ast::expr_pos(expression)" not in theorem or "Ast::pos_equal(actual, node_pos)" not in theorem:
    raise SystemExit("universal expression-position theorem must compare the production accessor with each stored span")
for name, has_position in variant_rows:
    if has_position:
        expected_arm = rf"(?m)^[ \t]*Expr\.{re.escape(name)}\([^\n)]*,[ \t]*node_pos\):[ \t]*\n[ \t]*return Ast::pos_equal\(actual,[ \t]*node_pos\)"
    else:
        expected_arm = rf"(?m)^[ \t]*Expr\.{re.escape(name)}:[ \t]*\n[ \t]*return Ast::pos_equal\(actual,[ \t]*Pos\{{line: 0, column: 0, offset: 0, end_line: 0, end_column: 0, end_offset: 0\}}\)"
    if not re.search(expected_arm, theorem):
        raise SystemExit(f"Expr.{name} proof arm does not state the payload-position contract")

negative_claim = function_section(negative_text, "false_claim_integer_literal_position_is_discarded")
expected_negative_claim = """def false_claim_integer_literal_position_is_discarded() -> bool:
    ensure result == true
    source_pos: Pos = Pos{line: 7, column: 4, offset: 15, end_line: 7, end_column: 9, end_offset: 20}
    expression: Expr = Expr.IntLit(123, source_pos)
    actual: Pos = Ast::expr_pos(expression)
    return Ast::pos_equal(actual, Pos{line: 0, column: 0, offset: 0, end_line: 0, end_column: 0, end_offset: 0})"""
if compact(negative_claim) != compact(expected_negative_claim):
    raise SystemExit("rejected control must falsely claim a concrete literal loses its stored position")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error

inputs = [
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    Path(__file__),
    HERE / "proof_product_gate.py",
    AST_NODES,
    PARSER_TOKENS,
    POSITIVE,
    NEGATIVE,
]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
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
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + len(NEGATIVE_NAMES) == negative["summary"]["obligations"]
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in NEGATIVE_NAMES
}

assert require_current_product(BIN, PROVER) == product
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({"admitted": True, "scope": "Ast.expr_pos is exhaustive and preserves each Expr payload position, with zero reserved for Invalid and Absent", "positive": sorted(POSITIVE_NAMES), "false_claims_rejected": sorted(NEGATIVE_NAMES), "sources_sha256": hashes_before}, sort_keys=True))
