"""Admit arithmetic bounds for the project's JSON Unicode escape decoder."""
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
SOURCE = ROOT / "src/driver/project_json_parse.elisa"
POSITIVE = HERE / "project_json_unicode_bounds.elisa"
NEGATIVE = HERE / "project_json_unicode_bounds_rejected.elisa"

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
    return source[start:end]


source_text = SOURCE.read_text()
hex_digit = compact(function_section(source_text, "json_hex_digit"))
hex_digit_order = (
    "(byte-48).i64()returnifbyte>=48andbyte<=57",
    "(byte-97+10).i64()returnifbyte>=97andbyte<=102",
    "(byte-65+10).i64()returnifbyte>=65andbyte<=70",
    "return-1",
)
positions = [hex_digit.find(fragment) for fragment in hex_digit_order]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("JSON hex-digit decoding must preserve decimal/lowercase/uppercase ranges and reject other bytes")

hex4 = compact(function_section(source_text, "json_hex4"))
hex4_order = (
    "foroffsetin0..<4|value,data,position|:",
    "digit:i64=json_hex_digit(json_at(data,position+offset.usize()))",
    "-1returnifdigit<0",
    "value<-value*16+digit",
    "returnvalue",
)
positions = [hex4.find(fragment) for fragment in hex4_order]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("four-digit JSON escapes must reject invalid nibbles and update the accumulator in base 16")

scalar = compact(function_section(source_text, "json_unicode_escape_scalar"))
scalar_order = (
    "iffirst>=55296andfirst<=56319andjson_at(data,cursor.position)==92andjson_at(data,cursor.position+1.usize())==117:",
    "low:i64=json_hex4(data,cursor.position+2.usize())",
    "iflow>=56320andlow<=57343:",
    "cursor.position<-cursor.position+6.usize()",
    "return65536+(first-55296)*1024+(low-56320)",
    "return65533iffirst>=55296andfirst<=57343",
    "returnfirst",
)
positions = [scalar.find(fragment) for fragment in scalar_order]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("Unicode escape decoding must combine valid surrogate pairs and replace every unpaired surrogate")

for name, first_name in (("json_parse_string", "first"), ("json_push_string_entry", "first_unit")):
    decoder = compact(function_section(source_text, name))
    ordered = (
        f"{first_name}:i64=json_hex4(data,cursor.position)",
        f"code:i64=json_unicode_escape_scalar(data,cursor,{first_name})",
        "json_push_utf8(&out,code.u32())" if name == "json_parse_string" else "scalar:u32=code.u32()",
    )
    positions = [decoder.find(fragment) for fragment in ordered]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{name} no longer uses the shared Unicode scalar decoder")

positive_names = {
    "decimal_hex_nibble", "lower_hex_nibble", "upper_hex_nibble",
    "four_hex_digits_fit_u16", "surrogate_pair_is_unicode_scalar",
    "replacement_character_uses_three_byte_encoding",
    "isolated_surrogate_selects_replacement",
}
negative_names = {
    "false_digit_nine_is_at_most_eight", "false_max_hex_is_below_u16",
    "false_max_scalar_is_smaller",
}
for path, names in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != names:
        raise SystemExit(f"{path.name} proof declaration inventory changed")

positive_shapes = {
    "decimal_hex_nibble": "requires byte >= 48 and byte <= 57 ensure result >= 0 ensure result <= 9 return byte - 48",
    "lower_hex_nibble": "requires byte >= 97 and byte <= 102 ensure result >= 10 ensure result <= 15 return byte - 97 + 10",
    "upper_hex_nibble": "requires byte >= 65 and byte <= 70 ensure result >= 10 ensure result <= 15 return byte - 65 + 10",
    "four_hex_digits_fit_u16": "requires a >= 0 and a <= 15 requires b >= 0 and b <= 15 requires c >= 0 and c <= 15 requires d >= 0 and d <= 15 ensure result >= 0 ensure result <= 65535 return ((a * 16 + b) * 16 + c) * 16 + d",
    "surrogate_pair_is_unicode_scalar": "requires high >= 55296 and high <= 56319 requires low >= 56320 and low <= 57343 ensure result >= 65536 ensure result <= 1114111 return 65536 + (high - 55296) * 1024 + (low - 56320)",
    "replacement_character_uses_three_byte_encoding": "requires code == 65533 ensure result == true return code >= 2048 and code < 65536",
    "isolated_surrogate_selects_replacement": "requires first >= 55296 and first <= 57343 requires not paired ensure result == 65533 return 0 if paired else (65533 if first >= 55296 and first <= 57343 else first)",
}
for name, shape in positive_shapes.items():
    if compact(shape) not in compact(function_section(POSITIVE.read_text(), name)):
        raise SystemExit(f"{name} no longer proves its JSON Unicode arithmetic bound")

negative_shapes = {
    "false_digit_nine_is_at_most_eight": "requires byte == 57 ensure result == true return byte - 48 <= 8",
    "false_max_hex_is_below_u16": "requires a == 15 and b == 15 and c == 15 and d == 15 ensure result == true return ((a * 16 + b) * 16 + c) * 16 + d <= 65534",
    "false_max_scalar_is_smaller": "requires high == 56319 and low == 57343 ensure result == true return 65536 + (high - 55296) * 1024 + (low - 56320) <= 1114110",
}
for name, shape in negative_shapes.items():
    if compact(shape) not in compact(function_section(NEGATIVE.read_text(), name)):
        raise SystemExit(f"{name} no longer challenges the exact boundary")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("project JSON Unicode proofs require a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
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
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 19
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "project JSON Unicode report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["obligations"] == 25 and negative["summary"]["proven"] == 22
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in negative["findings"])
assert negative_names.isdisjoint({row["name"] for row in negative["declaration_details"] if row.get("verified")})
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "JSON hex escapes fit u16, valid surrogate pairs map into the Unicode scalar range, and unpaired surrogates map to U+FFFD",
    "positive_obligations": positive["summary"]["proven"],
    "false_boundary_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
