"""Admit the lexer's source-slice boundary proof against a strict proof product."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
SOURCE = ROOT / "src/lexer/source_view.elisa"
TOKENS = ROOT / "src/lexer/tokens.elisa"
LEXER_TOKENS = ROOT / "src/lexer/lexer_tokens.elisa"
POSITIVE = HERE / "lexer_source_view_bounds.elisa"
NEGATIVE = HERE / "lexer_source_view_bounds_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def raw_function_body(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^[ \t]*def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(0).split("def", 1)[0]
    tail = source[match.end():]
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", tail)
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def function_body(source: str, name: str) -> str:
    section = raw_function_body(source, name)
    return "\n".join(line for line in section.splitlines()
                     if not line.lstrip().startswith("#"))


def source_file_function(path: Path, name: str) -> str:
    return function_body(path.read_text(), name)


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


constructor = function_body(SOURCE.read_text(), "make_source_view")
backing_assumption = "The caller supplies the readable byte extent for this pointer."
if backing_assumption not in SOURCE.read_text():
    raise SystemExit("source-view proof scope must identify source_length as a caller-supplied readable extent")
constructor_text = compact(constructor)
guards = (
    "def make_source_view(source: u8&, source_length: usize, start: usize, end: usize) -> sview?:",
    "null return if start > end or end > source_length",
    "null return if end <= start",
    "trusted Unsafe.PointerCast:",
    "return source[start:end]",
)
positions = [constructor_text.find(compact(fragment)) for fragment in guards]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("source-view constructor must reject reversed/out-of-extent and empty spans before slicing")
if constructor_text.count("returnsource[start:end]") != 1:
    raise SystemExit("expected exactly one raw source slice in the checked constructor")

token_text = TOKENS.read_text()
if not re.search(
    r"(?ms)^[ \t]*def source_view_or_empty\(source: u8&, source_length: usize, start: usize, end: usize\) -> sview:\s*"
    r"^[ \t]*return get make_source_view\(source, source_length, start, end\) else empty_sview\(\)",
    token_text,
):
    raise SystemExit("source-view fallback no longer routes through the bounded constructor")
for path, function, expected in (
    (TOKENS, "text", "return make_source_view(source, source_length, start, end)"),
    (TOKENS, "suffix", "return make_source_view(source, source_length, start, end)"),
    (LEXER_TOKENS, "view", "return make_source_view(lexer.source, lexer.source_length, start, end)"),
):
    if compact(expected) not in compact(source_file_function(path, function)):
        raise SystemExit(f"Lexer.{function} no longer routes source slicing through make_source_view")

# Both public Token accessors must receive the caller-supplied source extent and
# validate their requested spans against it. Check their explanatory comments in
# raw source; function_body intentionally strips comments for code-shape checks.
token_raw_source = TOKENS.read_text()
extent_comment = "The caller supplies the readable byte extent for this source."
token_bound_comment = "A token's computed end is only a requested span; it is never used as the bound."
identity_comments = (
    "The source pointer and length must be the same ones used to tokenize",
    "this stream. Extent validation alone cannot establish source/token identity.",
)
for name in ("text", "suffix"):
    token_accessor = source_file_function(TOKENS, name)
    if f"def {name}(token: Token&, source: u8&, source_length: usize)" not in token_accessor:
        raise SystemExit(f"Token.{name} must accept the actual source length")
    if compact("return make_source_view(source, source_length, start, end)") not in compact(token_accessor):
        raise SystemExit(f"Token.{name} no longer validates against the caller-supplied source extent")
    raw_accessor = raw_function_body(token_raw_source, name)
    if extent_comment not in raw_accessor or token_bound_comment not in raw_accessor or \
            any(comment not in raw_accessor for comment in identity_comments):
        raise SystemExit(f"Token.{name} must document source extent and token-source identity in raw source")

text_or_empty = source_file_function(TOKENS, "text_or_empty")
if "def text_or_empty(token: Token&, source: u8&, source_length: usize)" not in text_or_empty or \
        compact("token.text(source, source_length)") not in compact(text_or_empty):
    raise SystemExit("Token.text_or_empty must pass the caller-supplied source extent to Token.text")

raw_slices = []
for path in (ROOT / "src/lexer").glob("*.elisa"):
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        code = line.split("#", 1)[0]
        if re.search(r"\bsource\s*\[[^\]\n]*:[^\]\n]*\]", code):
            raw_slices.append((path, line_number, compact(code)))
if len(raw_slices) != 1 or raw_slices[0][0] != SOURCE.resolve() or \
        "source[start:end]" not in raw_slices[0][2]:
    raise SystemExit("all lexer source slices must pass through the single checked pointer boundary")

positive_names = {
    "source_view_guard_accepts",
    "valid_nonempty_source_span_is_admitted",
    "accepted_source_span_extent_fits_remaining_bytes",
    "token_self_bound_does_not_prove_backing_extent",
    "empty_source_span_is_rejected",
    "reversed_source_span_is_rejected",
    "source_span_past_end_is_rejected",
}
negative_names = {
    "accepted_source_span_can_exceed_remaining_bytes",
    "token_self_bound_guarantees_backing_extent",
    "empty_source_span_can_be_admitted",
    "reversed_source_span_can_be_admitted",
    "source_span_past_end_can_be_admitted",
}
if declarations(POSITIVE) != positive_names or declarations(NEGATIVE) != negative_names:
    raise SystemExit("source-view proof declaration inventory changed")
proof_backing_assumption = "arithmetic model assumes source points to at least source_length readable bytes."
if proof_backing_assumption not in POSITIVE.read_text():
    raise SystemExit("source-view proof must state its backing-storage assumption")
if "Token.text and Token.suffix do not establish that assumption" not in POSITIVE.read_text():
    raise SystemExit("source-view proof must exclude the self-bounded public Token accessors")

positive_claims = {
    "source_view_guard_accepts": (
        "def source_view_guard_accepts(start: usize, end: usize, source_length: usize) -> bool: "
        "ensure result implies start < end and end <= source_length "
        "ensure (start < end and end <= source_length) implies result "
        "accepted: bool = not (start > end or end > source_length) and not (end <= start) "
        "return accepted"
    ),
    "valid_nonempty_source_span_is_admitted": (
        "def valid_nonempty_source_span_is_admitted(start: usize, end: usize, source_length: usize) -> bool: "
        "requires start < end and end <= source_length ensure result == true "
        "return not (start > end or end > source_length) and not (end <= start)"
    ),
    "accepted_source_span_extent_fits_remaining_bytes": (
        "def accepted_source_span_extent_fits_remaining_bytes(start: usize, end: usize, source_length: usize) -> bool: "
        "requires source_view_guard_accepts(start, end, source_length) ensure result == true "
        "return start < source_length and end - start > 0 and end - start <= source_length - start"
    ),
    "token_self_bound_does_not_prove_backing_extent": (
        "def token_self_bound_does_not_prove_backing_extent(requested_end: usize, token_end: usize, backing_length: usize) -> bool: "
        "requires requested_end == token_end and token_end > backing_length ensure result == false "
        "return requested_end <= backing_length"
    ),
    "empty_source_span_is_rejected": (
        "def empty_source_span_is_rejected(start: usize, source_length: usize) -> bool: "
        "ensure result == false "
        "return not (start > start or start > source_length) and not (start <= start)"
    ),
    "reversed_source_span_is_rejected": (
        "def reversed_source_span_is_rejected(start: usize, end: usize, source_length: usize) -> bool: "
        "requires start > end "
        "ensure result == false "
        "return not (start > end or end > source_length) and not (end <= start)"
    ),
    "source_span_past_end_is_rejected": (
        "def source_span_past_end_is_rejected(start: usize, end: usize, source_length: usize) -> bool: "
        "requires end > source_length "
        "ensure result == false "
        "return not (start > end or end > source_length) and not (end <= start)"
    ),
}
for name, expected in positive_claims.items():
    if compact(function_body(POSITIVE.read_text(), name)) != compact(expected):
        raise SystemExit(f"{name} no longer proves its intended source-span condition")

negative_claims = {
    "accepted_source_span_can_exceed_remaining_bytes":
        "def accepted_source_span_can_exceed_remaining_bytes(start: usize, end: usize, source_length: usize) -> bool: "
        "requires source_view_guard_accepts(start, end, source_length) ensure result == true "
        "return end - start > source_length - start",
    "token_self_bound_guarantees_backing_extent":
        "def token_self_bound_guarantees_backing_extent(requested_end: usize, token_end: usize, backing_length: usize) -> bool: "
        "requires requested_end == token_end and token_end > backing_length ensure result == true "
        "return requested_end <= backing_length",
    "empty_source_span_can_be_admitted":
        "def empty_source_span_can_be_admitted(start: usize, source_length: usize) -> bool: ensure result == true return not (start > start or start > source_length) and not (start <= start)",
    "reversed_source_span_can_be_admitted":
        "def reversed_source_span_can_be_admitted(start: usize, end: usize, source_length: usize) -> bool: requires start > end ensure result == true return not (start > end or end > source_length) and not (end <= start)",
    "source_span_past_end_can_be_admitted":
        "def source_span_past_end_can_be_admitted(start: usize, end: usize, source_length: usize) -> bool: requires end > source_length ensure result == true return not (start > end or end > source_length) and not (end <= start)",
}
for name, expected in negative_claims.items():
    if compact(function_body(NEGATIVE.read_text(), name)) != compact(expected):
        raise SystemExit(f"{name} no longer challenges one source-view rejection case")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("source-view bounds proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, TOKENS, LEXER_TOKENS, POSITIVE, NEGATIVE,
]
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
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 15
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] == 10 and negative["summary"]["proven"] == 5
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}

assert require_current_product(BIN, PROVER) == product, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "source-view guard arithmetic relative to caller-supplied source_length, assuming that extent is readable; Token.text and Token.suffix self-bounds are explicitly not certified",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
