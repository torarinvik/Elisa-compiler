"""Admit the source-bound same-call alias path-overlap proof."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
HELPER = ROOT / "src/semantic/check_call_argument_exclusivity_paths.elisa"
CONSUMER = ROOT / "src/semantic/check_call_argument_exclusivity.elisa"
FACADE = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "call_argument_exclusivity_paths.elisa"
NEGATIVE = HERE / "call_argument_exclusivity_paths_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^[ \t]*(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one production function named {name}")
    match = matches[0]
    indent = len(match.group(0)) - len(match.group(0).lstrip(" "))
    following = re.search(
        rf"(?m)^[ \t]{{{indent}}}(?:ghost[ \t]+)?def [A-Za-z_][A-Za-z0-9_]*\(",
        source[match.end():],
    )
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


positive_names = {
    "production_path_scan_matches_recursive_model",
    "different_sibling_fields_are_disjoint",
    "different_literal_indices_are_disjoint",
    "equal_literal_indices_overlap",
    "unknown_index_may_alias_a_literal_index",
    "a_path_prefix_overlaps_its_extension",
    "an_empty_path_overlaps_every_nonempty_path",
    "later_disjoint_steps_make_paths_disjoint",
    "two_empty_paths_overlap",
    "malformed_path_ranges_cannot_prove_disjointness",
}
negative_names = {
    "sibling_fields_may_overlap",
    "distinct_literal_indices_may_overlap",
    "unknown_index_is_provably_disjoint",
    "empty_path_is_disjoint_from_a_nonempty_path",
}


def declarations(path: Path) -> list[str]:
    return re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text())


def require_inventory(path: Path, expected: set[str], label: str) -> None:
    found = declarations(path)
    if len(found) != len(set(found)) or set(found) != expected:
        raise SystemExit(f"{label} declaration inventory changed")


helper_text = HELPER.read_text()
helper_compact = compact(helper_text)
for fragment in (
    "moduleCallArgumentExclusivityPaths:",
    "defpath_span_valid(start:usize,count:usize,length:usize)->bool:",
    "definputs_well_formed(kinds:darray[u8]&,names:darray[sview]&,values:darray[i64]&,a_start:usize,a_count:usize,b_start:usize,b_count:usize)->bool:",
    "count<=length-start",
    "defsteps_provably_disjoint(",
    "ghostdefoverlap_reference_from(",
    "decreasesa_count-step",
    "ensure(step==a_countorstep==b_count)impliesresult==true",
    "ensurestep<a_countandstep<b_countandsteps_provably_disjoint(kinds[a_start+step],names[a_start+step],values[a_start+step],kinds[b_start+step],names[b_start+step],values[b_start+step])impliesresult==false",
    "ensurestep<a_countandstep<b_countandnotsteps_provably_disjoint(kinds[a_start+step],names[a_start+step],values[a_start+step],kinds[b_start+step],names[b_start+step],values[b_start+step])impliesresult==overlap_reference_from(kinds,names,values,a_start,a_count,b_start,b_count,step+1)",
    "ghostdefoverlap_reference(",
    "ensurenotinputs_well_formed(kinds,names,values,a_start,a_count,b_start,b_count)impliesresult==true",
    "ensureinputs_well_formed(kinds,names,values,a_start,a_count,b_start,b_count)impliesresult==overlap_reference_from(kinds,names,values,a_start,a_count,b_start,b_count,0)",
    "returntrueifnotinputs_well_formed(",
    "defpaths_overlap(",
    "ensureresult==overlap_reference(kinds,names,values,a_start,a_count,b_start,b_count)",
    "returntrueifnotinputs_well_formed(kinds,names,values,a_start,a_count,b_start,b_count)",
    "overlap_limit:usize=a_countifa_count<b_countelseb_count",
    "assertoverlap_limit<=a_countandoverlap_limit<=b_count",
    "assertoverlap_limit==a_countoroverlap_limit==b_count",
    "forstepin0..<overlap_limit:",
    "invariantstep<=a_countandstep<=b_count",
    "invariantoverlap_reference_from(kinds,names,values,a_start,a_count,b_start,b_count,step)==overlap_reference_from(kinds,names,values,a_start,a_count,b_start,b_count,0)",
    "assertoverlap_reference_from(kinds,names,values,a_start,a_count,b_start,b_count,step)==false",
    "assertoverlap_reference_from(kinds,names,values,a_start,a_count,b_start,b_count,0)==overlap_reference(kinds,names,values,a_start,a_count,b_start,b_count)",
    "assertoverlap_reference_from(kinds,names,values,a_start,a_count,b_start,b_count,step)==overlap_reference_from(kinds,names,values,a_start,a_count,b_start,b_count,step+1)",
    "assertoverlap_reference_from(kinds,names,values,a_start,a_count,b_start,b_count,step+1)==overlap_reference_from(kinds,names,values,a_start,a_count,b_start,b_count,0)",
    "assertoverlap_reference_from(kinds,names,values,a_start,a_count,b_start,b_count,overlap_limit)==true",
    "assertoverlap_reference_from(kinds,names,values,a_start,a_count,b_start,b_count,overlap_limit)==overlap_reference_from(kinds,names,values,a_start,a_count,b_start,b_count,0)",
    "returntrue",
):
    if compact(fragment) not in helper_compact:
        raise SystemExit(f"path-overlap proof helper lost source fragment: {fragment}")

consumer_text = CONSUMER.read_text()
expected_wrapper = """
def exclusivity_paths_overlap(kinds: darray[u8]&, names: darray[sview]&, values: darray[i64]&, a_start: usize, a_count: usize, b_start: usize, b_count: usize) -> bool:
    can Abort.Panic:
        return CallArgumentExclusivityPaths::paths_overlap(kinds, names, values, a_start, a_count, b_start, b_count)
"""
if compact(function_section(consumer_text, "exclusivity_paths_overlap")) != compact(expected_wrapper):
    raise SystemExit("same-call alias checker no longer uses the proved path-overlap decision")
if consumer_text.count('include "./check_call_argument_exclusivity_paths.elisa"') != 1:
    raise SystemExit("same-call alias checker must import the isolated, proved path helper once")
place_text = compact(function_section(consumer_text, "exclusivity_place"))
for tag_encoding in (
    'kinds.push(0)names.push(field)values.push(0)',
    'kinds.push(1ifliteral.knownelse2)names.push("")values.push(literal.value)',
    'kinds.push(2)names.push("")values.push(0)',
):
    if tag_encoding not in place_text:
        raise SystemExit("same-call place extraction tags no longer match the proved field/index encoding")
literal_text = compact(function_section(consumer_text, "exclusivity_index_literal"))
if not all(fragment in literal_text for fragment in (
        "Expr.IntLit(value,position):return(true,value)",
        "Expr.Paren(inner,position):returnexclusivity_index_literal(inner)",
        "_:return(false,0)")):
    raise SystemExit("same-call literal-index classification no longer matches the proved path tags")
call_text = compact(function_section(consumer_text, "exclusivity_check_call"))
for path_construction in (
    "roots.push(exclusivity_place(entries.places[entry],kinds,names,values))",
    "step_starts.push(first_step)",
    "step_counts.push(kinds.count-first_step)",
    "path_conflict:bool=exclusivity_paths_overlap(kinds,names,values,step_starts[earlier],step_counts[earlier],step_starts[later],step_counts[later])",
):
    if path_construction not in call_text:
        raise SystemExit("same-call pair checking no longer uses the proved parallel path slices")
if 'exclusivity_paths_overlap(kinds, names, values, step_starts[earlier]' not in consumer_text:
    raise SystemExit("same-call argument-pair checking no longer uses the proved overlap helper")
facade_text = FACADE.read_text()
if facade_text.count('include "./check_call_argument_exclusivity.elisa"') != 1:
    raise SystemExit("semantic facade must include the source-bound exclusivity consumer once")

if 'include "../../src/semantic/check_call_argument_exclusivity_paths.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive path proof no longer imports the production helper")
if 'include "./call_argument_exclusivity_paths.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("false claims no longer extend the source-bound path proof")
require_inventory(POSITIVE, positive_names, "positive path proof")
require_inventory(NEGATIVE, negative_names, "path false-claim proof")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error

MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py", HELPER,
          CONSUMER, FACADE, POSITIVE, NEGATIVE]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


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
assert positive == run(POSITIVE)[1], "path-overlap proof report changed across repeats"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names | {"path_span_valid", "inputs_well_formed", "steps_provably_disjoint",
                         "overlap_reference_from", "overlap_reference", "paths_overlap"} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product_manifest, "proof product provenance changed during replay"
print(json.dumps({"admitted": True,
                  "scope": "source-bound field/index prefix overlap semantics for same-call alias checking",
                  "positive_obligations": positive["summary"]["proven"],
                  "independently_replayed": positive["replay"]["replayed"],
                  "false_claims_rejected": sorted(negative_names),
                  "sources_sha256": hashes}, sort_keys=True))
