"""Admit comment-scanner cursor progress facts against the production loops."""
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
HELPER = ROOT / "src/lexer/lexer_comment_scan.elisa"
STEP = ROOT / "src/lexer/lexer_position_step.elisa"
LEXER = ROOT / "src/lexer/lexer.elisa"
COMMENTS = ROOT / "src/lexer/lexer_comments.elisa"
TOKENS = ROOT / "src/lexer/lexer_tokens.elisa"
CORE = ROOT / "src/lexer/lexer_core.elisa"
TOKEN = ROOT / "src/lexer/lexer_token.elisa"
SPAN = ROOT / "src/lexer/lexer_token_span.elisa"
POSITIVE = HERE / "lexer_comment_scan.elisa"
NEGATIVE = HERE / "lexer_comment_scan_rejected.elisa"

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
    lines = source[start:end].splitlines()
    while lines and (not lines[-1].strip() or lines[-1].lstrip().startswith(("#", "@"))):
        lines.pop()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def require_fragments(body: str, fragments: tuple[str, ...], label: str) -> None:
    text = compact(body)
    if any(compact(fragment) not in text for fragment in fragments):
        raise SystemExit(f"{label} no longer follows the checked comment-scanner path")


def require_ordered(body: str, fragments: tuple[str, ...], label: str) -> None:
    text = compact(body)
    positions = [text.find(compact(fragment)) for fragment in fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{label} changed the order of its guarded cursor transition")


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


helper_text = HELPER.read_text()
if 'include "./lexer_position_step.elisa"' not in helper_text:
    raise SystemExit("comment scan model no longer imports the production cursor transition")
expected_helper = {
    "remaining": "def remaining(source_length: usize, position: usize) -> usize: requires position <= source_length ensure result <= source_length return source_length - position",
    "after_one": "def after_one(position: usize, source_length: usize) -> usize: ensure result == (position + 1 if position < source_length else position) return LexerPositionStep::advanced_offset(position, source_length)",
    "column_after_three": "def column_after_three(column: int) -> int: ensure result == column + 3 return column + 3",
}
for name, expected in expected_helper.items():
    if compact(function_section(helper_text, name)) != compact(expected):
        raise SystemExit(f"production comment cursor helper {name} changed")
three_step = compact(function_section(helper_text, "after_three"))
expected_three_step = compact("""def after_three(position: usize, source_length: usize) -> usize:
            ensure result == (LexerPositionStep::advanced_offset(LexerPositionStep::advanced_offset(LexerPositionStep::advanced_offset(position, source_length), source_length), source_length))
            return LexerPositionStep::advanced_offset(LexerPositionStep::advanced_offset(LexerPositionStep::advanced_offset(position, source_length), source_length), source_length)""")
if three_step != expected_three_step:
    raise SystemExit("three-character comment delimiter model no longer composes three guarded cursor steps")

facade_text = LEXER.read_text()
if 'include "./lexer_comment_scan.elisa"' not in facade_text:
    raise SystemExit("lexer facade no longer includes the proved comment cursor model")
if facade_text.index('include "./lexer_comment_scan.elisa"') > facade_text.index('include "./lexer_comments.elisa"'):
    raise SystemExit("comment cursor proof model must be in scope before the production scanners")

comments_text = COMMENTS.read_text()
line_scan = function_section(comments_text, "skip_line_comment")
expected_line_scan = compact("""def skip_line_comment(lexer: lmut Lexer):
            position: LexerPosition = lexer.cursor_position()
            start: usize = lexer.position
            machine over lexer.current_char() while not lexer.is_end_of_source() and lexer.current_char() != '\\n':
                state Scan
                start Scan
                Scan, _:
                    lexer.position <- LexerCommentScan::after_one(lexer.position, lexer.source_length)
                    lexer.column <- LexerPositionStep::advanced_column(lexer.column)
                    -> Scan
            lexer.comments <- lexer.comments.push(Token(TokenKind.Comment, position, start, lexer.position)) can Memory.Allocate, Abort.Panic""")
if compact(line_scan) != expected_line_scan:
    raise SystemExit("line-comment scanner no longer consists of the proved one-step cursor loop and span emission")

block_scan = function_section(comments_text, "skip_block_comment")
expected_block_scan = compact("""def skip_block_comment(lexer: lmut Lexer):
            position: LexerPosition = lexer.cursor_position()
            start: usize = lexer.position
            lexer.position <- LexerCommentScan::after_three(lexer.position, lexer.source_length)
            lexer.column <- LexerCommentScan::column_after_three(lexer.column)
            machine over lexer.is_block_comment_start() while not lexer.is_end_of_source():
                state Scan
                start Scan
                Scan, true:
                    lexer.position <- LexerCommentScan::after_three(lexer.position, lexer.source_length)
                    lexer.column <- LexerCommentScan::column_after_three(lexer.column)
                    lexer.comments <- lexer.comments.push(Token(TokenKind.Comment, position, start, lexer.position)) can Memory.Allocate, Abort.Panic
                    return
                Scan, _:
                    lexer <- lexer.advance_char()
                    -> Scan
            lexer.comments <- lexer.comments.push(Token(TokenKind.Comment, position, start, lexer.position)) can Memory.Allocate, Abort.Panic""")
if compact(block_scan) != expected_block_scan:
    raise SystemExit("block-comment scanner no longer uses the proved delimiter step and ordinary character transition")
expected_marker = compact("def is_block_comment_start(lexer: Lexer&) -> bool: return lexer.current_char() == '\"' and lexer.peek(1) == '\"' and lexer.peek(2) == '\"'")
if compact(function_section(comments_text, "is_block_comment_start")) != expected_marker:
    raise SystemExit("block-comment delimiter predicate no longer requires three quote characters")

step_body = function_section(facade_text, "advance_char")
expected_step_body = compact("""def advance_char(lexer: lmut Lexer) -> void:
            return if lexer.is_end_of_source()
            character: char = lexer.current_char()
            is_newline: bool = character == '\\n'
            lexer.position <- LexerPositionStep::advanced_offset(lexer.position, lexer.source_length)
            lexer.line <- LexerPositionStep::advanced_line(lexer.line, is_newline)
            if is_newline:
                lexer.column <- LexerPositionStep::column_after_newline(is_newline)
            else:
                lexer.column <- LexerPositionStep::advanced_column(lexer.column)""")
if compact(step_body) != expected_step_body:
    raise SystemExit("Lexer.advance_char no longer exactly applies the proved bounded offset and line/column updates")

core_text = CORE.read_text()
require_ordered(function_section(core_text, "consume_indentation_trivia"), (
    "false return if not lexer.is_block_comment_start()",
    "lexer <- lexer.skip_block_comment()",
), "indentation trivia block-comment caller")
require_ordered(function_section(TOKENS.read_text(), "next_token"), (
    "-> BlockComment if lexer.is_block_comment_start()",
    "BlockComment:",
    "lexer <- lexer.skip_block_comment()",
), "token dispatch block-comment caller")
block_call_sites = set()
for source_file in (ROOT / "src/lexer").rglob("*.elisa"):
    if re.search(r"\blexer\s*<-\s*lexer\.skip_block_comment\(\)", source_file.read_text()):
        block_call_sites.add(source_file.resolve())
if block_call_sites != {CORE.resolve(), TOKENS.resolve()}:
    raise SystemExit("block-comment scanner has an unguarded, missing, or unexpected production caller")
end_guard = function_section(core_text, "is_end_of_source")
require_fragments(end_guard, (
    "ensure result == (lexer.position >= lexer.source_length)",
    "return LexerCursorDomain::cursor_at_or_past_source_end(lexer.position, lexer.source_length)",
), "comment scanner EOF guard")

token_text = TOKEN.read_text()
token_constructor_match = re.search(
    r"^[ \t]*def Token\(kind: TokenKind, position: LexerPosition, start: usize, text_end: usize, suffix_end: usize\) -> Token:\n(.*?)(?=^[ \t]*def |\Z)",
    token_text, re.MULTILINE | re.DOTALL)
if token_constructor_match is None:
    raise SystemExit("could not locate the production token-span constructor")
token_constructor = compact(token_constructor_match.group(0))
require_fragments(token_constructor, (
    "TokenSpan = token_span_fields(position.line.u32(), position.column.u32(), start.u32(), (text_end - start).u32(), (suffix_end - text_end).u16())",
    "token.start <- span.start",
    "token.length <- span.length",
), "comment token-span constructor")
expected_short_token_constructor = compact("""def Token(kind: TokenKind, position: LexerPosition, start: usize, text_end: usize) -> Token:
            return Token(kind, position, start, text_end, text_end)""")
short_token_matches = list(re.finditer(
    r"^[ \t]*def Token\(kind: TokenKind, position: LexerPosition, start: usize, text_end: usize\) -> Token:\n(.*?)(?=^[ \t]*def |\Z)",
    token_text, re.MULTILINE | re.DOTALL))
if len(short_token_matches) != 1 or compact(short_token_matches[0].group(0)) != expected_short_token_constructor:
    raise SystemExit("four-argument comment token construction no longer supplies an empty suffix span")
span_body = compact(function_section(SPAN.read_text(), "token_span_fields"))
for field in ("line", "column", "start", "length", "suffix_length"):
    require_fragments(span_body, (f"ensure result.{field} == {field}",), "TokenSpan projection")

positive_names = {
    "remaining_input_is_nonnegative",
    "line_comment_step_advances_by_one",
    "line_comment_step_stays_within_input",
    "line_comment_step_decreases_remaining_input",
    "block_comment_single_step_decreases_remaining_input",
    "three_present_delimiter_steps_match_offset_plus_three",
    "three_present_delimiter_steps_stay_within_input",
    "three_present_delimiter_steps_decrease_remaining_input",
    "delimiter_column_advances_by_three",
}
negative_names = {
    "line_comment_step_keeps_the_same_offset",
    "one_comment_step_increases_remaining_input",
    "a_three_character_delimiter_advances_by_two",
    "a_three_character_delimiter_advances_column_by_two",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "../../src/lexer/lexer_comment_scan.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer proves the production comment cursor model")

positive_shapes = {
    "remaining_input_is_nonnegative": "requires position <= source_length ensure result == true return LexerCommentScan::remaining(source_length, position) <= source_length",
    "line_comment_step_advances_by_one": "requires position < source_length ensure result == true return LexerCommentScan::after_one(position, source_length) == position + 1",
    "line_comment_step_stays_within_input": "requires position < source_length ensure result == true return LexerCommentScan::after_one(position, source_length) <= source_length",
    "line_comment_step_decreases_remaining_input": "requires position < source_length ensure result == true return LexerCommentScan::remaining(source_length, LexerCommentScan::after_one(position, source_length)) < LexerCommentScan::remaining(source_length, position)",
    "block_comment_single_step_decreases_remaining_input": "requires position < source_length ensure result == true return LexerCommentScan::remaining(source_length, LexerPositionStep::advanced_offset(position, source_length)) < LexerCommentScan::remaining(source_length, position)",
    "three_present_delimiter_steps_match_offset_plus_three": "requires position <= source_length requires source_length - position >= 3 ensure result == true return LexerCommentScan::after_three(position, source_length) == position + 3",
    "three_present_delimiter_steps_stay_within_input": "requires position <= source_length requires source_length - position >= 3 ensure result == true return LexerCommentScan::after_three(position, source_length) <= source_length",
    "three_present_delimiter_steps_decrease_remaining_input": "requires position <= source_length requires source_length - position >= 3 ensure result == true return LexerCommentScan::remaining(source_length, LexerCommentScan::after_three(position, source_length)) < LexerCommentScan::remaining(source_length, position)",
    "delimiter_column_advances_by_three": "ensure result == true return LexerCommentScan::column_after_three(column) == column + 3",
}
negative_shapes = {
    "line_comment_step_keeps_the_same_offset": "requires position < source_length ensure result == true return LexerCommentScan::after_one(position, source_length) == position",
    "one_comment_step_increases_remaining_input": "requires position < source_length ensure result == true return LexerCommentScan::remaining(source_length, LexerCommentScan::after_one(position, source_length)) > LexerCommentScan::remaining(source_length, position)",
    "a_three_character_delimiter_advances_by_two": "requires position <= source_length requires source_length - position >= 3 ensure result == true return LexerCommentScan::after_three(position, source_length) == position + 2",
    "a_three_character_delimiter_advances_column_by_two": "ensure result == true return LexerCommentScan::column_after_three(column) == column + 2",
}
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    proof_text = path.read_text()
    for name, shape in shapes.items():
        params = "column: int" if "column" in name else "position: usize, source_length: usize"
        if compact(function_section(proof_text, name)) != compact(f"def {name}({params}) -> bool: {shape}"):
            raise SystemExit(f"{name} no longer states the admitted cursor theorem")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("comment scan proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
    HELPER, STEP, LEXER, COMMENTS, TOKENS, CORE, TOKEN, SPAN,
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
assert positive["summary"]["declarations"] == len(positive_names) + 10
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "comment scan proof report changed across repeated runs"
verified = {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert positive_names | {"remaining", "after_one", "after_three", "column_after_three"} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert negative["summary"]["declarations"] == len(negative_names) + 10
assert {(item["kind"], item["name"]) for item in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert all(item["status"] == "disproved" and item["counterexample_found"]
           for item in negative["findings"])
assert require_current_product(BIN, PROVER) == product
if hashes_before != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}:
    raise SystemExit("comment proof inputs changed during replay")

print(json.dumps({
    "admitted": True,
    "scope": "line/block comment cursor bounds, strict progress, and source-linked three-byte delimiter offset/column updates",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
