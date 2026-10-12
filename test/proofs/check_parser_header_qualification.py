"""Admit the contextual header-keyword qualifier against the production parser."""
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
MODEL = ROOT / "src/parser/parser_header_qualification_model.elisa"
HELPER = ROOT / "src/parser/parser_header_qualification.elisa"
IMPORTER = ROOT / "src/parser/parser_types_extern.elisa"
SIGNATURES = ROOT / "src/parser/parser_types_signature.elisa"
PROBES = ROOT / "src/parser/parser_extern_header_probes.elisa"
CURSOR = ROOT / "src/parser/parser_core_cursor.elisa"
POSITIVE = HERE / "parser_header_qualification.elisa"
NEGATIVE = HERE / "parser_header_qualification_rejected.elisa"

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
    section = source[start:end]
    return "\n".join(line for line in section.splitlines()
                     if not line.lstrip().startswith("#"))


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


model_text = MODEL.read_text()
if compact(model_text).count(compact("module ParserHeaderQualification:")) != 1:
    raise SystemExit("production qualification model module changed")
expected_model = {
    "has_token": "def has_token(position: usize, token_count: usize) -> bool: ensure result == (position < token_count) return position < token_count",
    "offset_is_in_range": "def offset_is_in_range(position: usize, token_count: usize, offset: usize) -> bool: requires position < token_count ensure result == (offset < token_count - position) return offset < token_count - position",
    "qualified_by_neighbors": "def qualified_by_neighbors(offset: usize, following_is_scope: bool, previous_is_scope: bool, previous_token_is_scope: bool) -> bool: ensure result == (following_is_scope or (offset > 0 and previous_is_scope) or (offset == 0 and previous_token_is_scope)) return following_is_scope or (offset > 0 and previous_is_scope) or (offset == 0 and previous_token_is_scope)",
}
for name, expected in expected_model.items():
    if compact(function_section(model_text, name)) != compact(expected):
        raise SystemExit(f"production qualification model {name} changed")

helper_text = HELPER.read_text()
if 'include "./parser_header_qualification_model.elisa"' not in helper_text:
    raise SystemExit("production parser helper no longer imports the proved qualification model")
qualifier = compact(function_section(helper_text, "header_token_is_qualified"))
expected_qualifier = compact("""def header_token_is_qualified(parser: Parser&, offset: usize) -> bool:
            return false if not ParserHeaderQualification::has_token(parser.position, parser.tokens.count)
            return false if not ParserHeaderQualification::offset_is_in_range(parser.position, parser.tokens.count, offset)
            following_is_scope: bool = parser.peek_at(offset + 1) == TokenKind.Scope
            previous_is_scope: mutable bool = false
            previous_token_is_scope: mutable bool = false
            previous_is_scope <- parser.peek_at(offset - 1) == TokenKind.Scope if offset > 0
            previous_token_is_scope <- parser.tokens[parser.position - 1].kind == TokenKind.Scope if parser.position > 0
            return ParserHeaderQualification::qualified_by_neighbors(offset, following_is_scope, previous_is_scope, previous_token_is_scope)""")
if qualifier != expected_qualifier:
    raise SystemExit("production header keyword qualification no longer follows the verified bounds and neighbor rules")
if 'include "./parser_header_qualification.elisa"' not in IMPORTER.read_text():
    raise SystemExit("production parser assembly no longer includes the qualified-header helper")
expected_peek = compact("""def peek_at(parser: Parser&, offset: usize) -> TokenKind:
            token_index: usize = parser.position + offset
            machine over token_index:
                state Peek
                start Peek
                Peek, _ if token_index < parser.tokens.count:
                    return parser.tokens[token_index].kind
                Peek, _:
                    return TokenKind.Eof
            return TokenKind.Eof""")
if compact(function_section(CURSOR.read_text(), "peek_at")) != expected_peek:
    raise SystemExit("parser lookahead no longer bounds token indexing and maps past-end reads to EOF")
expected_capture = compact("""def capture_extern_header_contracts(parser: lmut Parser, extern_line: u32) -> void:
            can Abort.Panic, Memory.Allocate:
                machine over parser.position while parser.peek() != TokenKind.Eof:
                    state Scan(depth: int)
                    start Scan(0)
                    Scan(depth), _ if depth == 0 and (parser.peek() == TokenKind.Colon or parser.peek() == TokenKind.Newline):
                        break
                    Scan(depth), _ if depth == 0 and parser.peek() == TokenKind.Ident and not parser.header_token_is_qualified(0) and (parser.header_token_text(0) == "requires" or parser.header_token_text(0) == "require" or parser.header_token_text(0) == "ensure" or parser.header_token_text(0) == "ensures") and parser.peek_at(1) != TokenKind.Return:
                        parser <- parser.capture_signature_contract(parser.header_token_text(0)) can Global{Read,Write}
                        -> Scan(depth)
                    Scan(depth), _ if parser.peek() == TokenKind.LParen or parser.peek() == TokenKind.LBracket:
                        parser.position <- parser.position + 1
                        -> Scan(depth + 1)
                    Scan(depth), _ if parser.peek() == TokenKind.RParen or parser.peek() == TokenKind.RBracket:
                        parser.position <- parser.position + 1
                        -> Scan(depth - 1)
                    Scan(depth), _:
                        parser.position <- parser.position + 1
                        -> Scan(depth)
                parser <- parser.drain_signature_contracts(extern_line)""")
if compact(function_section(SIGNATURES.read_text(), "capture_extern_header_contracts")) != expected_capture:
    raise SystemExit("extern header contract parser no longer uses exactly the verified qualifier path")
expected_probe = compact("""def header_has_signature_contract(parser: Parser&) -> bool:
            can Abort.Panic:
                machine over parser.position:
                    state Scan(index: usize)
                    start Scan(0)
                    Scan(index), _ if parser.peek_at(index) == TokenKind.Ident and not parser.header_token_is_qualified(index) and (parser.header_token_text(index) == "requires" or parser.header_token_text(index) == "ensure" or parser.header_token_text(index) == "ensures"):
                        return true
                    Scan(index), _ if parser.peek_at(index) == TokenKind.Newline or parser.peek_at(index) == TokenKind.Eof:
                        return false
                    Scan(index), _:
                        -> Scan(index + 1)
                return false""")
if compact(function_section(PROBES.read_text(), "header_has_signature_contract")) != expected_probe:
    raise SystemExit("extern contract probe no longer uses exactly the verified qualifier path")

positive_names = {
    "cursor_has_token_matches_unsigned_order",
    "cursor_at_token_end_has_no_token",
    "offset_before_remaining_end_is_in_range",
    "offset_at_remaining_end_is_rejected",
    "offset_after_remaining_end_is_rejected",
    "following_peek_index_is_at_or_before_token_end",
    "preceding_peek_index_is_inside_token_stream",
    "cursor_predecessor_index_is_inside_token_stream",
    "following_scope_qualifies_even_at_offset_zero",
    "qualification_matches_the_exact_neighbor_policy",
    "relative_previous_scope_qualifies_after_offset_zero",
    "cursor_predecessor_is_fallback_at_offset_zero",
    "prior_token_does_not_override_a_nonzero_offset",
    "no_scope_neighbor_leaves_word_unqualified",
}
negative_names = {
    "token_at_end_is_present",
    "offset_at_remaining_end_is_accepted",
    "prior_token_qualifies_a_nonzero_offset_without_neighbor",
    "relative_previous_scope_qualifies_at_offset_zero",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "../../src/parser/parser_header_qualification_model.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer proves the production parser model")

positive_shapes = {
    "cursor_has_token_matches_unsigned_order": "ensure result == true return ParserHeaderQualification::has_token(position, token_count) == (position < token_count)",
    "cursor_at_token_end_has_no_token": "ensure result == true return not ParserHeaderQualification::has_token(token_count, token_count)",
    "offset_before_remaining_end_is_in_range": "requires position < token_count requires offset < token_count - position ensure result == true return ParserHeaderQualification::offset_is_in_range(position, token_count, offset)",
    "offset_at_remaining_end_is_rejected": "requires position < token_count requires offset == token_count - position ensure result == true return not ParserHeaderQualification::offset_is_in_range(position, token_count, offset)",
    "offset_after_remaining_end_is_rejected": "requires position < token_count requires offset > token_count - position ensure result == true return not ParserHeaderQualification::offset_is_in_range(position, token_count, offset)",
    "following_peek_index_is_at_or_before_token_end": "requires position < token_count requires offset < token_count - position ensure result == true return position + offset + 1 <= token_count",
    "preceding_peek_index_is_inside_token_stream": "requires position < token_count requires offset > 0 requires offset < token_count - position ensure result == true return position + (offset - 1) < token_count",
    "cursor_predecessor_index_is_inside_token_stream": "requires position > 0 requires position < token_count ensure result == true return position - 1 < token_count",
    "following_scope_qualifies_even_at_offset_zero": "ensure result == true return ParserHeaderQualification::qualified_by_neighbors(0, true, false, false)",
    "qualification_matches_the_exact_neighbor_policy": "ensure result == true return ParserHeaderQualification::qualified_by_neighbors(offset, following_is_scope, previous_is_scope, previous_token_is_scope) == (following_is_scope or (offset > 0 and previous_is_scope) or (offset == 0 and previous_token_is_scope))",
    "relative_previous_scope_qualifies_after_offset_zero": "requires offset > 0 ensure result == true return ParserHeaderQualification::qualified_by_neighbors(offset, false, true, false)",
    "cursor_predecessor_is_fallback_at_offset_zero": "ensure result == true return ParserHeaderQualification::qualified_by_neighbors(0, false, false, true)",
    "prior_token_does_not_override_a_nonzero_offset": "requires offset > 0 ensure result == true return not ParserHeaderQualification::qualified_by_neighbors(offset, false, false, true)",
    "no_scope_neighbor_leaves_word_unqualified": "ensure result == true return not ParserHeaderQualification::qualified_by_neighbors(offset, false, false, false)",
}
negative_shapes = {
    "token_at_end_is_present": "ensure result == true return ParserHeaderQualification::has_token(token_count, token_count)",
    "offset_at_remaining_end_is_accepted": "requires position < token_count ensure result == true return ParserHeaderQualification::offset_is_in_range(position, token_count, token_count - position)",
    "prior_token_qualifies_a_nonzero_offset_without_neighbor": "requires offset > 0 ensure result == true return ParserHeaderQualification::qualified_by_neighbors(offset, false, false, true)",
    "relative_previous_scope_qualifies_at_offset_zero": "ensure result == true return ParserHeaderQualification::qualified_by_neighbors(0, false, true, false)",
}
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    proof_text = path.read_text()
    for name, shape in shapes.items():
        args = "position: usize, token_count: usize, offset: usize" if name in {
            "offset_before_remaining_end_is_in_range",
            "offset_at_remaining_end_is_rejected",
            "offset_after_remaining_end_is_rejected",
            "following_peek_index_is_at_or_before_token_end",
            "preceding_peek_index_is_inside_token_stream",
        } else (
            "position: usize, token_count: usize" if name in {
                "cursor_has_token_matches_unsigned_order",
                "offset_at_remaining_end_is_accepted",
            "cursor_predecessor_index_is_inside_token_stream",
            } else (
                "token_count: usize" if name in {
                    "cursor_at_token_end_has_no_token",
                    "token_at_end_is_present",
                } else (
                "offset: usize" if name in {
                        "relative_previous_scope_qualifies_after_offset_zero",
                        "prior_token_does_not_override_a_nonzero_offset",
                        "no_scope_neighbor_leaves_word_unqualified",
                        "prior_token_qualifies_a_nonzero_offset_without_neighbor",
                } else (
                    "offset: usize, following_is_scope: bool, previous_is_scope: bool, previous_token_is_scope: bool"
                    if name == "qualification_matches_the_exact_neighbor_policy" else ""
                )
                )
            )
        )
        if compact(function_section(proof_text, name)) != compact(f"def {name}({args}) -> bool: {shape}"):
            raise SystemExit(f"{name} no longer states the admitted parser qualification theorem")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("parser header qualification proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
    MODEL, HELPER, IMPORTER, SIGNATURES, PROBES,
    CURSOR,
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
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert not positive["findings"]
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert positive == run(POSITIVE)[1], "parser qualification proof report changed across repeated runs"
verified = {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert positive_names | set(expected_model) <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert {(item["kind"], item["name"]) for item in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert all(item["status"] == "disproved" and item["counterexample_found"]
           for item in negative["findings"])
assert require_current_product(BIN, PROVER) == product
if hashes_before != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}:
    raise SystemExit("parser qualification proof inputs changed during replay")

print(json.dumps({
    "admitted": True,
    "scope": "header keyword cursor bounds and following/preceding scope qualification",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
