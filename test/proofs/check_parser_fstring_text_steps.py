"""Admit source-bound f-string scanner transitions, spans, and depth invariants."""
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
SOURCE = ROOT / "src/parser/parser_expr_fstring.elisa"
TOKENS = ROOT / "src/lexer/tokens.elisa"
SOURCE_VIEW = ROOT / "src/lexer/source_view.elisa"
POSITIVE = HERE / "parser_fstring_text_steps.elisa"
NEGATIVE = HERE / "parser_fstring_text_steps_rejected.elisa"
DEPTH_POSITIVE = HERE / "parser_fstring_depth_invariant.elisa"
DEPTH_NEGATIVE = HERE / "parser_fstring_depth_invariant_rejected.elisa"

POSITIVE_SHAPES = {
    "text_double_open_stays_text": (
        "requires state == FS_TEXT and character == F_LBRACE and has_next and next_character == F_LBRACE "
        "ensure result.state == FS_TEXT ensure result.depth == depth ensure result.advance == 2 "
        "return (state: FS_TEXT, depth: depth, advance: 2)"
    ),
    "text_double_close_stays_text": (
        "requires state == FS_TEXT and character == F_RBRACE and has_next and next_character == F_RBRACE "
        "ensure result.state == FS_TEXT ensure result.depth == depth ensure result.advance == 2 "
        "return (state: FS_TEXT, depth: depth, advance: 2)"
    ),
    "text_backslash_skips_two": (
        "requires state == FS_TEXT and character == F_BACKSLASH "
        "ensure result.state == FS_TEXT ensure result.depth == depth ensure result.advance == 2 "
        "return (state: FS_TEXT, depth: depth, advance: 2)"
    ),
    "text_lone_open_enters_expression": (
        "requires state == FS_TEXT and character == F_LBRACE "
        "requires not (has_next and next_character == F_LBRACE) "
        "ensure result.state == FS_EXPR ensure result.depth == 1 ensure result.advance == 1 "
        "return (state: FS_EXPR, depth: 1, advance: 1)"
    ),
    "text_double_open_retains_first_brace_span": (
        "requires chunk_start <= index and index + 1 < end "
        "ensure result.literal_end == index + 1 "
        "ensure result.literal_end < end "
        "ensure result.reopened == index + 2 "
        "ensure result.next_index == result.reopened "
        "return (literal_end: index + 1, reopened: index + 2, next_index: index + 2)"
    ),
    "text_double_close_retains_first_brace_span": (
        "requires chunk_start <= index and index + 1 < end "
        "ensure result.literal_end == index + 1 "
        "ensure result.literal_end < end "
        "ensure result.reopened == index + 2 "
        "ensure result.next_index == result.reopened "
        "return (literal_end: index + 1, reopened: index + 2, next_index: index + 2)"
    ),
}
NEGATIVE_SHAPES = {
    "false_claim_text_backslash_advances_one": (
        "requires state == FS_TEXT and character == F_BACKSLASH "
        "ensure result.advance == 1 return (state: FS_TEXT, depth: depth, advance: 2)"
    ),
    "false_claim_double_open_advances_one": (
        "requires state == FS_TEXT and character == F_LBRACE and has_next and next_character == F_LBRACE "
        "ensure result.advance == 1 return (state: FS_TEXT, depth: depth, advance: 2)"
    ),
    "false_claim_lone_open_stays_text": (
        "requires state == FS_TEXT and character == F_LBRACE "
        "requires not (has_next and next_character == F_LBRACE) "
        "ensure result.state == FS_TEXT return (state: FS_EXPR, depth: 1, advance: 1)"
    ),
}

DEPTH_SHAPES = {
    "interpolation_open_establishes_cursor_depth_bound": (
        "ensure result.depth == 1 ensure result.consumed == 0 "
        "ensure result.depth >= 1 and result.depth <= result.consumed + 1 "
        "return (depth: 1, consumed: 0)"
    ),
    "expression_open_preserves_cursor_depth_bound": (
        "requires depth >= 1 and consumed >= 0 and depth <= consumed + 1 "
        "requires consumed < 9223372036854775805 "
        "ensure result.depth >= 1 ensure result.depth <= result.consumed + 1 "
        "return (depth: depth + 1, consumed: consumed + 1)"
    ),
    "expression_nested_close_preserves_cursor_depth_bound": (
        "requires depth > 1 and consumed >= 0 and depth <= consumed + 1 "
        "requires consumed < 9223372036854775805 "
        "ensure result.depth >= 1 ensure result.depth <= result.consumed + 1 "
        "return (depth: depth - 1, consumed: consumed + 1)"
    ),
    "expression_other_preserves_cursor_depth_bound": (
        "requires depth >= 1 and consumed >= 0 and depth <= consumed + 1 "
        "requires consumed < 9223372036854775805 "
        "ensure result.depth >= 1 ensure result.depth <= result.consumed + 1 "
        "return (depth: depth, consumed: consumed + 1)"
    ),
    "inner_string_escape_preserves_cursor_depth_bound": (
        "requires depth >= 1 and consumed >= 0 and depth <= consumed + 1 "
        "requires consumed < 9223372036854775804 "
        "ensure result.depth >= 1 ensure result.depth <= result.consumed + 1 "
        "return (depth: depth, consumed: consumed + 2)"
    ),
    "inner_string_other_preserves_cursor_depth_bound": (
        "requires depth >= 1 and consumed >= 0 and depth <= consumed + 1 "
        "requires consumed < 9223372036854775805 "
        "ensure result.depth >= 1 ensure result.depth <= result.consumed + 1 "
        "return (depth: depth, consumed: consumed + 1)"
    ),
}
DEPTH_NEGATIVE_SHAPES = {
    "false_claim_nested_close_can_zero_depth": (
        "requires depth > 1 and consumed >= 0 and depth <= consumed + 1 "
        "requires consumed < 9223372036854775805 "
        "ensure result == 0 return depth - 1"
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


scanner = compact(function_section(SOURCE.read_text(), "fstring_expression"))
flush_chunk = compact(function_section(SOURCE.read_text(), "fstring_flush_chunk"))
span_view = compact(function_section(SOURCE.read_text(), "fstring_span_view"))
span_pos = compact(function_section(SOURCE.read_text(), "fstring_span_pos"))
token_view = compact(function_section(TOKENS.read_text(), "source_view_or_empty"))
source_view_constructor = compact(function_section(SOURCE_VIEW.read_text(), "make_source_view"))
text_branch_start = scanner.find("iffs_state==fs_text:")
expr_branch_start = scanner.find("eliffs_state==fs_expr:")
text_branch = scanner[text_branch_start:expr_branch_start]
first_expr_else = scanner.find("else:", expr_branch_start)
outer_string_else = scanner.find("else:", first_expr_else + len("else:"))
if expr_branch_start < 0 or first_expr_else < 0 or outer_string_else < 0:
    raise SystemExit("could not isolate f-string expression and inner-string scanner states")
expr_branch = scanner[expr_branch_start:outer_string_else]
string_branch = scanner[outer_string_else:]
required_scanner = (
    "start_offset:usize=token.start.usize()",
    "end_offset:usize=start_offset+token.length.usize()",
    "fs_text:i64=0",
    "fs_expr:i64=1",
    "fs_string:i64=2",
    "fs_state:mutablei64=fs_text",
    "while scan_index<end_offset",
    "ch:i64=parser.source[scan_index].char()",
    "if fs_state==fs_text:",
    "if ch=='{' and scan_index+1<end_offset and parser.source[scan_index+1].char()=='{':",
    "parser.fstring_flush_chunk(token,chunk_start,scan_index+1,arguments)",
    "chunk_start<-scan_index+2scan_index<-scan_index+2",
    "elif ch=='}' and scan_index+1<end_offset and parser.source[scan_index+1].char()=='}':",
    "elif ch=='\\\\':scan_index<-scan_index+2",
    "elif ch=='{':",
    "scan_index<-scan_index+1expr_start<-scan_indexdepth<-1fs_state<-fs_expr",
    "else:scan_index<-scan_index+1",
)
positions = [scanner.find(compact(fragment)) for fragment in required_scanner]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("f-string literal scanner state, guarded lookahead, or branch order changed")
if text_branch.count("scan_index+1<end_offset") != 2 or \
        text_branch.count("parser.source[scan_index+1].char()") != 2:
    raise SystemExit("each doubled-brace lookahead must be bounded by the token end")
if text_branch.count("scan_index<-scan_index+2") != 3 or \
        text_branch.count("chunk_start<-scan_index+2") != 2:
    raise SystemExit("text brace pairs and escapes must consume two bytes and reopen chunk spans after brace pairs")
if text_branch.count("scan_index<-scan_index+1") != 2:
    raise SystemExit("a lone interpolation opener and ordinary text must each advance once")
required_expr = (
    "ifch=='{':scan_index<-scan_index+1depth<-depth+1",
    "elifch=='}'anddepth==1:parser<-parser.fstring_close_interp(token,expr_start,scan_index,arguments,chunk_start)canGlobal{Read,Write}scan_index<-scan_index+1fs_state<-fs_text",
    "elifch=='}':scan_index<-scan_index+1depth<-depth-1",
    "elifch=='\"':scan_index<-scan_index+1fs_state<-fs_string",
    "else:scan_index<-scan_index+1",
)
expr_positions = [expr_branch.find(fragment) for fragment in required_expr]
if any(position < 0 for position in expr_positions) or expr_positions != sorted(expr_positions):
    raise SystemExit("expression mode must open/increase, close/decrease, quote-switch, and otherwise advance in order")
if expr_branch.count("scan_index<-scan_index+1") != 5 or \
        expr_branch.count("depth<-depth+1") != 1 or expr_branch.count("depth<-depth-1") != 1:
    raise SystemExit("every expression character must advance once and only nested braces may change depth")
required_string = (
    "ifch=='\\\\':scan_index<-scan_index+2",
    "elifch=='\"':scan_index<-scan_index+1fs_state<-fs_expr",
    "else:scan_index<-scan_index+1",
)
string_positions = [string_branch.find(fragment) for fragment in required_string]
if any(position < 0 for position in string_positions) or string_positions != sorted(string_positions):
    raise SystemExit("inner strings must skip escapes, return on quote, and preserve depth for other bytes")
if string_branch.count("scan_index<-scan_index+2") != 1 or \
        string_branch.count("scan_index<-scan_index+1") != 2 or "depth<-" in string_branch:
    raise SystemExit("inner-string transitions must preserve expression depth and advance by one or two bytes")
if "arguments.push((Ast::Expr.StringLit(parser.fstring_span_view(token,chunk_start,end),parser.fstring_span_pos(token,chunk_start,end))))ifend>chunk_start" not in flush_chunk:
    raise SystemExit("literal chunks must preserve their checked half-open source span")
if "returnLexer::source_view_or_empty(parser.source,parser.source_length,span_start,span_end)" not in span_view:
    raise SystemExit("f-string chunks must route raw spans through the checked source-view constructor")
if "returngetmake_source_view(source,source_length,start,end)elseempty_sview()" not in token_view:
    raise SystemExit("source_view_or_empty must route f-string chunk spans through make_source_view")
if "returnAst::Pos{line:token.line,column:token.column,offset:span_start,end_line:token.line,end_column:token.column+(span_end-span_start).u32(),end_offset:span_end}" not in span_pos:
    raise SystemExit("f-string chunk positions must retain the raw span endpoints")
source_view_guards = (
    "nullreturnifstart>endorend>source_length",
    "nullreturnifend<=start",
    "trustedUnsafe.PointerCast:",
    "returnsource[start:end]",
)
source_view_positions = [source_view_constructor.find(fragment) for fragment in source_view_guards]
if any(position < 0 for position in source_view_positions) or source_view_positions != sorted(source_view_positions):
    raise SystemExit("raw f-string chunks must pass both source-span guards before pointer slicing")
if source_view_constructor.count("returnsource[start:end]") != 1:
    raise SystemExit("expected a single checked raw source slice")

token_text = TOKENS.read_text()
if not re.search(r"(?m)^\s{12}start: mutable u32$", token_text) or \
        not re.search(r"(?m)^\s{12}length: mutable u32$", token_text):
    raise SystemExit("f-string token offsets are no longer stored in the checked u32 token span")

positive_names = set(POSITIVE_SHAPES)
negative_names = set(NEGATIVE_SHAPES)
depth_names = set(DEPTH_SHAPES)
depth_negative_names = set(DEPTH_NEGATIVE_SHAPES)
if declarations(POSITIVE) != positive_names or declarations(NEGATIVE) != negative_names or \
        declarations(DEPTH_POSITIVE) != depth_names or declarations(DEPTH_NEGATIVE) != depth_negative_names:
    raise SystemExit("f-string scanner proof inventory is incomplete or contains extras")

for path, shapes in ((POSITIVE, POSITIVE_SHAPES), (NEGATIVE, NEGATIVE_SHAPES),
                     (DEPTH_POSITIVE, DEPTH_SHAPES), (DEPTH_NEGATIVE, DEPTH_NEGATIVE_SHAPES)):
    proof_text = path.read_text()
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(proof_text, name)):
            raise SystemExit(f"{name} no longer proves its intended literal-text transition")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("f-string text-step proofs require a strict proof build")

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
    SOURCE_VIEW,
    POSITIVE,
    NEGATIVE,
    DEPTH_POSITIVE,
    DEPTH_NEGATIVE,
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
assert positive["summary"]["declarations"] == len(positive_names) + 7
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 45
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names) + 7
assert negative["summary"]["obligations"] == 53 and negative["summary"]["proven"] == 49
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

code, depth_positive = run(DEPTH_POSITIVE)
assert code == 0 and depth_positive["status"] == depth_positive["verification_state"] == "proved"
assert depth_positive["summary"]["declarations"] == len(depth_names)
assert depth_positive["summary"]["obligations"] == depth_positive["summary"]["proven"] == 19
assert not depth_positive["findings"]
assert {row["name"] for row in depth_positive["declaration_details"] if row.get("verified")} == depth_names

code, depth_negative = run(DEPTH_NEGATIVE)
assert code == 1 and depth_negative["status"] == "failed"
assert depth_negative["summary"]["declarations"] == len(depth_names) + len(depth_negative_names)
assert depth_negative["summary"]["obligations"] == 21 and depth_negative["summary"]["proven"] == 20
assert {row["name"] for row in depth_negative["findings"]} == depth_negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in depth_negative["findings"])
assert not depth_negative_names & {row["name"] for row in depth_negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "source-bound f-string text transitions, raw spans, and one-step expression/string depth invariants",
    "positive_obligations": positive["summary"]["proven"] + depth_positive["summary"]["proven"],
    "false_transition_claims_refused": sorted(negative_names | depth_negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
