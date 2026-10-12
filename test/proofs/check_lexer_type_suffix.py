"""Admit the exact type-suffix grammar used by the production lexer."""
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
HELPER = ROOT / "src/lexer/lexer_type_suffix.elisa"
CORE = ROOT / "src/lexer/lexer_core.elisa"
LEXER = ROOT / "src/lexer/lexer.elisa"
POSITIVE = HERE / "lexer_type_suffix.elisa"
NEGATIVE = HERE / "lexer_type_suffix_rejected.elisa"

SUPPORTED = (
    "u", "u8", "u16", "u32", "u64", "usize",
    "i8", "i16", "i32", "i64", "isize", "f32", "f64",
)


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


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


helper_text = HELPER.read_text()
core_text = CORE.read_text()
lexer_text = LEXER.read_text()
helper = compact(function_section(helper_text, "is_valid_type_suffix"))
exact_predicate = " or ".join(f'suffix == "{spelling}"' for spelling in SUPPORTED)
if compact(f"ensure result == ({exact_predicate})") not in helper:
    raise SystemExit("production suffix contract no longer characterizes the complete accepted set")
match_patterns = " | ".join(f'"{spelling}"' for spelling in SUPPORTED)
match_decision = f"return match suffix: {match_patterns}: true _: false"
if compact(match_decision) not in helper:
    raise SystemExit("production suffix decision no longer pattern-matches the exact closed set")
if 'include "./lexer_type_suffix.elisa"' not in core_text:
    raise SystemExit("lexer core no longer imports the proved suffix grammar")
if 'include "./lexer_core.elisa"' not in lexer_text:
    raise SystemExit("production lexer no longer imports the scanner that uses the proved suffix grammar")
valid_suffix = compact(function_section(core_text, "valid_suffix"))
if compact("return LexerTypeSuffix::is_valid_type_suffix(view)") not in valid_suffix:
    raise SystemExit("lexer valid_suffix wrapper no longer delegates to the proved predicate")
reader = compact(function_section(core_text, "read_type_suffix_at"))
reader_steps = (
    "first: char = char_at(source, source_length, start)",
    "null return if not (first == 'u' or first == 'i' or first == 'f')",
    "probe: mutable usize = start + 1",
    "match make_source_view(source, source_length, start, probe):",
    "valid: bool = Lexer::valid_suffix(suffix)",
    "suffix return if valid",
)
reader_positions = [reader.find(compact(step)) for step in reader_steps]
if any(position < 0 for position in reader_positions) or reader_positions != sorted(reader_positions):
    raise SystemExit("bounded suffix reader no longer gates, spans, and validates in source order")
if "valid:bool=Lexer::valid_suffix(suffix)" not in reader:
    raise SystemExit("bounded suffix reader no longer validates with the proved predicate")
if "valid:bool=when suffix:" in reader:
    raise SystemExit("bounded suffix reader regained a duplicate suffix table")
positive_text = POSITIVE.read_text()
exact_proof = (
    f"def type_suffix_predicate_is_exact(suffix: sview) -> bool: "
    f"ensure result == ({exact_predicate}) "
    "return LexerTypeSuffix::is_valid_type_suffix(suffix)"
)
if compact(function_section(positive_text, "type_suffix_predicate_is_exact")) != compact(exact_proof):
    raise SystemExit("universal proof no longer states the exact production suffix grammar")
accepted_calls = " and ".join(f'LexerTypeSuffix::is_valid_type_suffix("{spelling}")' for spelling in SUPPORTED)
accepted_proof = (
    "def every_supported_type_suffix_is_accepted() -> bool: "
    "ensure result == true "
    f"return {accepted_calls}"
)
if compact(function_section(positive_text, "every_supported_type_suffix_is_accepted")) != compact(accepted_proof):
    raise SystemExit("accepted-spelling proof no longer covers every supported suffix")

negative_shapes = {
    "unsupported_i_width_is_accepted": 'return LexerTypeSuffix::is_valid_type_suffix("i34")',
    "unsupported_u_width_is_accepted": 'return LexerTypeSuffix::is_valid_type_suffix("u128")',
    "uppercase_float_suffix_is_accepted": 'return LexerTypeSuffix::is_valid_type_suffix("F32")',
    "suffixed_float_name_is_accepted": 'return LexerTypeSuffix::is_valid_type_suffix("f32x")',
}
negative_text = NEGATIVE.read_text()
for name, conclusion in negative_shapes.items():
    expected = f"def {name}() -> bool: ensure result == true {conclusion}"
    if compact(function_section(negative_text, name)) != compact(expected):
        raise SystemExit(f"{name} no longer asserts the intended unsupported spelling")

positive_names = {
    "type_suffix_predicate_is_exact",
    "every_supported_type_suffix_is_accepted",
}
negative_names = {
    "unsupported_i_width_is_accepted",
    "unsupported_u_width_is_accepted",
    "uppercase_float_suffix_is_accepted",
    "suffixed_float_name_is_accepted",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "../../src/lexer/lexer_type_suffix.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer includes the production suffix predicate")

inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    Path(__file__), HERE / "proof_product_gate.py", HELPER, CORE, POSITIVE, NEGATIVE,
    LEXER,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("type-suffix proof requires a strict proof build")
compiler = manifest["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs.extend((stage1_product, stage1_provenance))
inputs = list(dict.fromkeys(inputs))
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
assert positive == run(POSITIVE)[1], "suffix proof report changed across identical runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
rejected = {row["name"] for row in negative["findings"] if row["kind"] == "ensure-unproven"}
assert rejected == negative_names
assert negative == run(NEGATIVE)[1], "suffix false-control report changed across identical runs"

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "the production numeric suffix predicate accepts exactly 13 integer and float suffix spellings; bounded suffix reading delegates validation to it",
    "positive_obligations": positive["summary"]["proven"],
    "unsupported_spellings_rejected": sorted(rejected),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
