"""Admit source-linked proofs of ProjectSystem's exact whitespace byte set."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "project_whitespace.elisa"
NEGATIVE = HERE / "project_whitespace_rejected.elisa"
CONTROL_BYTES = HERE / "project_whitespace_control_bytes.elisa"
PROJECT = ROOT / "src/driver/project.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
JSON_PARSER = ROOT / "src/driver/project_json_parse.elisa"

EXPECTED_VALUES = {
    "ASCII_SPACE": 32,
    "ASCII_HORIZONTAL_TAB": 9,
    "ASCII_LINE_FEED": 10,
    "ASCII_CARRIAGE_RETURN": 13,
}
EXPECTED_NAMES = tuple(EXPECTED_VALUES)

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return " ".join(text.split())


project_text = PROJECT.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
function_marker = "def bytes_is_space(byte: u8) -> bool:"
if function_marker not in project_text:
    raise SystemExit("production project whitespace predicate is missing")
function_body = project_text.split(function_marker, 1)[1].split("# First index that is not whitespace", 1)[0]
expected_contract = compact("ensure result == ( " + " or ".join(
    f"byte == ProjectSystemWhitespaceByte::{name}" for name in EXPECTED_NAMES
) + " )")
if expected_contract not in compact(function_body):
    raise SystemExit("production predicate contract does not state its exact named byte set")
expected_return = (
    "return ( "
    + " or ".join(f"byte == ProjectSystemWhitespaceByte::{name}" for name in EXPECTED_NAMES)
    + " )"
)
if expected_return not in compact(function_body):
    raise SystemExit("production predicate no longer checks the exact named byte set")
def function_body(name: str, signature: str) -> str:
    if signature not in project_text:
        raise SystemExit(f"production project helper is missing: {name}")
    return project_text.split(signature, 1)[1].split("\n    def ", 1)[0]


trim_start_body = function_body(
    "bytes_trim_start", "def bytes_trim_start(value: darray[u8]&) -> usize:"
)
trim_end_body = function_body(
    "bytes_trim_end", "def bytes_trim_end(value: darray[u8]&) -> usize:"
)
blank_body = function_body(
    "bytes_is_blank", "def bytes_is_blank(value: darray[u8]&) -> bool:"
)
trimmed_body = function_body(
    "bytes_trimmed", "def bytes_trimmed(value: darray[u8]&) -> darray[u8]:"
)
extend_span_body = function_body(
    "bytes_extend_span",
    "def bytes_extend_span(target: mutable darray[u8]&, source: darray[u8]&, start: usize, length: usize) -> void:",
)
extend_view_body = function_body(
    "bytes_extend_view", "def bytes_extend_view(target: mutable darray[u8]&, text: sview) -> void:"
)
strlist_extend_body = function_body(
    "strlist_extend", "def strlist_extend(target: lmut StrList, source: StrList&) -> void:"
)
equal_view_body = function_body(
    "bytes_equal_view", "def bytes_equal_view(value: darray[u8]&, text: sview) -> bool:"
)
default_body = function_body(
    "bytes_or_default",
    "def bytes_or_default(value: darray[u8]&, fallback: sview) -> darray[u8]:",
)
for fragment in (
    "ensure result <= value.count",
    "ensure forall prefix in 0..<result: bytes_is_space(value[prefix])",
    "ensure result < value.count implies not bytes_is_space(value[result])",
    "while first < value.count and bytes_is_space(value[first])",
    "decreases value.count - first",
    "invariant first <= value.count",
    "invariant forall prefix in 0..<first: bytes_is_space(value[prefix])",
    "first <- first + 1.usize()",
    "return first",
):
    if compact(fragment) not in compact(trim_start_body):
        raise SystemExit(f"production leading trim no longer has its bounded first-nonspace scan: {fragment}")
for fragment in (
    "ensure result >= bytes_trim_start(value)",
    "ensure result <= value.count",
    "ensure forall suffix in result..<value.count: bytes_is_space(value[suffix])",
    "ensure result > bytes_trim_start(value) implies not bytes_is_space(value[result - 1.usize()])",
    "first: usize = bytes_trim_start(value)",
    "while last > first and bytes_is_space(value[last - 1.usize()])",
    "decreases last - first",
    "invariant first <= last",
    "invariant first == bytes_trim_start(value)",
    "invariant last <= value.count",
    "invariant forall suffix in last..<value.count: bytes_is_space(value[suffix])",
    "last <- last - 1.usize()",
    "return last",
):
    if compact(fragment) not in compact(trim_end_body):
        raise SystemExit(f"production trailing trim no longer preserves the nonspace interval: {fragment}")
if compact("return bytes_trim_start(value) == value.count") not in compact(blank_body):
    raise SystemExit("production blank predicate no longer uses the leading trim boundary")
if compact("can Memory.Allocate, Abort.Panic:") not in compact(strlist_extend_body) or \
        compact("target <- strlist_push_span(target, source.data, source.starts[index], source.lengths[index])") \
        not in compact(strlist_extend_body):
    raise SystemExit("production StrList extension no longer grants the span-copy effects explicitly")
for fragment in (
    "start: usize = bytes_trim_start(value)",
    "end: usize = bytes_trim_end(value)",
    "bytes_extend_span(&out, value, start, end - start)",
    "return out",
):
    if compact(fragment) not in compact(trimmed_body):
        raise SystemExit(f"production byte trimming no longer copies its computed interval: {fragment}")
if "def production_trim_interval_is_bounded(value: darray[u8]&) -> bool:" not in positive_text:
    raise SystemExit("positive proof no longer checks bounds of the production trim interval")
if "start <= end and end <= value.count" not in compact(positive_text.split("def production_trim_interval_is_bounded", 1)[1]):
    raise SystemExit("trim interval proof no longer requires ordered in-bounds endpoints")
for name, required in (
    ("production_trim_interval_is_bounded", (
        "ensure result == true", "start <= end and end <= value.count",
    )),
    ("production_trim_boundaries_match_the_whitespace_spec", (
        "ensure result == true",
        "ProjectSystem::bytes_trim_start(value)",
        "ProjectSystem::bytes_trim_end(value)",
        "forall prefix in 0..<start", "start < value.count implies",
        "forall suffix in end..<value.count", "end > start implies",
    )),
    ("production_trimmed_value_is_exactly_its_source_span", (
        "ensure result == true",
        "return false if start > end or end > value.count",
        "ProjectSystem::bytes_trimmed(value)",
        "trimmed.count == end - start",
        "trimmed[index] == value[start + index]",
    )),
):
    if f"def {name}(" not in positive_text:
        raise SystemExit(f"production trim proof is missing: {name}")
    body = positive_text.split(f"def {name}(", 1)[1].split("\ndef ", 1)[0]
    if any(fragment not in body for fragment in required):
        raise SystemExit(f"production trim proof contract changed: {name}")
for name, claim in (
    ("trim_start_can_exceed_the_source_length", "ProjectSystem::bytes_trim_start(value) > value.count"),
    ("trim_end_can_exceed_the_source_length", "ProjectSystem::bytes_trim_end(value) > value.count"),
    ("trim_end_can_precede_trim_start", "ProjectSystem::bytes_trim_end(value) < ProjectSystem::bytes_trim_start(value)"),
    ("trim_start_can_skip_a_non_whitespace_first_byte", "ProjectSystem::bytes_trim_start(value) > 0.usize()"),
    ("trim_end_can_leave_a_non_whitespace_last_byte", "ProjectSystem::bytes_trim_end(value) < value.count"),
    ("a_nonblank_trimmed_value_can_lose_all_bytes", "trimmed.count == 0.usize()"),
):
    marker = f"def {name}("
    if marker not in negative_text:
        raise SystemExit(f"trim interval false-claim control is missing: {name}")
    body = negative_text.split(marker, 1)[1].split("\ndef ", 1)[0]
    if "ensure result == true" not in body or claim not in body:
        raise SystemExit(f"trim interval false-claim control changed: {name}")
for fragment in (
    "for index in 0..<length |target, source, start|",
    "target.push(source[start + index])",
):
    if compact(fragment) not in compact(extend_span_body):
        raise SystemExit(f"production span copy no longer preserves each selected byte: {fragment}")
for fragment in (
    "if bytes_is_blank(value):",
    "bytes_extend_view(&out, fallback)",
    "return out",
    "bytes_extend(&out, value)",
):
    if compact(fragment) not in compact(default_body):
        raise SystemExit(f"production project default no longer selects the blank fallback: {fragment}")
for fragment in (
    "length: i64 = text.len.i64()",
    "for index in 0..<length |target, text|",
    "target.push(text[index])",
):
    if compact(fragment) not in compact(extend_view_body):
        raise SystemExit(f"production view copy no longer preserves fallback bytes: {fragment}")
for fragment in (
    "false return if value.count.i64() != text.len.i64()",
    "for index in 0..<value.count |value, text|",
    "false return if value[index] != text[index.i64()]",
    "return true",
):
    if compact(fragment) not in compact(equal_view_body):
        raise SystemExit(f"production view equality no longer checks the exact byte sequence: {fragment}")
for name, value in EXPECTED_VALUES.items():
    if not re.search(rf"\b{name}: u8 = {value}\b", project_text):
        raise SystemExit(f"missing or changed named byte constant: {name} = {value}")
if 'include "../../src/driver/project.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer includes the production project system")
if 'include "./project.elisa"' not in DRIVER.read_text():
    raise SystemExit("compiler driver no longer imports the proved project system")
if not re.search(r"bytes_is_space\(data\[cursor\.position\]\)", JSON_PARSER.read_text()):
    raise SystemExit("project JSON parser no longer uses the proved whitespace predicate")
if not all(f"ProjectSystemWhitespaceByte::{name}" in positive_text for name in EXPECTED_NAMES):
    raise SystemExit("positive proof does not cover every named production whitespace byte")


def include_closure(roots: list[Path]) -> list[Path]:
    include = re.compile(r'^\s*include\s+"([^"]+)"', re.MULTILINE)
    pending = list(roots)
    seen: set[Path] = set()
    while pending:
        path = pending.pop().resolve(strict=True)
        if path in seen:
            continue
        seen.add(path)
        for relative in include.findall(path.read_text()):
            child = (path.parent / relative).resolve(strict=True)
            if child not in seen:
                pending.append(child)
    return sorted(seen)


try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("project whitespace proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    MANIFEST,
    MANIFEST_CHECKSUM,
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    CONTROL_BYTES,
    DRIVER,
    JSON_PARSER,
    *include_closure([POSITIVE, NEGATIVE, PROJECT]),
]
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


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "positive proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {
    "bytes_is_space",
    "production_predicate_matches_its_exact_byte_set",
    "all_project_whitespace_bytes_are_recognized",
    "nearby_ascii_controls_are_not_project_whitespace",
    "non_space_singleton_is_preserved_by_project_trimming",
    "whitespace_singleton_trims_to_blank",
    "surrounding_project_whitespace_preserves_the_middle_byte",
    "blank_project_value_uses_the_fallback",
    "nonblank_project_value_is_preserved",
    "bytes_trim_start",
    "bytes_trim_end",
    "production_trim_interval_is_bounded",
    "production_trim_boundaries_match_the_whitespace_spec",
    "production_trimmed_value_is_exactly_its_source_span",
} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "vertical_tab_is_project_whitespace"),
    ("ensure-unproven", "form_feed_is_project_whitespace"),
    ("ensure-unproven", "exclamation_mark_is_project_whitespace"),
    ("ensure-unproven", "a_non_space_singleton_can_be_blank"),
    ("ensure-unproven", "blank_project_value_can_ignore_fallback"),
    ("ensure-unproven", "trim_start_can_exceed_the_source_length"),
    ("ensure-unproven", "trim_end_can_exceed_the_source_length"),
    ("ensure-unproven", "trim_end_can_precede_trim_start"),
    ("ensure-unproven", "trim_start_can_skip_a_non_whitespace_first_byte"),
    ("ensure-unproven", "trim_end_can_leave_a_non_whitespace_last_byte"),
    ("ensure-unproven", "a_nonblank_trimmed_value_can_lose_all_bytes"),
]
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
assert subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                      check=True, capture_output=True, text=True).stdout.strip() == compiler_head
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "project whitespace predicate, trim boundaries, and blank-value defaults",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [row["name"] for row in negative["findings"]],
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
