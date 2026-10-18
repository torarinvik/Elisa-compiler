"""Replay source-bound ordered-choice proofs for project include resolution."""
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
POSITIVE = HERE / "project_include_resolution_order.elisa"
NEGATIVE = HERE / "project_include_resolution_order_rejected.elisa"
SOURCE = ROOT / "src/driver/project_sources.elisa"
POSITIVE_NAMES = {
    "first_configured_include_hit",
    "choose_include_candidate",
    "the_including_directory_wins_when_available",
    "first_configured_directory_is_selected",
    "no_candidate_means_not_found",
}
NEGATIVE_NAMES = {
    "a_configured_directory_beats_the_including_directory",
    "a_later_configured_directory_beats_the_first",
    "absent_include_candidates_produce_a_path",
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


def source_errors(source_text: str) -> list[str]:
    try:
        resolver = compact(function_section(source_text, "project_resolve_include_path"))
    except SystemExit as error:
        return [str(error)]
    ordered_steps = (
        "direct:darray[u8]=path_join(current_dir,include_path)",
        "directreturniffile_exists(direct)",
        "forindexin0..<include_dirs.starts.count|include_dirs,include_path|:",
        "base:darray[u8]=strlist_entry_copy(include_dirs,index)",
        "candidate:darray[u8]=path_join(base,include_path)",
        "candidatereturniffile_exists(candidate)",
        "empty:mutabledarray[u8]=[]",
        "returnempty",
    )
    positions = [resolver.find(step) for step in ordered_steps]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        return ["project include resolution no longer checks the local path, ordered configured paths, then empty fallback"]
    if resolver.count("candidatereturniffile_exists(candidate)") != 1:
        return ["each configured include candidate must return at its first successful directory"]
    return []


def validate_model() -> None:
    positive = POSITIVE.read_text()
    negative = NEGATIVE.read_text()
    hit_body = compact(function_section(positive, "first_configured_include_hit"))
    for fragment in (
        "ensuresresult<=available.count",
        "ensuresresult<available.countimpliesavailable[result]",
        "ensuresforallpriorin0..<result:notavailable[prior]",
        "invariantposition<=available.count",
        "invariantforallpriorin0..<position:notavailable[prior]",
        "returnpositionifavailable[position]",
    ):
        if fragment not in hit_body:
            raise SystemExit("first configured include search lost its bound or minimality invariant")

    choose_body = compact(function_section(positive, "choose_include_candidate"))
    for fragment in (
        "ensuresdirect_availableimpliesresult.foundandresult.index==0.usize()",
        "result.found==not(forallcandidatein0..<configured_available.count:notconfigured_available[candidate])",
        "configured_available[result.index-1.usize()]",
        "return(true,0.usize())",
        "first_configured_include_hit(configured_available)",
        "return(false,0.usize())ifconfigured_index==configured_available.count",
        "return(true,configured_index+1.usize())",
    ):
        if fragment not in choose_body:
            raise SystemExit("include candidate choice no longer states direct priority and earliest-hit behavior")

    if declarations(POSITIVE) != POSITIVE_NAMES:
        raise SystemExit("project include resolution positive proof inventory changed")
    if declarations(NEGATIVE) != NEGATIVE_NAMES or 'include "./project_include_resolution_order.elisa"' not in negative:
        raise SystemExit("project include resolution false-claim inventory changed")
    false_claims = (
        ("a_configured_directory_beats_the_including_directory", "returnselected.index==1.usize()"),
        ("a_later_configured_directory_beats_the_first", "returnselected.index==1.usize()"),
        ("absent_include_candidates_produce_a_path", "returnselected.found"),
    )
    for name, claim in false_claims:
        if "ensuresresult==true" not in compact(function_section(negative, name)) or claim not in compact(function_section(negative, name)):
            raise SystemExit(f"project include resolution false claim changed: {name}")


source_text = SOURCE.read_text()
errors = source_errors(source_text)
if errors:
    raise SystemExit("\n".join(errors))
validate_model()

# Confirm the source binding notices reversed precedence or reversed first-hit selection.
mutated_local = source_text.replace(
    "return direct if file_exists(direct)", "direct return if not file_exists(direct)", 1
)
if mutated_local == source_text or not source_errors(mutated_local):
    raise SystemExit("source gate failed to reject a reversed local-directory existence check")
mutated_candidate = source_text.replace(
    "return candidate if file_exists(candidate)", "candidate return if not file_exists(candidate)", 1
)
if mutated_candidate == source_text or not source_errors(mutated_candidate):
    raise SystemExit("source gate failed to reject a reversed configured-directory existence check")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("project include resolution proofs require a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
    stage1_provenance, Path(__file__), POSITIVE, NEGATIVE, SOURCE,
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
assert positive == run(POSITIVE)[1], "project include resolution report changed across repeated runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"]: row["kind"] for row in negative["findings"]} == {
    name: "ensure-unproven" for name in NEGATIVE_NAMES
}
assert negative["summary"]["unproven"] == len(NEGATIVE_NAMES)
assert negative == run(NEGATIVE)[1], "project include false-claim report changed across repeated runs"
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "project include resolution proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "local-directory priority, first configured include hit, and missing-path outcome",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(NEGATIVE_NAMES),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
