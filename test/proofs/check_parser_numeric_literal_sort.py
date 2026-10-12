"""Admit numeric literal sort metadata gates against the production parser path."""
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
MODEL = ROOT / "src/parser/parser_numeric_literal_sort_model.elisa"
SORT = ROOT / "src/parser/parser_numeric_literal_sort.elisa"
SUFFIX = ROOT / "src/parser/parser_numeric_suffix.elisa"
EXPR = ROOT / "src/parser/parser_expr.elisa"
TOKENS = ROOT / "src/lexer/tokens.elisa"
SOURCE_VIEW = ROOT / "src/lexer/source_view.elisa"
POSITIVE = HERE / "parser_numeric_literal_sort.elisa"
NEGATIVE = HERE / "parser_numeric_literal_sort_rejected.elisa"

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


def require_ordered(body: str, fragments: tuple[str, ...], label: str) -> None:
    text = compact(body)
    positions = [text.find(compact(fragment)) for fragment in fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{label} no longer follows the verified numeric-sort admission path")


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


model_text = MODEL.read_text()
if 'module ParserNumericLiteralSort:' not in model_text:
    raise SystemExit("numeric literal sort proof model module changed")
expected_helpers = {
    "accepts_integer_token": "def accepts_integer_token(is_integer: bool, is_hex: bool) -> bool: ensure result == (is_integer or is_hex) return is_integer or is_hex",
    "accepts_suffix": "def accepts_suffix(suffix: sview) -> bool: ensure result == (when suffix: \"u8\" | \"u16\" | \"u32\" | \"u64\" | \"usize\" | \"i8\" | \"i16\" | \"i32\" | \"i64\" | \"isize\" -> true _ -> false) return when suffix: \"u8\" | \"u16\" | \"u32\" | \"u64\" | \"usize\" | \"i8\" | \"i16\" | \"i32\" | \"i64\" | \"isize\" -> true _ -> false",
    "span_fits": "def span_fits(start: usize, length: usize, source_length: usize) -> bool: requires start < source_length ensure result == (length <= source_length - start) return length <= source_length - start",
    "span_end": "def span_end(start: usize, length: usize, source_length: usize) -> usize: requires start < source_length requires length <= source_length - start ensure result == start + length ensure result <= source_length return start + length",
}
for name, expected in expected_helpers.items():
    if compact(function_section(model_text, name)) != compact(expected):
        raise SystemExit(f"production numeric-sort predicate {name} changed")

if 'include "./parser_numeric_literal_sort_model.elisa"' not in SORT.read_text():
    raise SystemExit("production numeric-sort metadata helper no longer imports the proved predicates")
sort_body = function_section(SORT.read_text(), "record_numeric_literal_sort")
expected_sort_body = compact("""def record_numeric_literal_sort(parser: lmut Parser, token: Token, suffix: sview) -> void:
            return if not ParserNumericLiteralSort::accepts_integer_token(token.kind == TokenKind.IntLit, token.kind == TokenKind.HexLit)
            return if not ParserNumericLiteralSort::accepts_suffix(suffix)
            start: usize = token.start.usize()
            length: usize = token.length.usize()
            return if start >= parser.source_length
            return if length == 0
            return if not ParserNumericLiteralSort::span_fits(start, length, parser.source_length)
            span_end: usize = ParserNumericLiteralSort::span_end(start, length, parser.source_length)
            spelling: sview = Lexer::source_view_or_empty(parser.source, parser.source_length, start, span_end)
            parser.enum_annotations <- parser.enum_annotations.push(Ast::EnumAnnotation{owner: "__numeric_literal_sort", name: suffix, line: token.line})
            parser.enum_annotations <- parser.enum_annotations.push(Ast::EnumAnnotation{owner: "__numeric_literal_sort_column", name: suffix, line: token.column})
            parser.enum_annotations <- parser.enum_annotations.push(Ast::EnumAnnotation{owner: "__numeric_literal_sort_text", name: spelling, line: token.line})""")
if compact(sort_body) != expected_sort_body:
    raise SystemExit("numeric-sort annotation producer no longer matches the exact source-bound contract")

if 'include "./parser_numeric_literal_sort.elisa"' not in EXPR.read_text():
    raise SystemExit("parser expression unit no longer imports numeric-sort metadata production")
expected_suffix_producer = compact("""def record_numeric_suffix(parser: lmut Parser, token: Token) -> void:
            return if not token.flags.has_suffix or token.suffix_length == 0
            token_start: usize = token.start.usize()
            token_length: usize = token.length.usize()
            return if token_start >= parser.source_length
            return if token_length == 0
            return if not ParserNumericLiteralSort::span_fits(token_start, token_length, parser.source_length)
            suffix_start: usize = ParserNumericLiteralSort::span_end(token_start, token_length, parser.source_length)
            suffix_length: usize = token.suffix_length.usize()
            return if suffix_start >= parser.source_length
            return if not ParserNumericLiteralSort::span_fits(suffix_start, suffix_length, parser.source_length)
            suffix_end: usize = ParserNumericLiteralSort::span_end(suffix_start, suffix_length, parser.source_length)
            suffix: sview = Lexer::source_view_or_empty(parser.source, parser.source_length, suffix_start, suffix_end)
            parser.numeric_suffix_names <- parser.numeric_suffix_names.push(suffix)
            parser.numeric_suffix_lines <- parser.numeric_suffix_lines.push(token.line)
            parser <- parser.record_numeric_literal_sort(token, suffix)""")
if compact(function_section(SUFFIX.read_text(), "record_numeric_suffix")) != expected_suffix_producer:
    raise SystemExit("legacy suffix producer no longer derives and forwards the exact token suffix span")
expected_source_view = compact("""def source_view_or_empty(source: u8&, source_length: usize, start: usize, end: usize) -> sview:
            return get make_source_view(source, source_length, start, end) else empty_sview()""")
if compact(function_section(TOKENS.read_text(), "source_view_or_empty")) != expected_source_view:
    raise SystemExit("numeric suffix extraction no longer uses the bounded source-view projection")
expected_view_constructor = compact("""def make_source_view(source: u8&, source_length: usize, start: usize, end: usize) -> sview?:
            null return if start > end or end > source_length
            null return if end <= start
            trusted Unsafe.PointerCast:
                return source[start:end]""")
if compact(function_section(SOURCE_VIEW.read_text(), "make_source_view")) != expected_view_constructor:
    raise SystemExit("numeric suffix view no longer inherits the production source-span bounds check")
primary = function_section(EXPR.read_text(), "primary_literal")
require_ordered(primary, (
    "TokenKind.IntLit | TokenKind.HexLit:",
    "parser <- parser.record_numeric_suffix(token)",
    "TokenKind.FloatLit:",
), "literal parser suffix call sites")
suffix_call = compact("parser <- parser.record_numeric_suffix(token)")
suffix_positions = [match.start() for match in re.finditer(re.escape(suffix_call), compact(primary))]
if len(suffix_positions) != 2 or suffix_positions[1] < compact(primary).find(compact("TokenKind.FloatLit:")):
    raise SystemExit("integer and float literal branches no longer route suffix metadata through the same helper")

positive_shapes = {
    "integer_token_is_accepted": "def integer_token_is_accepted() -> bool: ensure result == true return ParserNumericLiteralSort::accepts_integer_token(true, false)",
    "hexadecimal_integer_token_is_accepted": "def hexadecimal_integer_token_is_accepted() -> bool: ensure result == true return ParserNumericLiteralSort::accepts_integer_token(false, true)",
    "float_token_is_not_accepted": "def float_token_is_not_accepted() -> bool: ensure result == true return not ParserNumericLiteralSort::accepts_integer_token(false, false)",
    "identifier_token_is_not_accepted": "def identifier_token_is_not_accepted() -> bool: ensure result == true return not ParserNumericLiteralSort::accepts_integer_token(false, false)",
    "token_kind_gate_matches_exact_integer_set": "def token_kind_gate_matches_exact_integer_set(is_integer: bool, is_hex: bool) -> bool: ensure result == true return ParserNumericLiteralSort::accepts_integer_token(is_integer, is_hex) == (is_integer or is_hex)",
    "every_supported_signed_or_unsigned_suffix_is_accepted": "def every_supported_signed_or_unsigned_suffix_is_accepted(suffix: sview) -> bool: requires suffix == \"u8\" or suffix == \"u16\" or suffix == \"u32\" or suffix == \"u64\" or suffix == \"usize\" or suffix == \"i8\" or suffix == \"i16\" or suffix == \"i32\" or suffix == \"i64\" or suffix == \"isize\" ensure result == true return ParserNumericLiteralSort::accepts_suffix(suffix)",
    "suffix_gate_matches_exact_width_whitelist": "def suffix_gate_matches_exact_width_whitelist(suffix: sview) -> bool: ensure result == true return ParserNumericLiteralSort::accepts_suffix(suffix) == (when suffix: \"u8\" | \"u16\" | \"u32\" | \"u64\" | \"usize\" | \"i8\" | \"i16\" | \"i32\" | \"i64\" | \"isize\" -> true _ -> false)",
    "u8_suffix_is_accepted": "def u8_suffix_is_accepted() -> bool: ensure result == true return ParserNumericLiteralSort::accepts_suffix(\"u8\")",
    "isize_suffix_is_accepted": "def isize_suffix_is_accepted() -> bool: ensure result == true return ParserNumericLiteralSort::accepts_suffix(\"isize\")",
    "span_strictly_inside_source_fits": "def span_strictly_inside_source_fits(start: usize, length: usize, source_length: usize) -> bool: requires start < source_length requires length <= source_length - start ensure result == true return ParserNumericLiteralSort::span_fits(start, length, source_length)",
    "admitted_text_span_end_does_not_exceed_source": "def admitted_text_span_end_does_not_exceed_source(start: usize, length: usize, source_length: usize) -> bool: requires start < source_length requires length <= source_length - start ensure result == true return start + length <= source_length",
    "proved_span_end_equals_start_plus_length": "def proved_span_end_equals_start_plus_length(start: usize, length: usize, source_length: usize) -> bool: requires start < source_length requires length <= source_length - start ensure result == true return ParserNumericLiteralSort::span_end(start, length, source_length) == start + length",
    "proved_span_end_stays_inside_source": "def proved_span_end_stays_inside_source(start: usize, length: usize, source_length: usize) -> bool: requires start < source_length requires length <= source_length - start ensure result == true return ParserNumericLiteralSort::span_end(start, length, source_length) <= source_length",
    "span_ending_at_source_end_fits": "def span_ending_at_source_end_fits(start: usize, source_length: usize) -> bool: requires start < source_length ensure result == true return ParserNumericLiteralSort::span_fits(start, source_length - start, source_length)",
    "adjacent_admitted_text_and_suffix_stay_in_source": "def adjacent_admitted_text_and_suffix_stay_in_source(start: usize, text_length: usize, suffix_length: usize, source_length: usize) -> bool: requires start < source_length requires text_length <= source_length - start requires start + text_length < source_length requires suffix_length <= source_length - (start + text_length) ensure result == true return start + text_length + suffix_length <= source_length",
    "span_beyond_source_does_not_fit": "def span_beyond_source_does_not_fit(start: usize, length: usize, source_length: usize) -> bool: requires start < source_length requires length > source_length - start ensure result == true return not ParserNumericLiteralSort::span_fits(start, length, source_length)",
}
negative_shapes = {
    "float_token_is_accepted": "def float_token_is_accepted() -> bool: ensure result == true return ParserNumericLiteralSort::accepts_integer_token(false, false)",
    "unsupported_u128_suffix_is_accepted": "def unsupported_u128_suffix_is_accepted() -> bool: ensure result == true return ParserNumericLiteralSort::accepts_suffix(\"u128\")",
    "signed_i8_suffix_is_rejected": "def signed_i8_suffix_is_rejected() -> bool: ensure result == true return not ParserNumericLiteralSort::accepts_suffix(\"i8\")",
    "out_of_source_span_is_accepted": "def out_of_source_span_is_accepted(start: usize, length: usize, source_length: usize) -> bool: requires start < source_length requires length > source_length - start ensure result == true return ParserNumericLiteralSort::span_fits(start, length, source_length)",
    "integer_gate_accepts_neither_kind": "def integer_gate_accepts_neither_kind() -> bool: ensure result == true return ParserNumericLiteralSort::accepts_integer_token(false, false) == true",
}
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    if declarations(path) != set(shapes):
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "../../src/parser/parser_numeric_literal_sort_model.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer includes the production numeric-sort predicates")
    for name, expected in shapes.items():
        if compact(function_section(path.read_text(), name)) != compact(expected):
            raise SystemExit(f"{name} no longer states the admitted numeric-sort theorem")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("numeric literal sort proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
    MODEL, SORT, SUFFIX, EXPR, TOKENS, SOURCE_VIEW,
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
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "numeric-sort proof report changed across repeated runs"
verified = {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert set(positive_shapes) | set(expected_helpers) <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert {(item["kind"], item["name"]) for item in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_shapes
}
assert all(item["status"] == "disproved" and item["counterexample_found"]
           for item in negative["findings"])
assert set(expected_helpers) <= {
    item["name"] for item in negative["declaration_details"] if item.get("verified")
}
assert require_current_product(BIN, PROVER) == product
if hashes_before != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}:
    raise SystemExit("numeric-sort proof inputs changed during replay")

print(json.dumps({
    "admitted": True,
    "scope": "integer/hex token admission, exact numeric suffix whitelist, and source span bounds for sort metadata",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_shapes),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
