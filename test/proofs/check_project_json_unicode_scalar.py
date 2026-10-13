"""Admit source-linked proofs that JSON UTF-16 escapes produce valid Unicode scalars."""
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
POSITIVE = HERE / "project_json_unicode_scalar.elisa"
NEGATIVE = HERE / "project_json_unicode_scalar_rejected.elisa"
PROJECT = ROOT / "src/driver/project.elisa"
SOURCE = ROOT / "src/driver/project_json_parse.elisa"

POSITIVE_NAMES = {
    "production_hex4_result_is_invalid_or_within_u16",
    "every_production_escape_result_is_a_unicode_scalar",
    "the_maximum_surrogate_pair_decodes_to_the_maximum_scalar",
    "an_isolated_high_surrogate_decodes_to_replacement",
}
NEGATIVE_NAMES = {"an_isolated_surrogate_can_escape_unchanged"}
SPECIFIED_PRODUCTION_NAMES = {"json_hex_digit", "json_hex4", "json_unicode_escape_scalar"}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


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


source_text = SOURCE.read_text()
hex_digit = compact(function_section(source_text, "json_hex_digit"))
if "ensureresult==-1or(result>=0andresult<=15)" not in hex_digit:
    raise SystemExit("JSON hex-digit production contract no longer distinguishes invalid input from one nibble")

hex4 = compact(function_section(source_text, "json_hex4"))
for fragment in (
    "ensureresult==-1or(result>=0andresult<=65535)",
    "foroffsetin0..<4|value,data,position|:",
    "invariantoffset<=4.usize()",
    "invariantvalue>=0",
    "invariantoffset==0.usize()impliesvalue==0",
    "invariantoffset==1.usize()impliesvalue<=15",
    "invariantoffset==2.usize()impliesvalue<=255",
    "invariantoffset==3.usize()impliesvalue<=4095",
    "invariantoffset==4.usize()impliesvalue<=65535",
    "digit:i64=json_hex_digit(json_at(data,position+offset.usize()))",
    "-1returnifdigit<0",
    "value<-value*16+digit",
    "returnvalue",
):
    if fragment not in hex4:
        raise SystemExit(f"production four-hex-digit decoder lost its bounded fold invariant: {fragment}")

scalar = compact(function_section(source_text, "json_unicode_escape_scalar"))
for fragment in (
    "requiresfirst>=0andfirst<=65535",
    "ensureresult>=0",
    "ensureresult<=1114111",
    "ensureresult<55296orresult>57343",
    "iflow>=56320andlow<=57343:",
    "return65536+(first-55296)*1024+(low-56320)",
    "return65533iffirst>=55296andfirst<=57343",
    "returnfirst",
):
    if fragment not in scalar:
        raise SystemExit(f"production UTF-16 escape decoder lost its Unicode-scalar contract: {fragment}")

encoder = compact(function_section(source_text, "json_push_utf8"))
for fragment in (
    "requirescode<=1114111",
    "requirescode<55296orcode>57343",
    "ifcode<128:", "elifcode<2048:", "elifcode<65536:",
):
    if fragment not in encoder:
        raise SystemExit("production UTF-8 encoder no longer requires a Unicode scalar")

parse_string = compact(function_section(source_text, "json_parse_string"))
for fragment in (
    "first:i64=json_hex4(data,cursor.position)",
    "iffirst<0:",
    "code:i64=json_unicode_escape_scalar(data,cursor,first)",
    "json_push_utf8(&out,code.u32())",
):
    if fragment not in parse_string:
        raise SystemExit(f"JSON string decoding no longer checks or encodes the validated escape scalar: {fragment}")

list_string = compact(function_section(source_text, "json_push_string_entry"))
for fragment in (
    "first_unit:i64=json_hex4(data,cursor.position)",
    "iffirst_unit<0:",
    "code:i64=json_unicode_escape_scalar(data,cursor,first_unit)",
    "json_push_utf8(&list.data,code.u32())",
):
    if fragment not in list_string:
        raise SystemExit(f"project string-list decoding no longer shares the validated UTF-8 encoder: {fragment}")
if "list.data<-list.data.push((192+" in list_string or "list.data<-list.data.push((240+" in list_string:
    raise SystemExit("string-list Unicode decoding reintroduced a duplicate UTF-8 encoder")

positive = POSITIVE.read_text()
negative = NEGATIVE.read_text()
if 'include "../../src/driver/project.elisa"' not in positive:
    raise SystemExit("positive Unicode-scalar proofs no longer include the production project system")
if 'include "./project_json_unicode_scalar.elisa"' not in negative:
    raise SystemExit("Unicode-scalar false control no longer includes the source-linked positive proof")
if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("project JSON Unicode-scalar proof inventory changed")

for name, fragments in (
    ("production_hex4_result_is_invalid_or_within_u16", (
        "ProjectSystem::json_hex4(data, position)", "decoded == -1 or (decoded >= 0 and decoded <= 65535)",
    )),
    ("every_production_escape_result_is_a_unicode_scalar", (
        "requires first >= 0 and first <= 65535",
        "ProjectSystem::json_unicode_escape_scalar(data, &cursor, first)",
        "scalar >= 0 and scalar <= 1114111",
        "scalar < 55296 or scalar > 57343",
    )),
    ("the_maximum_surrogate_pair_decodes_to_the_maximum_scalar", (
        "ProjectSystem::json_unicode_escape_scalar(data, &cursor, 56319)",
        "scalar == 1114111 and cursor.position == 12.usize()",
    )),
    ("an_isolated_high_surrogate_decodes_to_replacement", (
        "ProjectSystem::json_unicode_escape_scalar(data, &cursor, 55296)",
        "scalar == 65533 and cursor.position == 0.usize()",
    )),
):
    body = compact(function_section(positive, name))
    if "ensureresult==true" not in body or any(compact(fragment) not in body for fragment in fragments):
        raise SystemExit(f"source-linked Unicode-scalar proof changed: {name}")
negative_body = compact(function_section(negative, "an_isolated_surrogate_can_escape_unchanged"))
if "ensureresult==true" not in negative_body or "scalar==56320" not in negative_body:
    raise SystemExit("false claim no longer challenges the isolated-surrogate replacement rule")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("project JSON Unicode-scalar proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")
stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
    stage1_provenance, Path(__file__), HERE / "proof_product_gate.py", SOURCE,
]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive_report = run(POSITIVE)
assert code == 0 and positive_report["status"] == positive_report["verification_state"] == "proved"
assert positive_report["summary"]["proven"] == positive_report["summary"]["obligations"]
assert not positive_report["findings"]
assert positive_report == run(POSITIVE)[1], "project JSON Unicode-scalar report changed across repeated runs"
verified = {row["name"] for row in positive_report["declaration_details"] if row.get("verified")}
assert (POSITIVE_NAMES | SPECIFIED_PRODUCTION_NAMES) <= verified

code, negative_report = run(NEGATIVE)
assert code == 1 and negative_report["status"] == negative_report["verification_state"] == "failed"
assert [(row["kind"], row["name"]) for row in negative_report["findings"]] == [
    ("ensure-unproven", "an_isolated_surrogate_can_escape_unchanged"),
]
negative_verified = {row["name"] for row in negative_report["declaration_details"] if row.get("verified")}
assert SPECIFIED_PRODUCTION_NAMES <= negative_verified
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "project JSON Unicode-scalar proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "source-bound JSON hex bounds, scalar decoding, and shared UTF-8 encoder preconditions",
    "positive_obligations": positive_report["summary"]["proven"],
    "false_claim_rejected": sorted(NEGATIVE_NAMES),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
