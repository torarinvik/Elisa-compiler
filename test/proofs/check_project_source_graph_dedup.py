"""Replay source-bound file-table deduplication and edge-slot proofs."""
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
POSITIVE = HERE / "project_source_graph_dedup.elisa"
NEGATIVE = HERE / "project_source_graph_dedup_rejected.elisa"
SOURCE = ROOT / "src/driver/project_sources.elisa"
PROJECT = ROOT / "src/driver/project.elisa"
POSITIVE_NAMES = {
    "first_matching_source_row",
    "target_registration_after_lookup",
    "an_existing_path_reuses_its_first_slot",
    "a_missing_path_appends_a_valid_edge_slot",
}
NEGATIVE_NAMES = {
    "a_found_path_returns_the_append_sentinel",
    "a_missing_path_does_not_grow_the_file_table",
    "an_edge_to_a_new_path_is_out_of_bounds",
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


def source_errors(source_text: str, project_text: str) -> list[str]:
    errors = []
    try:
        lookup = compact(function_section(source_text, "source_graph_index_of"))
        discovery = compact(function_section(source_text, "discover_sources"))
        push = compact(function_section(project_text, "strlist_push"))
    except SystemExit as error:
        return [str(error)]

    lookup_steps = (
        "forindexin0..<files.starts.count|files,path|:",
        "indexreturnifstrlist_entry_equals(files,index,path)",
        "returnfiles.starts.count",
    )
    positions = [lookup.find(step) for step in lookup_steps]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        errors.append("source graph path lookup no longer returns the first exact match or the count sentinel")

    discovery_steps = (
        "slot:mutableusize=source_graph_index_of(&files,target)",
        "ifslot==files.starts.count:",
        "files<-strlist_push(files,target)",
        "graph.edges<-graph.edges.push(slot)",
    )
    positions = [discovery.find(step) for step in discovery_steps]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        errors.append("discovery no longer appends a path only on a miss before recording its edge")
    if discovery.count("source_graph_index_of(&files,target)") != 1:
        errors.append("discovery must use the matched graph slot for each include target")

    push_steps = (
        "list.starts<-list.starts.push(list.data.count)",
        "list.lengths<-list.lengths.push(value.count)",
        "forindexin0..<value.count|list,value|:",
    )
    positions = [push.find(step) for step in push_steps]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        errors.append("StrList insertion no longer advances start and length rows before copying path bytes")
    if push.count("list.starts<-list.starts.push(") != 1 or push.count("list.lengths<-list.lengths.push(") != 1:
        errors.append("StrList insertion must append exactly one start row and one length row")
    return errors


def validate_model() -> None:
    positive = POSITIVE.read_text()
    negative = NEGATIVE.read_text()
    lookup = compact(function_section(positive, "first_matching_source_row"))
    for fragment in (
        "ensuresresult<=matches.count",
        "ensuresresult<matches.countimpliesmatches[result]",
        "ensuresforallpriorin0..<result:notmatches[prior]",
        "invariantindex<=matches.count",
        "invariantforallpriorin0..<index:notmatches[prior]",
        "returnindexifmatches[index]",
        "returnmatches.count",
    ):
        if fragment not in lookup:
            raise SystemExit("first-match source graph lookup lost its range, exclusion, or miss contract")

    registration = compact(function_section(positive, "target_registration_after_lookup"))
    for fragment in (
        "requiresslot<=file_count",
        "ensuresresult.edge_target==slot",
        "ensuresresult.edge_target<result.files_after",
        "ensuresresult.files_after==file_countifslot<file_count",
        "ensuresresult.files_after==file_count+1.usize()ifslot==file_count",
    ):
        if fragment not in registration:
            raise SystemExit("graph target registration no longer proves reuse-or-append slot bounds")

    if declarations(POSITIVE) != POSITIVE_NAMES:
        raise SystemExit("project source graph positive proof inventory changed")
    if declarations(NEGATIVE) != NEGATIVE_NAMES or 'include "./project_source_graph_dedup.elisa"' not in negative:
        raise SystemExit("project source graph false-claim inventory changed")
    false_claims = (
        ("a_found_path_returns_the_append_sentinel", "returnfirst_matching_source_row(matches)==matches.count"),
        ("a_missing_path_does_not_grow_the_file_table", "returnregistration.files_after==matches.count"),
        ("an_edge_to_a_new_path_is_out_of_bounds", "returnregistration.edge_target>=registration.files_after"),
    )
    for name, expression in false_claims:
        body = compact(function_section(negative, name))
        if "ensuresresult==true" not in body or expression not in body:
            raise SystemExit(f"project source graph false claim changed: {name}")


source_text = SOURCE.read_text()
project_text = PROJECT.read_text()
errors = source_errors(source_text, project_text)
if errors:
    raise SystemExit("\n".join(errors))
validate_model()

# Reject loss of exact lookup, miss-only insertion, and aligned StrList metadata writes.
mutated_lookup = source_text.replace(
    "return index if strlist_entry_equals(files, index, path)", "index return", 1
)
if mutated_lookup == source_text or not source_errors(mutated_lookup, project_text):
    raise SystemExit("source gate failed to reject unconditional source graph lookup")
mutated_append = source_text.replace(
    "if slot == files.starts.count:", "if slot != files.starts.count:", 1
)
if mutated_append == source_text or not source_errors(mutated_append, project_text):
    raise SystemExit("source gate failed to reject appending on a graph lookup hit")
mutated_strlist = project_text.replace(
    "list.lengths <- list.lengths.push(value.count)", "pass", 1
)
if mutated_strlist == project_text or not source_errors(source_text, mutated_strlist):
    raise SystemExit("source gate failed to reject a StrList append with misaligned length rows")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("project source graph proofs require a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
    stage1_provenance, Path(__file__), POSITIVE, NEGATIVE, SOURCE, PROJECT,
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
assert positive == run(POSITIVE)[1], "project source graph proof report changed across repeated runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"]: row["kind"] for row in negative["findings"]} == {
    name: "ensure-unproven" for name in NEGATIVE_NAMES
}
assert negative["summary"]["unproven"] == len(NEGATIVE_NAMES)
assert negative == run(NEGATIVE)[1], "project source graph false-claim report changed across repeated runs"
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "project source graph proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "first exact path match, miss-only graph growth, and valid edge slots",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(NEGATIVE_NAMES),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
