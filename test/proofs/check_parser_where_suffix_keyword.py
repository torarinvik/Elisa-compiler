"""Admit source-linked proofs of the parser's exact contextual `where` keyword."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
KEYWORD = ROOT / "src/parser/parser_where_suffix_keyword.elisa"
SUFFIX = ROOT / "src/parser/parser_expr_suffixes.elisa"
EXPR_LITERALS = ROOT / "src/parser/parser_expr_literals.elisa"
PARSER = ROOT / "src/parser/parser.elisa"
POSITIVE = HERE / "parser_where_suffix_keyword.elisa"
NEGATIVE = HERE / "parser_where_suffix_keyword_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^\s*def {re.escape(name)}\([^\n]*\n(.*?)(?=^\s*def |\Z)",
        source,
        re.DOTALL,
    )
    if not match:
        raise SystemExit(f"function missing: {name}")
    return match.group(1)


def function_statements(source: str, signature: str) -> list[str]:
    lines = source.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != signature:
            continue
        header_indent = len(line) - len(line.lstrip(" "))
        statements = []
        for body_line in lines[index + 1:]:
            if not body_line.strip() or body_line.lstrip().startswith("#"):
                continue
            indent = len(body_line) - len(body_line.lstrip(" "))
            if indent <= header_indent:
                break
            statements.append(body_line.strip())
        return statements
    raise SystemExit(f"function missing: {signature}")


def match_arms(block: str, description: str) -> None:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if lines != ['"where" -> true', "_ -> false"]:
        raise SystemExit(f"{description} differs from the exact case-sensitive keyword table")


def require_classifier(source: str, name: str, description: str, require_dispatch: bool = True) -> None:
    body = function_source(source, name)
    contract = re.search(
        r"ensure\s+result\s*==\s*\(\s*when\s+text:\s*\n(.*?)^\s*\)",
        body,
        re.DOTALL | re.MULTILINE,
    )
    if not contract:
        raise SystemExit(f"{description} no longer specifies its exact set with a pattern match")
    match_arms(contract.group(1), description + " contract")
    if require_dispatch:
        dispatch = re.search(r"return\s+when\s+text:\s*\n(.*)", body, re.DOTALL)
        if not dispatch:
            raise SystemExit(f"{description} no longer implements its exact set with a pattern match")
        match_arms(dispatch.group(1), description + " implementation")


keyword_text = KEYWORD.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
require_classifier(keyword_text, "is_where_keyword", "production contextual-keyword classifier")
require_classifier(
    positive_text,
    "source_where_keyword_classification_is_exact",
    "proof contextual-keyword classifier",
    require_dispatch=False,
)

if 'include "./parser_where_suffix_keyword.elisa"' not in SUFFIX.read_text():
    raise SystemExit("parser suffix module no longer imports the proved keyword classifier")
if 'include "./parser_expr_literals.elisa"' not in PARSER.read_text():
    raise SystemExit("parser root no longer imports the expression suffix consumer")
if 'include "./parser_expr_suffixes.elisa"' not in EXPR_LITERALS.read_text():
    raise SystemExit("expression parser no longer imports the suffix consumer")

signature = "def where_view_suffix(parser: lmut Parser, source: Ast::Expr) -> Ast::Expr:"
expected_prefix = [
    "source return if not parser.in_where_group",
    "where_token: Token = parser.cursor()",
    "source return if parser.peek() != TokenKind.Ident or not ParserWhereSuffixKeyword::is_where_keyword(Lexer::text_or_empty(where_token, parser.source))",
    "parser, _ <- parser.advance()",
]


def require_parser_guard(source: str, description: str) -> None:
    statements = function_statements(source, signature)
    if statements[:len(expected_prefix)] != expected_prefix:
        raise SystemExit(f"{description} no longer preserves the group, token-kind, and keyword guards before consumption")


suffix_text = SUFFIX.read_text()
require_parser_guard(suffix_text, "production where-view suffix")

# Mutation controls demonstrate that the source checker rejects both a changed
# keyword pattern and a parser path that admits the suffix outside its group.
mutated_keyword = keyword_text.replace('"where" -> true', '"whereish" -> true', 1)
try:
    require_classifier(mutated_keyword, "is_where_keyword", "mutated production classifier")
except SystemExit:
    pass
else:
    raise SystemExit("keyword source gate accepted a changed literal pattern")
keyword_prefix, keyword_dispatch = keyword_text.split("return when text:", 1)
mutated_dispatch = keyword_prefix + "return when text:" + keyword_dispatch.replace(
    '"where" -> true', '"whereish" -> true', 1
)
try:
    require_classifier(mutated_dispatch, "is_where_keyword", "mutated production dispatch")
except SystemExit:
    pass
else:
    raise SystemExit("keyword source gate accepted a changed implementation arm")

mutated_suffix = suffix_text.replace(
    "source return if not parser.in_where_group",
    "source return if parser.in_where_group",
    1,
)
try:
    require_parser_guard(mutated_suffix, "mutated where-view suffix")
except SystemExit:
    pass
else:
    raise SystemExit("where-group source gate accepted an inverted guard")

positive_names = {
    "source_where_keyword_classification_is_exact",
    "lowercase_where_is_recognized",
    "another_keyword_is_not_recognized",
    "keyword_prefix_is_not_recognized",
}
negative_names = {
    "capitalized_where_is_recognized",
    "a_keyword_prefix_is_recognized",
}
if 'include "../../src/parser/parser_where_suffix_keyword.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer imports the production classifier")
if 'include "../../src/parser/parser_where_suffix_keyword.elisa"' not in negative_text:
    raise SystemExit("false-claim proof no longer imports the production classifier")
for name in positive_names:
    if not re.search(rf"\bdef\s+{re.escape(name)}\s*\(", positive_text):
        raise SystemExit(f"positive contextual-keyword theorem is missing: {name}")
for name in negative_names:
    if not re.search(rf"\bdef\s+{re.escape(name)}\s*\(", negative_text):
        raise SystemExit(f"false contextual-keyword control is missing: {name}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("parser contextual-keyword proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
    stage1_provenance, Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
    KEYWORD, SUFFIX, EXPR_LITERALS, PARSER,
]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
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
assert positive == run(POSITIVE)[1], "contextual-keyword proof changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "capitalized_where_is_recognized"),
    ("ensure-unproven", "a_keyword_prefix_is_recognized"),
]
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert require_current_product(BIN, PROVER) == manifest
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact contextual `where` classification in expression suffix parsing",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
