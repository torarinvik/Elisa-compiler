"""Admit the exhaustive keyword-table proofs against the strict proof product."""
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
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
SOURCE = ROOT / "src/lexer/lexer_identifiers.elisa"
LEXER_ROOT = ROOT / "src/lexer/lexer.elisa"
CORE = ROOT / "src/lexer/lexer_core.elisa"
TOKEN_SOURCE = ROOT / "src/lexer/tokens.elisa"
PROJECTION = HERE / "parser_token_kind_projection.elisa"
POSITIVE = HERE / "lexer_keyword_table.elisa"
NEGATIVE = HERE / "lexer_keyword_table_rejected.elisa"
MISSPELLINGS = {"iff", "defn", "mutabl", "align_ofx", "offset_ofx", "aligned", "DEF", "As", "x", "abcdefghij"}

if not __debug__:
    raise SystemExit("run without Python -O")


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^[ \t]*def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(0).split("def", 1)[0]
    tail = source[match.end():]
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", tail)
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def production_mapping(source_text: str) -> dict[str, str]:
    body = function_section(source_text, "frontend_lookup_keyword")
    if "text_length: usize = sview_len(text)" not in body:
        raise ValueError("keyword classifier no longer partitions on the text byte length")
    lines = body.splitlines()
    branch_headers = [(index, int(match.group(1))) for index, line in enumerate(lines)
                      if (match := re.fullmatch(r"\s*if text_length == (\d+):", line))]
    if [length for _, length in branch_headers] != list(range(2, 10)):
        raise ValueError("keyword classifier must retain exactly the ordered length buckets 2 through 9")
    mapping: dict[str, str] = {}
    for branch_number, (start, expected_length) in enumerate(branch_headers):
        stop = branch_headers[branch_number + 1][0] if branch_number + 1 < len(branch_headers) else next(
            (index for index in range(start + 1, len(lines))
             if re.fullmatch(r"\s*return TokenKind\.Ident", lines[index])), len(lines))
        branch = lines[start + 1:stop]
        if not any(re.fullmatch(r"\s*return when text:", line) for line in branch):
            raise ValueError(f"length {expected_length} no longer dispatches through an exhaustive string match")
        for line in branch:
            stripped = line.strip()
            if (not stripped or stripped.startswith("#") or
                    re.fullmatch(r"return when text:", stripped) or
                    re.fullmatch(r'"[^"]+" -> TokenKind\.[A-Za-z_][A-Za-z0-9_]*', stripped) or
                    re.fullmatch(r"_ -> TokenKind\.Ident", stripped)):
                continue
            raise ValueError(f"unexpected logic in the length {expected_length} string match: {stripped}")
        defaults = [line for line in branch if re.fullmatch(r"\s*_ -> TokenKind\.Ident", line)]
        if len(defaults) != 1:
            raise ValueError(f"length {expected_length} must retain exactly one Ident default arm")
        for line in branch:
            match = re.fullmatch(r'\s*"([^"]+)" -> TokenKind\.([A-Za-z_][A-Za-z0-9_]*)', line)
            if not match:
                continue
            spelling, token_kind = match.groups()
            if len(spelling) != expected_length:
                raise ValueError(f"{spelling!r} appears in the wrong byte-length bucket")
            if spelling in mapping:
                raise ValueError(f"duplicate production keyword spelling: {spelling}")
            mapping[spelling] = token_kind
    if not re.search(r"(?m)^\s*return TokenKind\.Ident\s*$", body):
        raise ValueError("keyword classifier lost its outside-bucket Ident fallback")
    return mapping


def admit_source_and_proof(source_text: str, proof_text: str) -> None:
    source = production_mapping(source_text)
    pairs = re.findall(
        r'Lexer::frontend_lookup_keyword\("([^"]+)"\)\s*==\s*Lexer::TokenKind\.([A-Za-z_][A-Za-z0-9_]*)',
        proof_text,
    )
    proof = {spelling: token_kind for spelling, token_kind in pairs if spelling in source}
    if proof != source:
        missing = sorted(set(source.items()) - set(proof.items()))
        extra = sorted(set(proof.items()) - set(source.items()))
        raise ValueError(f"positive keyword examples differ from production; missing={missing}, extra={extra}")
    misspellings = {spelling for spelling, token_kind in pairs
                    if spelling not in source and token_kind == "Ident"}
    if len(pairs) != len(proof) + len(MISSPELLINGS) or misspellings != MISSPELLINGS:
        raise ValueError("positive proof must cover each selected same-length and outside-bucket Ident case")


def admit_production_wiring(lexer_text: str, core_text: str) -> None:
    if 'include "./lexer_identifiers.elisa"' not in lexer_text:
        raise ValueError("lexer root no longer includes the source-linked keyword classifier")
    reader = function_section(core_text, "read_identifier")
    expected = (
        "text: sview = source_view_or_empty(lexer.source, lexer.source_length, start, lexer.position)",
        "kind: TokenKind = frontend_lookup_keyword(text)",
        "return Token(kind, position, start, lexer.position)",
    )
    positions = [reader.find(fragment) for fragment in expected]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise ValueError("read_identifier no longer routes the scanned spelling through the proved keyword table")


source_text = SOURCE.read_text()
lexer_text = LEXER_ROOT.read_text()
core_text = CORE.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
if 'include "./parser_token_kind_projection.elisa"' not in positive_text:
    raise SystemExit("positive keyword proof lost its TokenKind projection")
if 'include "../../src/lexer/lexer_identifiers.elisa"' not in positive_text:
    raise SystemExit("positive keyword proof no longer includes the production classifier")
if 'include "./lexer_keyword_table.elisa"' not in negative_text:
    raise SystemExit("rejected controls no longer use the source-linked production proof")


def enum_variants(text: str) -> list[str]:
    lines = text.splitlines()
    header = re.compile(r"^( *)const enum TokenKind of u8:\s*$")
    for index, line in enumerate(lines):
        match = header.match(line)
        if not match:
            continue
        indent = len(match.group(1))
        variants = []
        for variant_line in lines[index + 1:]:
            if not variant_line.strip() or variant_line.lstrip().startswith("#"):
                continue
            variant_indent = len(variant_line) - len(variant_line.lstrip(" "))
            if variant_indent <= indent:
                break
            if variant_indent == indent + 4:
                variants.append(variant_line.strip())
        return variants
    raise SystemExit("TokenKind enum declaration is missing")


token_kinds = enum_variants(TOKEN_SOURCE.read_text())
if token_kinds != enum_variants(PROJECTION.read_text()):
    raise SystemExit("keyword proof TokenKind projection differs from production enum order")
if set(production_mapping(source_text).values()) - set(token_kinds):
    raise SystemExit("keyword table names a TokenKind variant absent from the production enum")

try:
    admit_source_and_proof(source_text, positive_text)
    admit_production_wiring(lexer_text, core_text)
except ValueError as error:
    raise SystemExit(str(error)) from error

positive_names = {
    "length_two_keywords_keep_their_token_kinds",
    "length_three_keywords_keep_their_token_kinds",
    "length_four_keywords_keep_their_token_kinds",
    "length_five_keywords_keep_their_token_kinds",
    "length_six_keywords_keep_their_token_kinds",
    "length_seven_keywords_keep_their_token_kinds",
    "length_eight_keywords_keep_their_token_kinds",
    "length_nine_keyword_keeps_its_token_kind",
    "keyword_near_misses_remain_identifiers",
    "lengths_outside_the_keyword_table_remain_identifiers",
}
negative_names = {
    "a_keyword_must_not_be_returned_as_an_identifier",
    "a_near_miss_must_not_be_returned_as_a_keyword",
    "the_reserved_aligned_spelling_must_remain_an_identifier",
    "uppercase_keyword_spelling_must_remain_an_identifier",
}


def declarations(text: str) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", text))


if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("keyword-table proof declaration inventory changed")
negative_shapes = {
    "a_keyword_must_not_be_returned_as_an_identifier": 'ensure result == true return Lexer::frontend_lookup_keyword("def") == Lexer::TokenKind.Ident',
    "a_near_miss_must_not_be_returned_as_a_keyword": 'ensure result == true return Lexer::frontend_lookup_keyword("defn") == Lexer::TokenKind.Def',
    "the_reserved_aligned_spelling_must_remain_an_identifier": 'ensure result == true return Lexer::frontend_lookup_keyword("aligned") != Lexer::TokenKind.Ident',
    "uppercase_keyword_spelling_must_remain_an_identifier": 'ensure result == true return Lexer::frontend_lookup_keyword("DEF") != Lexer::TokenKind.Ident',
}
for name, expected in negative_shapes.items():
    if "".join(expected.split()) not in "".join(function_section(negative_text, name).split()):
        raise SystemExit(f"{name} no longer challenges the intended fallback property")

# Exercise the exact source-admission check against a changed token and a lost
# default arm so table edits cannot leave the finite proof coverage behind.
mutated_kind = source_text.replace('"def" -> TokenKind.Def', '"def" -> TokenKind.Ident', 1)
mutated_default = source_text.replace('_ -> TokenKind.Ident', '_ -> TokenKind.Def', 1)
for mutation in (mutated_kind, mutated_default):
    try:
        admit_source_and_proof(mutation, positive_text)
    except ValueError:
        continue
    raise SystemExit("keyword source mutation escaped the proof-table admission check")
mutated_core = core_text.replace("kind: TokenKind = frontend_lookup_keyword(text)",
                                "kind: TokenKind = TokenKind.Ident", 1)
try:
    admit_production_wiring(lexer_text, mutated_core)
except ValueError:
    pass
else:
    raise SystemExit("identifier-token classification bypass escaped the proof wiring check")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("keyword-table proofs require a strict proof build")

compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    SOURCE, LEXER_ROOT, CORE, TOKEN_SOURCE, PROJECTION, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
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
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "keyword-table proof report changed across identical runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified
assert all(row.get("verified") for row in positive["declaration_details"]
           if row.get("kind") == "function")

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert require_current_product(BIN, PROVER) == product
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({
    "admitted": True,
    "scope": "exact spellings, TokenKind results, and Ident fallbacks for all production keyword buckets",
    "keyword_entries": len(production_mapping(source_text)),
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
