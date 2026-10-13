"""Replay source-bound exact-byte equality proofs for source graph paths."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
HERE = Path(__file__).resolve().parent
POSITIVE = HERE / "project_source_path_equality.elisa"
NEGATIVE = HERE / "project_source_path_equality_rejected.elisa"
PROJECT = ROOT / "src/driver/project.elisa"
SOURCE = ROOT / "src/driver/project_sources.elisa"
POSITIVE_NAMES = {
    "source_span_overlap_length",
    "bytes_span_copy_model",
    "span_copy_preserves_the_selected_bytes",
    "a_valid_span_copy_has_the_requested_length",
    "bytes_span_equal_model",
    "an_exact_stored_path_span_matches",
    "a_different_path_length_is_not_equal",
    "a_different_byte_inside_the_span_is_not_equal",
    "a_matching_prefix_does_not_match_a_longer_path",
}
NEGATIVE_NAMES = {
    "a_valid_span_copy_can_have_the_wrong_length",
    "different_lengths_can_compare_equal",
    "a_different_byte_can_compare_equal",
    "a_short_prefix_can_match_the_full_path",
}

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


def source_errors(project_text: str, source_text: str) -> list[str]:
    try:
        span_equal = compact(function_section(project_text, "bytes_span_equal"))
        span_copy = compact(function_section(project_text, "bytes_extend_span"))
        entry_equal = compact(function_section(project_text, "strlist_entry_equals"))
        lookup = compact(function_section(source_text, "source_graph_index_of"))
    except SystemExit as error:
        return [str(error)]
    span_steps = (
        "falsereturniflength!=right.count",
        "forindexin0..<length|left,right,left_start|:",
        "falsereturnifleft[left_start+index]!=right[index]",
        "returntrue",
    )
    positions = [span_equal.find(step) for step in span_steps]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        return ["production span equality no longer checks exact length then every corresponding byte"]
    copy_steps = (
        "forindexin0..<length|target,source,start|:",
        "target.push(source[start+index])",
    )
    positions = [span_copy.find(step) for step in copy_steps]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        return ["production span copy no longer appends the selected source bytes in order"]
    if entry_equal != compact("""
        def strlist_entry_equals(list: StrList&, index: usize, value: darray[u8]&) -> bool:
            return bytes_span_equal(list.data, list.starts[index], list.lengths[index], value)
    """):
        return ["StrList path equality no longer compares exactly the selected start/length span"]
    lookup_steps = (
        "forindexin0..<files.starts.count|files,path|:",
        "indexreturnifstrlist_entry_equals(files,index,path)",
        "returnfiles.starts.count",
    )
    positions = [lookup.find(step) for step in lookup_steps]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        return ["source graph lookup no longer deduplicates with exact StrList entry equality"]
    return []


def validate_model() -> None:
    positive = POSITIVE.read_text()
    negative = NEGATIVE.read_text()
    model = compact(function_section(positive, "bytes_span_equal_model"))
    copy_model = compact(function_section(positive, "bytes_span_copy_model"))
    for fragment in (
        "requiresstart<=source.count",
        "requireslength<=source.count-start",
        "ensuresresult.count==length",
        "ensuresforallindexin0..<length:result[index]==source[start+index]",
        "invariantindex<=length",
        "invariantout.count==index",
        "invariantforallpriorin0..<index:out[prior]==source[start+prior]",
        "out.push(source[start+index])",
    ):
        if fragment not in copy_model:
            raise SystemExit("span copy model lost its source bounds or exact-copy invariant")
    for fragment in (
        "requiresleft_start<=left.count",
        "requireslength<=left.count-left_start",
        "ensuresresult==(length==right.countand(forallindexin0..<source_span_overlap_length(length,right.count):left[left_start+index]==right[index]))",
        "falsereturniflength!=right.count",
        "invariantindex<=length",
        "invariantforallpriorin0..<index:left[left_start+prior]==right[prior]",
        "falsereturnifleft[left_start+index]!=right[index]",
    ):
        if fragment not in model:
            raise SystemExit("span equality model lost its exact-length, bounded-byte contract")
    overlap = compact(function_section(positive, "source_span_overlap_length"))
    if "ensuresresult<=left_lengthandresult<=right_length" not in overlap:
        raise SystemExit("span equality common-prefix bound no longer protects both byte arrays")
    if declarations(POSITIVE) != POSITIVE_NAMES:
        raise SystemExit("project source path equality positive proof inventory changed")
    if declarations(NEGATIVE) != NEGATIVE_NAMES or 'include "./project_source_path_equality.elisa"' not in negative:
        raise SystemExit("project source path equality false-claim inventory changed")
    for name, expression in (
        ("a_valid_span_copy_can_have_the_wrong_length", "returncopied.count!=length"),
        ("different_lengths_can_compare_equal", "returnbytes_span_equal_model(left,left_start,length,right)"),
        ("a_different_byte_can_compare_equal", "returnbytes_span_equal_model(left,left_start,length,right)"),
        ("a_short_prefix_can_match_the_full_path", "returnbytes_span_equal_model(stored,0.usize(),stored.count,requested)"),
    ):
        body = compact(function_section(negative, name))
        if "ensuresresult==true" not in body or expression not in body:
            raise SystemExit(f"project source path equality false claim changed: {name}")


project_text = PROJECT.read_text()
source_text = SOURCE.read_text()
errors = source_errors(project_text, source_text)
if errors:
    raise SystemExit("\n".join(errors))
validate_model()

# Mutation controls guard the length check, byte mismatch check, and selected span.
mutated_length = project_text.replace(
    "false return if length != right.count", "false return if length == right.count", 1
)
if mutated_length == project_text or not source_errors(mutated_length, source_text):
    raise SystemExit("source gate failed to reject accepting only unequal span lengths")
mutated_byte = project_text.replace(
    "left[left_start + index] != right[index]", "left[left_start + index] == right[index]", 1
)
if mutated_byte == project_text or not source_errors(mutated_byte, source_text):
    raise SystemExit("source gate failed to reject reversing the span byte comparison")
mutated_entry = project_text.replace(
    "list.lengths[index], value", "list.starts[index], value", 1
)
if mutated_entry == project_text or not source_errors(mutated_entry, source_text):
    raise SystemExit("source gate failed to reject comparing a path with the wrong span length")
mutated_copy = project_text.replace(
    "target.push(source[start + index])", "target.push(source[index])", 1
)
if mutated_copy == project_text or not source_errors(mutated_copy, source_text):
    raise SystemExit("source gate failed to reject a span copy that ignores its starting offset")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("project source path equality proofs require a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
    stage1_provenance, Path(__file__), POSITIVE, NEGATIVE, PROJECT, SOURCE,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert positive == run(POSITIVE)[1], "project source path equality report changed across repeated runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"]: row["kind"] for row in negative["findings"]} == {
    name: "ensure-unproven" for name in NEGATIVE_NAMES
}
assert negative["summary"]["unproven"] == len(NEGATIVE_NAMES)
assert negative == run(NEGATIVE)[1], "project source path equality false-claim report changed across repeated runs"
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "project source path equality proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact source-path span length and byte equality feeding graph deduplication",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(NEGATIVE_NAMES),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
