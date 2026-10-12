"""Admit the production view-return-origin bytewise ordering proof."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
SORTED = ROOT / "src/semantic/view_return_origins_sorted.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
CONSUMER = ROOT / "src/semantic/check_local_view_return_escape.elisa"
POSITIVE = HERE / "view_return_origin_order.elisa"
NEGATIVE = HERE / "view_return_origin_order_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")

source = SORTED.read_text()
semantic = SEMANTIC.read_text()
consumer = CONSUMER.read_text()
positive = POSITIVE.read_text()
negative = NEGATIVE.read_text()
if 'include "../../src/semantic/view_return_origins_sorted.elisa"' not in positive:
    raise SystemExit("positive proof no longer includes the production comparator")
if 'include "../../src/semantic/binding_identity_types.elisa"' not in positive:
    raise SystemExit("positive proof no longer opens the production Semantic module")
if 'include "./view_return_origin_order.elisa"' not in negative:
    raise SystemExit("negative controls no longer include the source-linked proof")
if 'include "./view_return_origins_sorted.elisa"' not in semantic:
    raise SystemExit("production semantic pipeline no longer includes the proved comparator")
if "vro_sort_rows(origin_rows)" not in consumer:
    raise SystemExit("view-return-origin consumer no longer uses the sorted row implementation")

required_source = (
    "ghost def vro_text_compare_reference_from(",
    "ghost def vro_text_compare_prefix_preserves(",
    "requires position <= sview_len(left) and position <= sview_len(right)",
    "decreases (sview_len(left) if sview_len(left) < sview_len(right) else sview_len(right)) - position",
    "ensure vro_text_compare_reference_from(left, right, 0) == vro_text_compare_reference_from(left, right, position)",
    "-1 return if left[position] < right[position]",
    "1 return if left[position] > right[position]",
    "ensure result == vro_text_compare_reference_from(left, right, 0)",
    "ensure result >= -1 and result <= 1",
    "invariant position <= shared",
    "invariant forall prefix_index in 0..<position: left[prefix_index] == right[prefix_index]",
    "invariant vro_text_compare_prefix_preserves(left, right, position)",
)
if not all(fragment in source for fragment in required_source):
    raise SystemExit("production text comparator lost its recursive specification or prefix proof invariant")

positive_names = {
    "production_comparator_refines_recursive_lexicographic_spec",
    "production_comparator_returns_only_three_way_results",
    "identical_text_keys_compare_equal",
    "a_text_prefix_sorts_before_its_extension",
}
negative_names = {
    "a_smaller_first_difference_is_reported_as_greater",
    "identical_keys_are_claimed_unequal",
    "a_shorter_prefix_is_claimed_greater",
}
for name in positive_names:
    if f"def {name}(" not in positive:
        raise SystemExit(f"positive comparator theorem missing: {name}")
for name in negative_names:
    if f"def {name}(" not in negative:
        raise SystemExit(f"negative comparator control missing: {name}")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("view-return-origin comparator proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != product_manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
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
    POSITIVE,
    NEGATIVE,
    SORTED,
    SEMANTIC,
    CONSUMER,
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
assert positive_report == run(POSITIVE)[1], "comparator proof report changed across repeated runs"
verified = {row["name"] for row in positive_report["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative_report = run(NEGATIVE)
assert code == 1 and negative_report["status"] == negative_report["verification_state"] == "failed"
assert negative_report["summary"]["proven"] + len(negative_names) == negative_report["summary"]["obligations"]
assert {finding["name"] for finding in negative_report["findings"]} == negative_names
assert all(finding["kind"] == "ensure-unproven" for finding in negative_report["findings"])
assert not negative_names & {row["name"] for row in negative_report["declaration_details"] if row.get("verified")}

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product_manifest
print(json.dumps({
    "admitted": True,
    "scope": "production bytewise key comparator refines the recursive lexicographic specification; result is three-way, reflexive, and prefix ordered",
    "positive_obligations": positive_report["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
}, sort_keys=True))
