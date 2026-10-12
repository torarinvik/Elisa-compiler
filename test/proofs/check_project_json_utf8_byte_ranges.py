"""Admit byte-range proofs for the project's JSON UTF-8 encoder branches."""
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
UNICODE_PROOF = HERE / "project_json_unicode_bounds.elisa"
POSITIVE = HERE / "project_json_utf8_byte_ranges.elisa"
NEGATIVE = HERE / "project_json_utf8_byte_ranges_rejected.elisa"

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
encoder = compact(function_section(source_text, "json_push_utf8"))
encoder_order = (
    "ifcode<128:",
    "out.push(code.u8())",
    "elifcode<2048:",
    "out.push((192+(code/64)).u8())",
    "out.push((128+(code%64)).u8())",
    "elifcode<65536:",
    "out.push((224+(code/4096)).u8())",
    "out.push((128+((code/64)%64)).u8())",
    "out.push((128+(code%64)).u8())",
    "else:",
    "out.push((240+(code/262144)).u8())",
    "out.push((128+((code/4096)%64)).u8())",
    "out.push((128+((code/64)%64)).u8())",
    "out.push((128+(code%64)).u8())",
)
positions = []
cursor = 0
for fragment in encoder_order:
    position = encoder.find(fragment, cursor)
    positions.append(position)
    if position >= 0:
        cursor = position + len(fragment)
if any(position < 0 for position in positions):
    raise SystemExit("UTF-8 byte formulas no longer match the proved 1/2/3/4-byte codepoint ranges")
expected_occurrences = {
    "out.push((128+(code%64)).u8())": 3,
    "out.push((128+((code/64)%64)).u8())": 2,
}
if any(encoder.count(fragment) != count for fragment, count in expected_occurrences.items()):
    raise SystemExit("each UTF-8 output-byte formula must occur once in json_push_utf8")

# The list decoder has an allocation-free copy of the same encoder. Keep both code paths
# tied to the same byte-range contracts.
list_decoder = compact(function_section(source_text, "json_push_string_entry"))
list_encoder_order = (
    "ifscalar<128:",
    "list.data<-list.data.push(scalar.u8())",
    "elifscalar<2048:",
    "list.data<-list.data.push((192+(scalar/64)).u8())",
    "list.data<-list.data.push((128+(scalar%64)).u8())",
    "elifscalar<65536:",
    "list.data<-list.data.push((224+(scalar/4096)).u8())",
    "list.data<-list.data.push((128+((scalar/64)%64)).u8())",
    "list.data<-list.data.push((128+(scalar%64)).u8())",
    "else:",
    "list.data<-list.data.push((240+(scalar/262144)).u8())",
    "list.data<-list.data.push((128+((scalar/4096)%64)).u8())",
    "list.data<-list.data.push((128+((scalar/64)%64)).u8())",
    "list.data<-list.data.push((128+(scalar%64)).u8())",
)
cursor = 0
for fragment in list_encoder_order:
    position = list_decoder.find(fragment, cursor)
    if position < 0:
        raise SystemExit("allocation-free JSON string decoding diverged from the proved UTF-8 byte formulas")
    cursor = position + len(fragment)

scalar_decoder = compact(function_section(source_text, "json_unicode_escape_scalar"))
for fragment in (
    "iffirst>=55296andfirst<=56319andjson_at(data,cursor.position)==92andjson_at(data,cursor.position+1.usize())==117:",
    "low:i64=json_hex4(data,cursor.position+2.usize())",
    "iflow>=56320andlow<=57343:",
    "return65536+(first-55296)*1024+(low-56320)",
    "return65533iffirst>=55296andfirst<=57343",
):
    if fragment not in scalar_decoder:
        raise SystemExit("UTF-8 encoder input no longer receives the proven valid-pair or replacement scalar")
for name, first in (("json_parse_string", "first"), ("json_push_string_entry", "first_unit")):
    decoder = compact(function_section(source_text, name))
    if f"code:i64=json_unicode_escape_scalar(data,cursor,{first})" not in decoder:
        raise SystemExit(f"{name} no longer normalizes escaped UTF-16 code units before UTF-8 encoding")

if source_text.count("json_push_utf8(&out, code.u32())") != 1:
    raise SystemExit("expected one json_push_utf8 call, sourced from validated JSON escape decoding")

unicode_proofs = UNICODE_PROOF.read_text()
for name, shape in (
    ("four_hex_digits_fit_u16", "requires a >= 0 and a <= 15 requires b >= 0 and b <= 15 requires c >= 0 and c <= 15 requires d >= 0 and d <= 15 ensure result >= 0 ensure result <= 65535 return ((a * 16 + b) * 16 + c) * 16 + d"),
    ("surrogate_pair_is_unicode_scalar", "requires high >= 55296 and high <= 56319 requires low >= 56320 and low <= 57343 ensure result >= 65536 ensure result <= 1114111 return 65536 + (high - 55296) * 1024 + (low - 56320)"),
    ("replacement_character_uses_three_byte_encoding", "requires code == 65533 ensure result == true return code >= 2048 and code < 65536"),
    ("isolated_surrogate_selects_replacement", "requires first >= 55296 and first <= 57343 requires not paired ensure result == 65533 return 0 if paired else (65533 if first >= 55296 and first <= 57343 else first)"),
):
    if compact(shape) not in compact(function_section(unicode_proofs, name)):
        raise SystemExit(f"the codepoint input range proof changed: {name}")

positive_names = {
    "one_byte_fits", "two_byte_lead_fits", "two_byte_tail_fits",
    "three_byte_lead_fits", "three_byte_middle_fits", "three_byte_tail_fits",
    "four_byte_lead_fits", "four_byte_second_fits", "four_byte_third_fits",
    "four_byte_tail_fits",
}
negative_names = {"false_ascii_del_is_below_itself"}
for path, names in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != names:
        raise SystemExit(f"{path.name} proof declaration inventory changed")

positive_shapes = {
    "one_byte_fits": "requires code >= 0 and code < 128 ensure result >= 0 ensure result <= 127 return code",
    "two_byte_lead_fits": "requires code >= 128 and code < 2048 ensure result >= 194 ensure result <= 223 return 192 + code / 64",
    "two_byte_tail_fits": "requires code >= 128 and code < 2048 ensure result >= 128 ensure result <= 191 return 128 + code % 64",
    "three_byte_lead_fits": "requires code >= 2048 and code < 65536 ensure result >= 224 ensure result <= 239 return 224 + code / 4096",
    "three_byte_middle_fits": "requires code >= 2048 and code < 65536 ensure result >= 128 ensure result <= 191 return 128 + (code / 64) % 64",
    "three_byte_tail_fits": "requires code >= 2048 and code < 65536 ensure result >= 128 ensure result <= 191 return 128 + code % 64",
    "four_byte_lead_fits": "requires code >= 65536 and code <= 1114111 ensure result >= 240 ensure result <= 244 return 240 + code / 262144",
    "four_byte_second_fits": "requires code >= 65536 and code <= 1114111 ensure result >= 128 ensure result <= 191 return 128 + (code / 4096) % 64",
    "four_byte_third_fits": "requires code >= 65536 and code <= 1114111 ensure result >= 128 ensure result <= 191 return 128 + (code / 64) % 64",
    "four_byte_tail_fits": "requires code >= 65536 and code <= 1114111 ensure result >= 128 ensure result <= 191 return 128 + code % 64",
}
for name, shape in positive_shapes.items():
    if compact(shape) not in compact(function_section(POSITIVE.read_text(), name)):
        raise SystemExit(f"{name} no longer states its UTF-8 byte-range theorem")
if compact("requires code == 127 ensure result == true return code < 127") not in compact(function_section(NEGATIVE.read_text(), "false_ascii_del_is_below_itself")):
    raise SystemExit("false_ascii_del_is_below_itself no longer challenges the ASCII upper boundary")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("JSON UTF-8 byte-range proofs require a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, UNICODE_PROOF, POSITIVE, NEGATIVE,
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
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 30
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "project JSON UTF-8 byte report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["obligations"] == 32 and negative["summary"]["proven"] == 31
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in negative["findings"])
assert negative_names.isdisjoint({row["name"] for row in negative["declaration_details"] if row.get("verified")})
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "source-bound UTF-8 output byte formulas stay within their canonical one-to-four-byte ranges",
    "positive_obligations": positive["summary"]["proven"],
    "false_boundary_claim_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
