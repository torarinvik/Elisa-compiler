"""Admit source-bound fail-closed proofs for ProjectSystem JSON hex escapes."""
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
SOURCE = ROOT / "src/driver/project_json_parse.elisa"
POSITIVE = HERE / "project_json_hex4_bounds.elisa"
NEGATIVE = HERE / "project_json_hex4_bounds_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():], re.MULTILINE)
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


source = SOURCE.read_text()
at = compact(function_section(source, "json_at"))
if "0returnifposition>=data.count" not in at or "returndata[position]" not in at:
    raise SystemExit("JSON byte access no longer returns a sentinel before indexing past data.count")

hex_digit = compact(function_section(source, "json_hex_digit"))
hex_digit_steps = (
    "(byte-48).i64()returnifbyte>=48andbyte<=57",
    "(byte-97+10).i64()returnifbyte>=97andbyte<=102",
    "(byte-65+10).i64()returnifbyte>=65andbyte<=70",
    "return-1",
)
positions = [hex_digit.find(step) for step in hex_digit_steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("JSON hex classifier must reject the zero sentinel and every non-hex byte")

hex4 = compact(function_section(source, "json_hex4"))
hex4_steps = (
    "foroffsetin0..<4|value,data,position|:",
    "digit:i64=json_hex_digit(json_at(data,position+offset.usize()))",
    "-1returnifdigit<0",
    "value<-value*16+digit",
    "returnvalue",
)
positions = [hex4.find(step) for step in hex4_steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("four-digit JSON escapes must fail immediately on a bad/truncated nibble before accumulating")

positive_names = {
    "json_at_model",
    "json_hex_digit_model",
    "out_of_bounds_json_byte_is_zero",
    "json_hex4_model",
}
negative_names = {
    "false_claim_zero_byte_is_a_decimal_hex_digit",
    "false_claim_invalid_nibble_decodes_to_a_value",
    "false_claim_maximum_hex_quad_is_below_65535",
}


def declaration_names(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


if declaration_names(POSITIVE) != positive_names:
    raise SystemExit("JSON hex4 proof declaration inventory changed")
if declaration_names(NEGATIVE) != negative_names or \
        'include "./project_json_hex4_bounds.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("JSON hex4 negative controls changed")

positive_text = compact(POSITIVE.read_text())
positive_models = (
    "requires data_length >= 0 and position >= 0 and stored_byte >= 0 and stored_byte <= 255 ensure result == (0 if position >= data_length else stored_byte) return 0 if position >= data_length else stored_byte",
    "requires byte >= 0 and byte <= 255 ensure result == (byte - 48 if byte >= 48 and byte <= 57 else (byte - 87 if byte >= 97 and byte <= 102 else (byte - 55 if byte >= 65 and byte <= 70 else -1))) return byte - 48 if byte >= 48 and byte <= 57 else (byte - 87 if byte >= 97 and byte <= 102 else (byte - 55 if byte >= 65 and byte <= 70 else -1))",
    "requires data_length >= 0 and position >= data_length and stored_byte >= 0 and stored_byte <= 255 ensure result == 0 return 0 if position >= data_length else stored_byte",
    "requires a >= -1 and a <= 15 requires b >= -1 and b <= 15 requires c >= -1 and c <= 15 requires d >= -1 and d <= 15 ensure result == (-1 if a < 0 or b < 0 or c < 0 or d < 0 else ((a * 16 + b) * 16 + c) * 16 + d) ensure (a < 0 or b < 0 or c < 0 or d < 0) implies result == -1 ensure (a >= 0 and b >= 0 and c >= 0 and d >= 0) implies result == ((a * 16 + b) * 16 + c) * 16 + d ensure (a >= 0 and a <= 15 and b >= 0 and b <= 15 and c >= 0 and c <= 15 and d >= 0 and d <= 15) implies (result >= 0 and result <= 65535) return -1 if a < 0 or b < 0 or c < 0 or d < 0 else ((a * 16 + b) * 16 + c) * 16 + d",
)
if not all(compact(model) in positive_text for model in positive_models):
    raise SystemExit("JSON hex4 proofs no longer state the fail-closed sentinel and accumulator laws")

negative_text = compact(NEGATIVE.read_text())
negative_models = (
    "requires byte == 0 ensure result == true return byte >= 48 and byte <= 57",
    "requires nibble == -1 ensure result == true return nibble >= 0 and ((1 * 16 + nibble) * 16 + 2) * 16 + 3 >= 0",
    "ensure result == true return ((15 * 16 + 15) * 16 + 15) * 16 + 15 <= 65534",
)
if not all(compact(model) in negative_text for model in negative_models):
    raise SystemExit("JSON hex4 false claims no longer challenge the sentinel or range boundaries")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("ProjectSystem JSON hex4 proofs require a strict proof build")

compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    SOURCE,
    POSITIVE,
    NEGATIVE,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert report["summary"]["semantic_diagnostics"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 11
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "JSON hex4 proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["obligations"] == 17 and negative["summary"]["proven"] == 14
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", "false_claim_zero_byte_is_a_decimal_hex_digit"),
    ("ensure-unproven", "false_claim_invalid_nibble_decodes_to_a_value"),
    ("ensure-unproven", "false_claim_maximum_hex_quad_is_below_65535"),
}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "bounded JSON byte access, invalid/truncated hexadecimal escape rejection, and u16 accumulation bounds",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
