"""Admit the quoted string/character classification proof against the scanner."""
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
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POLICY = ROOT / "src/lexer/lexer_quoted_input_policy.elisa"
SCANNER = ROOT / "src/lexer/lexer_strings.elisa"
POSITIVE = HERE / "lexer_quoted_input.elisa"
NEGATIVE = HERE / "lexer_quoted_input_rejected.elisa"
TIMEOUT_SECONDS = 60


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


policy_source = POLICY.read_text()
policy_compact = compact(policy_source)
policy_header = compact("module LexerQuotedInputPolicy: const enum QuotedClass of u8:")
if policy_header not in policy_compact:
    raise SystemExit("quoted classification enum is no longer declared in the policy module")
class_names = ["Terminator", "Newline", "EscapeTerm", "Escape", "Other"]
enum_body = re.search(r"(?ms)^    const enum QuotedClass of u8:\n(.*?)(?=^    def )", policy_source)
if enum_body is None:
    raise SystemExit("could not isolate the quoted classification enum")
if re.findall(r"(?m)^        ([A-Za-z_][A-Za-z0-9_]*)\s*$", enum_body.group(1)) != class_names:
    raise SystemExit("quoted classification enum no longer has the exact five scanner states")
expected_classifier = compact(r"""
def classify(character: char, terminator: char, at_source_end: bool, next_is_newline: bool) -> QuotedClass:
    return QuotedClass.Terminator if character == terminator
    return QuotedClass.Newline if character == '\n'
    if character == '\\':
        return QuotedClass.EscapeTerm if at_source_end or next_is_newline
        return QuotedClass.Escape
    return QuotedClass.Other
""")
if compact(function_section(policy_source, "classify")) != expected_classifier:
    raise SystemExit("production quoted-input policy changed from the predicate proved here")
if compact(function_section(policy_source, "char_prefix_is_loop_label")) != compact(
    "def char_prefix_is_loop_label(next_is_identifier_start: bool, closes_character_literal: bool) -> bool: "
    "return next_is_identifier_start and not closes_character_literal"
):
    raise SystemExit("character literal/loop-label policy changed from the predicate proved here")

scanner_source = SCANNER.read_text()
if 'include "./lexer_quoted_input_policy.elisa"' not in scanner_source:
    raise SystemExit("quoted scanner no longer imports the proved policy")
expected_adapter = compact(r"""
def classify_quoted_input(lexer: Lexer&, terminator: char) -> LexerQuotedInputPolicy::QuotedClass:
    character: char = lexer.current_char()
    at_source_end: mutable bool = false
    next_is_newline: mutable bool = false
    if character == '\\':
        at_source_end <- lexer.position + 1 >= lexer.source_length
        if not at_source_end:
            next_is_newline <- lexer.peek(1) == '\n'
    return LexerQuotedInputPolicy::classify(character, terminator, at_source_end, next_is_newline)
""")
if compact(function_section(scanner_source, "classify_quoted_input")) != expected_adapter:
    raise SystemExit("lexer adapter no longer supplies the guarded source-bound lookahead")

quoted_scanner = compact(function_section(scanner_source, "read_quoted"))
required_transitions = [
    compact("machine over lexer.classify_quoted_input(terminator) while not lexer.is_end_of_source()"),
    compact("Body, LexerQuotedInputPolicy::QuotedClass.Terminator: lexer.quoted_text_end <- lexer.position lexer.quoted_done <- true lexer <- lexer.advance_char() -> Done"),
    compact("Body, LexerQuotedInputPolicy::QuotedClass.Newline: lexer.quoted_text_end <- lexer.position lexer.quoted_done <- true -> Done"),
    compact("Body, LexerQuotedInputPolicy::QuotedClass.EscapeTerm: lexer <- lexer.advance_char() lexer.quoted_text_end <- lexer.position lexer.quoted_done <- true -> Done"),
    compact("Body, LexerQuotedInputPolicy::QuotedClass.Escape: lexer <- lexer.advance_chars(2) -> Body"),
    compact("Body, LexerQuotedInputPolicy::QuotedClass.Other: lexer <- lexer.advance_char() -> Body"),
    compact("Done, LexerQuotedInputPolicy::QuotedClass.Terminator | LexerQuotedInputPolicy::QuotedClass.Newline | LexerQuotedInputPolicy::QuotedClass.EscapeTerm | LexerQuotedInputPolicy::QuotedClass.Escape | LexerQuotedInputPolicy::QuotedClass.Other: break"),
    compact("return Token(kind, position, start, lexer.quoted_text_end)"),
]
positions = [quoted_scanner.find(fragment) for fragment in required_transitions]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("quoted scanner transitions, span endpoints, or exhaustive Done state changed")
if quoted_scanner.count("Body,LexerQuotedInputPolicy::QuotedClass.") != len(class_names):
    raise SystemExit("quoted scanner no longer has exactly one body transition per classification")

string_call = "lexer.read_quoted('" + chr(34) + "',TokenKind.StringLit)"
if compact(function_section(scanner_source, "read_string")).find(compact(string_call)) < 0:
    raise SystemExit("string literal scanning no longer uses the shared quoted scanner")
char_call = "lexer.read_quoted('" + chr(92) + "'" + "',TokenKind.CharLit)"
if compact(function_section(scanner_source, "read_char")).find(compact(char_call)) < 0:
    raise SystemExit("character literal scanning no longer uses the shared quoted scanner")
read_char = compact(function_section(scanner_source, "read_char"))
char_quote = "'" + chr(92) + "''"
label_gate = compact(
    "next_is_identifier_start: bool = is_identifier_start(lexer.peek(1)) "
    "closes_character_literal: mutable bool = false "
    "if next_is_identifier_start: "
    "closes_character_literal <- lexer.peek(2) == " + char_quote + " "
    "if LexerQuotedInputPolicy::char_prefix_is_loop_label(next_is_identifier_start, closes_character_literal):"
)
if label_gate not in read_char:
    raise SystemExit("read_char no longer uses the proved, guarded identifier/closing-quote decision")
if not (read_char.index(label_gate) < read_char.index("lexer.read_identifier()") < read_char.index("lexer.read_quoted(")):
    raise SystemExit("loop-label selection no longer precedes identifier parsing and character-literal fallback")

positive_names = {
    "quoted_terminator_has_priority",
    "newline_stops_quoted_scanning",
    "trailing_backslash_is_escape_terminator",
    "ordinary_backslash_skips_next_character",
    "ordinary_quoted_character_is_other",
    "quoted_classifier_is_total",
    "unclosed_identifier_prefix_is_loop_label",
    "closed_single_character_prefix_is_not_loop_label",
    "non_identifier_prefix_is_not_loop_label",
}
negative_names = {
    "false_claim_trailing_backslash_is_other",
    "false_claim_nonterminal_escape_is_escape_terminator",
    "false_claim_terminator_is_other",
    "false_claim_closed_character_is_loop_label",
    "false_claim_non_identifier_prefix_is_loop_label",
}
if declarations(POSITIVE) != positive_names or declarations(NEGATIVE) != negative_names:
    raise SystemExit("quoted-input positive or rejected proof declaration inventory changed")
if 'include "../../src/lexer/lexer_quoted_input_policy.elisa"' not in POSITIVE.read_text():
    raise SystemExit("proof no longer includes the production quoted-input policy")
if 'include "./lexer_quoted_input.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative proof no longer reuses the source-linked positive laws")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("quoted-input proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    *source_include_closure([POSITIVE, NEGATIVE, SCANNER]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=TIMEOUT_SECONDS)
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
assert positive == run(POSITIVE)[1], "quoted-input proof report changed across repeated replay"
assert positive_names <= {
    row["name"] for row in positive["declaration_details"] if row.get("verified")
}

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert all(row["status"] == "disproved" and row["counterexample_found"]
           for row in negative["findings"])
assert product == require_current_product(BIN, PROVER)
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "quoted-input proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "quoted string/character classifier, EOF/newline escape boundaries, and token span transitions",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
