"""Bind declaration-position proofs to the sealed AST and production accessor."""
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
AST_SIDE_TABLES = ROOT / "src/parser/ast_side_tables.elisa"
TOKEN_POSITION = ROOT / "src/parser/parser_token_position.elisa"
POSITIVE = HERE / "ast_decl_position.elisa"
NEGATIVE = HERE / "ast_decl_position_rejected.elisa"

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
enum_start = ast_text.find("enum Decl is Node:")
enum_end = ast_text.find("enum Pattern is Node:", enum_start)
if enum_start < 0 or enum_end < 0:
    raise SystemExit("sealed AST declaration enum or its pattern boundary disappeared")
enum_block = ast_text[enum_start:enum_end]
variant_rows = []
for line in enum_block.splitlines():
    match = re.match(r"\s{8}([A-Z][A-Za-z0-9_]*)(?:\((.*)\))?\s*$", line)
    if match:
        fields = match.group(2)
        has_position = bool(fields) and fields.rsplit(",", 1)[-1].strip() == "pos: Pos"
        variant_rows.append((match.group(1), has_position))
variants = [name for name, _ in variant_rows]
if not variants or variants[0] != "Invalid" or \
        any(has_position != (name != "Invalid") for name, has_position in variant_rows):
    raise SystemExit("every concrete Decl variant must carry its own final Pos field")

decl_pos_source = function_section(AST_SIDE_TABLES.read_text(), "decl_pos")
match_markers = list(re.finditer(r"match declaration:", decl_pos_source))
if len(match_markers) != 2 or "ensure pos_equal(result, (match declaration:" not in decl_pos_source:
    raise SystemExit("Ast.decl_pos must pair its executable match with one exhaustive position contract")
contract_match = decl_pos_source[match_markers[0].start():match_markers[1].start()]
implementation_match = decl_pos_source[match_markers[1].start():]
contract_arms = re.findall(r"(?m)^[ \t]*Decl\.([A-Za-z][A-Za-z0-9_]*)\s*(?:\([^\n)]*\))?:", contract_match)
implementation_arms = re.findall(r"(?m)^[ \t]*Decl\.([A-Za-z][A-Za-z0-9_]*)\s*(?:\([^\n)]*\))?:", implementation_match)
if contract_arms != variants or implementation_arms != variants:
    raise SystemExit("Ast.decl_pos contract and implementation must each cover every sealed Decl constructor in declaration order")
for name, has_position in variant_rows:
    if has_position:
        contract_arm = re.search(rf"(?m)^[ \t]*Decl\.{re.escape(name)}\(([^)\n]*)\):[ \t]*([A-Za-z_][A-Za-z0-9_]*)\b", contract_match)
        implementation_arm = re.search(rf"(?m)^[ \t]*Decl\.{re.escape(name)}\(([^)\n]*)\):[ \t]*\n[ \t]*return[ \t]+([A-Za-z_][A-Za-z0-9_]*)\b", implementation_match)
        if not contract_arm or not implementation_arm:
            raise SystemExit(f"Ast.decl_pos contract and implementation must preserve Decl.{name}'s stored position")
        contract_fields = [part.strip() for part in contract_arm.group(1).split(",")]
        implementation_fields = [part.strip() for part in implementation_arm.group(1).split(",")]
        contract_value = contract_arm.group(2)
        implementation_value = implementation_arm.group(2)
        if (not contract_fields or not implementation_fields or
                contract_fields[-1] != contract_value or
                implementation_fields[-1] != implementation_value or
                contract_value != implementation_value or
                not contract_value.endswith("_pos")):
            raise SystemExit(f"Decl.{name} must return exactly its final stored Pos field")
    else:
        if compact("Decl.Invalid: pos_at_line(0)") not in compact(contract_match) or \
                compact("Decl.Invalid: pass") not in compact(implementation_match):
            raise SystemExit("Decl.Invalid must use the documented line-zero fallback position")
if compact("return pos_at_line(0)") not in compact(implementation_match) or \
        re.search(r"(?m)^[ \t]*_:", implementation_match):
    raise SystemExit("Ast.decl_pos fallback must remain explicit and the variant match must be exhaustive")

expected_pos_equal = """def pos_equal(left: Pos, right: Pos) -> bool:
    ensure result == (left.line == right.line and left.column == right.column and left.offset == right.offset and left.end_line == right.end_line and left.end_column == right.end_column and left.end_offset == right.end_offset)
    return left.line == right.line and left.column == right.column and left.offset == right.offset and left.end_line == right.end_line and left.end_column == right.end_column and left.end_offset == right.end_offset"""
if compact(function_section(ast_text, "pos_equal")) != compact(expected_pos_equal):
    raise SystemExit("Ast.pos_equal must compare every start and end coordinate field")
token_position_text = TOKEN_POSITION.read_text()
expected_pos_at_line = """def pos_at_line(line: u32) -> Pos:
            ensure result.line == line
            ensure result.column == 0
            ensure result.offset == 0
            ensure result.end_line == line
            ensure result.end_column == 0
            ensure result.end_offset == 0
            return Pos{line: line, column: 0, offset: 0, end_line: line, end_column: 0, end_offset: 0}"""
if compact(function_section(token_position_text, "pos_at_line")) != compact(expected_pos_at_line):
    raise SystemExit("the declaration sentinel relies on the exact pos_at_line coordinate contract")

positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
if 'include "../../src/parser/parser_tokens.elisa"' not in positive_text:
    raise SystemExit("positive declaration-position proof must import the production AST modules")
if 'include "./ast_decl_position.elisa"' not in negative_text:
    raise SystemExit("negative control must reuse the same source-linked declaration-position contract")

POSITIVE_NAMES = {"decl_pos_matches_the_owned_span_for_every_variant"}
NEGATIVE_NAMES = {"false_claim_import_declaration_position_is_zero"}
if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("declaration-position proof declaration inventory changed")

theorem = function_section(positive_text, "decl_pos_matches_the_owned_span_for_every_variant")
proof_arms = re.findall(r"(?m)^[ \t]*Decl\.([A-Za-z][A-Za-z0-9_]*)\s*(?:\([^\n)]*\))?:", theorem)
if proof_arms != variants or "Ast::decl_pos(declaration)" not in theorem:
    raise SystemExit("universal declaration-position theorem must cover every Decl constructor and call Ast.decl_pos")
for name, has_position in variant_rows:
    if has_position:
        expected_arm = rf"(?m)^[ \t]*Decl\.{re.escape(name)}\([^\n)]*,[ \t]*node_pos\):[ \t]*\n[ \t]*return Ast::pos_equal\(actual,[ \t]*node_pos\)"
    else:
        expected_arm = rf"(?m)^[ \t]*Decl\.{re.escape(name)}:[ \t]*\n[ \t]*return Ast::pos_equal\(actual,[ \t]*Ast::pos_at_line\(0\)\)"
    if not re.search(expected_arm, theorem):
        raise SystemExit(f"Decl.{name} proof arm does not state the payload-position contract")

expected_negative = """def false_claim_import_declaration_position_is_zero() -> bool:
    ensure result == true
    source_pos: Pos = Pos{line: 5, column: 3, offset: 12, end_line: 5, end_column: 9, end_offset: 18}
    declaration: Decl = Decl.Import(sview("module", 0, 6), source_pos)
    actual: Pos = Ast::decl_pos(declaration)
    return Ast::pos_equal(actual, Ast::pos_at_line(0))"""
if compact(function_section(negative_text, "false_claim_import_declaration_position_is_zero")) != compact(expected_negative):
    raise SystemExit("rejected control must falsely claim a concrete import declaration loses its position")

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
    AST_SIDE_TABLES,
    TOKEN_POSITION,
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
print(json.dumps({"admitted": True, "scope": "Ast.decl_pos is exhaustive and preserves every Decl payload position, with the zero-line fallback for Invalid", "positive": sorted(POSITIVE_NAMES), "false_claims_rejected": sorted(NEGATIVE_NAMES), "sources_sha256": hashes_before}, sort_keys=True))
