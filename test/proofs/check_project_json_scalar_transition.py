"""Admit the JSON Unicode escape scalar/cursor transition against production source."""
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
PROJECT = ROOT / "src/driver/project.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
POSITIVE = HERE / "project_json_scalar_transition.elisa"
NEGATIVE = HERE / "project_json_scalar_transition_rejected.elisa"

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
json_at = compact(function_section(source, "json_at"))
json_at_steps = (
    "0returnifposition>=data.count",
    "returndata[position]",
)
positions = [json_at.find(step) for step in json_at_steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("Unicode escape byte probes no longer use sentinel access before indexing")

hex_digit = compact(function_section(source, "json_hex_digit"))
hex_digit_steps = (
    "(byte-48).i64()returnifbyte>=48andbyte<=57",
    "(byte-97+10).i64()returnifbyte>=97andbyte<=102",
    "(byte-65+10).i64()returnifbyte>=65andbyte<=70",
    "return-1",
)
positions = [hex_digit.find(step) for step in hex_digit_steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("Unicode low-unit input no longer rejects non-hex and truncated bytes")

scalar = compact(function_section(source, "json_unicode_escape_scalar"))
scalar_steps = (
    "iffirst>=55296andfirst<=56319andjson_at(data,cursor.position)==92andjson_at(data,cursor.position+1.usize())==117:",
    "low:i64=json_hex4(data,cursor.position+2.usize())",
    "iflow>=56320andlow<=57343:",
    "cursor.position<-cursor.position+6.usize()",
    "return65536+(first-55296)*1024+(low-56320)",
    "return65533iffirst>=55296andfirst<=57343",
    "returnfirst",
)
positions = [scalar.find(step) for step in scalar_steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("production Unicode decoding no longer combines only valid surrogate pairs and replaces isolated surrogates")

# The proof models the first and low code units as json_hex4 results, including
# its -1 invalid/truncated sentinel and the full four-digit u16 range.
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
    raise SystemExit("Unicode scalar proof inputs no longer come from the bounded four-hex-digit decoder")

for name, first_name, output in (
    ("json_parse_string", "first", "json_push_utf8(&out, code.u32())"),
    ("json_push_string_entry", "first_unit", "scalar: u32 = code.u32()"),
):
    decoder = compact(function_section(source, name))
    call_sequence = (
        "escape:u8=json_at(data,cursor.position+1.usize())",
        "cursor.position<-cursor.position+2.usize()",
        "elifescape==117:",
        f"{first_name}:i64=json_hex4(data,cursor.position)",
        f"if{first_name}<0:cursor.ok<-falsereturn" + ("out" if name == "json_parse_string" else ""),
        "cursor.position<-cursor.position+4.usize()",
        f"code:i64=json_unicode_escape_scalar(data,cursor,{first_name})",
        compact(output),
    )
    positions = [decoder.find(fragment) for fragment in call_sequence]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{name} no longer consumes one code unit before using the shared scalar transition")

# The scalar proof's four width ranges are bound to both production encoding
# paths, including the else branch's Unicode maximum established above.
for name, value in (("json_push_utf8", "code"), ("json_push_string_entry", "scalar")):
    encoder = compact(function_section(source, name))
    branch_steps = (
        f"if{value}<128:",
        f"elif{value}<2048:",
        f"elif{value}<65536:",
        "else:",
    )
    positions = [encoder.find(step) for step in branch_steps]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{name} no longer follows the proved ordered UTF-8 scalar width branches")

project_source = PROJECT.read_text()
if 'include "./project_json_parse.elisa"' not in project_source or \
        'include "./project.elisa"' not in DRIVER.read_text():
    raise SystemExit("proved JSON scalar decoder is no longer included by the compiler driver")

positive_names = {
    "json_unicode_scalar_transition",
    "json_unicode_cursor_delta",
    "json_unicode_escape_total_delta",
    "json_unicode_scalar_utf8_width",
}
negative_names = {
    "false_claim_isolated_high_surrogate_is_preserved",
    "false_claim_unpaired_surrogate_consumes_pair_bytes",
    "false_claim_max_scalar_uses_three_byte_branch",
}


def declaration_names(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


if declaration_names(POSITIVE) != positive_names:
    raise SystemExit("JSON scalar transition positive proof inventory changed")
if declaration_names(NEGATIVE) != negative_names or \
        'include "./project_json_scalar_transition.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("JSON scalar transition negative controls changed")

positive_text = compact(POSITIVE.read_text())
required_positive_shapes = (
    "requiresfirst>=0andfirst<=65535",
    "requireslow>=-1andlow<=65535",
    "result==(",
    "first>=55296andfirst<=56319andfollows_unicode_escapeandlow>=56320andlow<=57343",
    "65533iffirst>=55296andfirst<=57343elsefirst",
    "ensureresult>=0",
    "ensureresult<=1114111",
    "ensureresult<55296orresult>57343",
    "ensure(first>=55296andfirst<=57343andnot(first>=55296andfirst<=56319andfollows_unicode_escapeandlow>=56320andlow<=57343))impliesresult==65533",
    "return 65536 + (first - 55296) * 1024 + (low - 56320) if first >= 55296 and first <= 56319 and follows_unicode_escape and low >= 56320 and low <= 57343 else (65533 if first >= 55296 and first <= 57343 else first)",
    "ensure result == (6 if first >= 55296 and first <= 56319 and follows_unicode_escape and low >= 56320 and low <= 57343 else 0)",
    "ensure result == (12 if first >= 55296 and first <= 56319 and follows_unicode_escape and low >= 56320 and low <= 57343 else 6)",
    "ensure result >= 6 and result <= 12",
    "return 6 if first >= 55296 and first <= 56319 and follows_unicode_escape and low >= 56320 and low <= 57343 else 0",
    "return 12 if first >= 55296 and first <= 56319 and follows_unicode_escape and low >= 56320 and low <= 57343 else 6",
    "def json_unicode_scalar_utf8_width(code: i64) -> i64:",
    "requires code >= 0 and code <= 1114111",
    "ensure result == (1 if code < 128 else (2 if code < 2048 else (3 if code < 65536 else 4)))",
)
if not all(compact(shape) in positive_text for shape in required_positive_shapes):
    raise SystemExit("JSON scalar transition proof no longer states exact scalar and cursor-delta behavior")

negative_text = compact(NEGATIVE.read_text())
required_false_claims = (
    "deffalse_claim_isolated_high_surrogate_is_preserved(first:i64,follows_unicode_escape:bool,low:i64)->bool:requiresfirst==55296andnotfollows_unicode_escapeandlow>=-1andlow<=65535ensureresult==true",
    "deffalse_claim_unpaired_surrogate_consumes_pair_bytes(first:i64,follows_unicode_escape:bool,low:i64)->bool:requiresfirst==55296andnotfollows_unicode_escapeandlow>=-1andlow<=65535ensureresult==true",
    "return(6iffirst>=55296andfirst<=56319andfollows_unicode_escapeandlow>=56320andlow<=57343else0)==6",
    "deffalse_claim_max_scalar_uses_three_byte_branch(code:i64)->bool:requirescode==1114111ensureresult==truereturncode<65536",
)
if not all(compact(shape) in negative_text for shape in required_false_claims):
    raise SystemExit("JSON scalar transition negative controls no longer cover an isolated high surrogate")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("JSON scalar transition proofs require a strict proof build")

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
    PROJECT,
    DRIVER,
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
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "JSON scalar transition proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["obligations"] == negative["summary"]["proven"] + len(negative_names)
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "JSON Unicode scalar replacement/combination, UTF-16 escape cursor consumption, and scalar-to-UTF-8-width branch selection",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
