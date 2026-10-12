"""Replay the lexer suffix-width bound against the scanner and Token cast."""
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
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
CORE = ROOT / "src/lexer/lexer_core.elisa"
NUMBERS = ROOT / "src/lexer/lexer_numbers.elisa"
TOKEN = ROOT / "src/lexer/lexer_token.elisa"
POSITIVE = HERE / "lexer_suffix_probe_bound.elisa"
NEGATIVE = HERE / "lexer_suffix_probe_bound_rejected.elisa"

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
    return "\n".join(line for line in source[start:end].splitlines()
                      if not line.lstrip().startswith("#"))


core_text = CORE.read_text()
numbers_text = NUMBERS.read_text()
token_text = TOKEN.read_text()

valid_suffix = function_section(core_text, "valid_suffix")
expected_suffixes = (
    '"u" | "u8" | "u16" | "u32" | "u64" | "usize" | '
    '"i8" | "i16" | "i32" | "i64" | "isize" | "f32" | "f64" -> true'
)
if compact(expected_suffixes) not in compact(valid_suffix):
    raise SystemExit("lexer suffix whitelist changed; revisit the suffix-width bound")

suffix_wrapper = function_section(core_text, "read_type_suffix")
if compact(suffix_wrapper) != compact(
    "def read_type_suffix(lexer: lmut Lexer) -> sview?: return Lexer::read_type_suffix_at(lexer.source, lexer.source_length, lexer.position)"
):
    raise SystemExit("numeric suffix wrapper no longer calls the bounded source scanner")

reader = function_section(core_text, "read_type_suffix_at")
initial_probe = list(re.finditer(r"probe\s*:\s*mutable\s+usize\s*=\s*start\s*\+\s*1", reader))
if len(initial_probe) != 1:
    raise SystemExit("suffix reader no longer includes exactly one initial probe byte")
increment_pattern = (
    r"probe\s*<-\s*probe\s*\+\s*1\s+if\s+probe\s*<\s*source_length\s+and\s+char_at\(source,\s*source_length,\s*probe\)\.is_alphanumeric\(\)"
)
increments = list(re.finditer(increment_pattern, reader))
if len(increments) != 5:
    raise SystemExit("suffix reader no longer has exactly five guarded additional-byte steps")
probe_writes = [line.strip() for line in reader.splitlines()
                if re.match(r"probe\s*(?::|<-)", line.strip())]
if len(probe_writes) != 6 or sum(line.startswith("probe:") for line in probe_writes) != 1:
    raise SystemExit("suffix reader gained an unchecked probe update")
if re.search(r"\b(?:for|while)\b", reader):
    raise SystemExit("suffix reader gained an unbounded scan loop")
view_match = re.search(r"make_source_view\(source,\s*source_length,\s*start,\s*probe\)", reader)
valid_return = re.search(r"suffix\s+return\s+if\s+valid", reader)
if not view_match or not valid_return or not (
    initial_probe[0].start() < increments[0].start() < increments[-1].end()
    < view_match.start() < valid_return.start()
):
    raise SystemExit("suffix view no longer spans only the bounded, validated probe window")

number_reader = function_section(numbers_text, "read_number")
number_steps = (
    "text_end: usize = lexer.position",
    "rebind suffix: sview?, lexer = lexer.read_type_suffix()",
    "lexer.position <- text_end + suffix_text.len.usize()",
    "return Token(result_kind, position, start, text_end, lexer.position)",
)
number_text = compact(number_reader)
number_positions = [number_text.find(compact(fragment)) for fragment in number_steps]
if any(position < 0 for position in number_positions) or number_positions != sorted(number_positions):
    raise SystemExit("numeric token suffix span no longer follows the bounded reader in order")

if token_text.count("(suffix_end - text_end).u16()") != 1:
    raise SystemExit("Token suffix-length cast changed; revisit this proof")

positive_text = POSITIVE.read_text()
positive_shapes = {
    "suffix_probe_span_is_at_most_six": "def suffix_probe_span_is_at_most_six(additional_bytes: i64) -> bool: requires additional_bytes >= 0 and additional_bytes <= 5 ensure result == true return 1 + additional_bytes <= 6",
    "suffix_probe_span_fits_u16": "def suffix_probe_span_fits_u16(additional_bytes: i64) -> bool: requires additional_bytes >= 0 and additional_bytes <= 5 ensure result == true return 1 + additional_bytes <= 65535",
    "first_u16_overflow_exceeds_the_suffix_probe": "def first_u16_overflow_exceeds_the_suffix_probe(additional_bytes: i64) -> bool: requires additional_bytes >= 0 and additional_bytes <= 5 ensure result == true return 65536 > 1 + additional_bytes",
}
for name, expected in positive_shapes.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"{name} no longer proves the checked scanner bound")

negative_text = NEGATIVE.read_text()
if 'include "./lexer_suffix_probe_bound.elisa"' not in negative_text:
    raise SystemExit("overflow false control no longer imports the positive bound")
if compact(function_section(negative_text, "bounded_suffix_probe_can_overflow_u16")) != compact(
    "def bounded_suffix_probe_can_overflow_u16(additional_bytes: i64) -> bool: requires additional_bytes >= 0 and additional_bytes <= 5 ensure result == true return 1 + additional_bytes > 65535"
):
    raise SystemExit("u16 overflow false control changed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("lexer suffix bound requires a strict proof build")

inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, Path(__file__), CORE, NUMBERS, TOKEN, POSITIVE, NEGATIVE]
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
assert positive["summary"]["proven"] == positive["summary"]["obligations"] == 6
assert not positive["findings"]
verified = {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert set(positive_shapes) <= verified
assert positive == run(POSITIVE)[1], "suffix-width proof changed across repeated runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] == 7 and negative["summary"]["obligations"] == 8
assert [(item["kind"], item["name"]) for item in negative["findings"]] == [
    ("ensure-unproven", "bounded_suffix_probe_can_overflow_u16")
]
assert negative == run(NEGATIVE)[1], "suffix-width false control changed across repeated runs"

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
print(json.dumps({"admitted": True,
                  "scope": "bounded lexer suffix scan proves the Token u16 suffix-length cast input is representable",
                  "positive_obligations": positive["summary"]["proven"],
                  "false_claim_rejected": negative["findings"][0]["name"],
                  "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
                  "proof_revision": manifest["proof"].get("head"),
                  "compiler_revision": manifest["compiler"].get("source_revision"),
                  "sources_sha256": hashes_before}, sort_keys=True))
