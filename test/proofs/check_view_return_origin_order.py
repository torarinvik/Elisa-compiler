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
CONSTANTS = ROOT / "src/semantic/view_return_origin_constants.elisa"
ORIGIN_BUILDER = ROOT / "src/semantic/view_return_origins.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
CONSUMER = ROOT / "src/semantic/check_local_view_return_escape.elisa"
POSITIVE = HERE / "view_return_origin_order.elisa"
NEGATIVE = HERE / "view_return_origin_order_rejected.elisa"
PROOF_PROCESS_TIMEOUT_SECONDS = 120

if not __debug__:
    raise SystemExit("run without Python -O")

source = SORTED.read_text()
origin_builder = ORIGIN_BUILDER.read_text()
semantic = SEMANTIC.read_text()
consumer = CONSUMER.read_text()
positive = POSITIVE.read_text()
negative = NEGATIVE.read_text()
if 'include "../../src/semantic/view_return_origins_sorted.elisa"' not in positive:
    raise SystemExit("positive proof no longer includes the production comparator")
if 'include "../../src/semantic/binding_identity_types.elisa"' not in positive:
    raise SystemExit("positive proof no longer opens the production Semantic module")
if 'include "../../src/semantic/view_return_origin_constants.elisa"' not in positive:
    raise SystemExit("positive proof no longer imports the production comparator and row constants")
if 'include "./view_return_origin_order.elisa"' not in negative:
    raise SystemExit("negative controls no longer include the source-linked proof")
if 'include "./view_return_origins_sorted.elisa"' not in semantic:
    raise SystemExit("production semantic pipeline no longer includes the proved comparator")
if 'include "./view_return_origin_constants.elisa"' not in semantic:
    raise SystemExit("production semantic pipeline no longer includes the shared layout constants")
constant_include = semantic.find('include "./view_return_origin_constants.elisa"')
builder_include = semantic.find('include "./view_return_origins.elisa"')
sort_include = semantic.find('include "./view_return_origins_sorted.elisa"')
if not 0 <= constant_include < builder_include < sort_include:
    raise SystemExit("view-return-origin constants must load before the builder and sorted consumers")
if "vro_sort_rows(origin_rows)" not in consumer:
    raise SystemExit("view-return-origin consumer no longer uses the sorted row implementation")

required_source = (
    "ghost def vro_text_compare_reference_from(",
    "requires position <= left.len and position <= right.len",
    "decreases (left.len if left.len < right.len else right.len) - position",
    "if left[position] < right[position]:",
    "if left[position] > right[position]:",
    "assert vro_text_compare_reference_from(left, right, position) == VRO_COMPARE_LESS",
    "assert vro_text_compare_reference_from(left, right, position) == VRO_COMPARE_GREATER",
    "ensure result == vro_text_compare_reference_from(left, right, VRO_FIRST_BYTE_POSITION)",
    "ensure result >= VRO_COMPARE_LESS and result <= VRO_COMPARE_GREATER",
    "ghost def vro_text_compare_reference_swap(",
    "ensure vro_text_compare_reference_from(left, right, position) == -vro_text_compare_reference_from(right, left, position)",
    "assert vro_text_compare_reference_from(left, right, position) == vro_text_compare_reference_from(left, right, position + VRO_BYTE_STEP)",
    "assert vro_text_compare_reference_from(right, left, position) == vro_text_compare_reference_from(right, left, position + VRO_BYTE_STEP)",
    "next_result: bool = vro_text_compare_reference_swap(left, right, position + VRO_BYTE_STEP)",
    "assert vro_text_compare_reference_from(left, right, position) == -vro_text_compare_reference_from(right, left, position)",
    "invariant position <= shared",
    "while position < shared |position, left, right, shared|:",
    "invariant vro_text_compare_reference_from(left, right, VRO_FIRST_BYTE_POSITION) == vro_text_compare_reference_from(left, right, position)",
    "assert vro_text_compare_reference_from(left, right, position) == vro_text_compare_reference_from(left, right, position + VRO_BYTE_STEP)",
    "assert position == shared",
    "assert vro_text_compare_reference_from(left, right, VRO_FIRST_BYTE_POSITION) == vro_text_compare_reference_from(left, right, position)",
    "assert shared == left_length",
    "assert vro_text_compare_reference_from(left, right, position) == VRO_COMPARE_LESS",
    "assert shared == right_length",
    "assert vro_text_compare_reference_from(left, right, position) == VRO_COMPARE_GREATER",
    "assert vro_text_compare_reference_from(left, right, position) == VRO_COMPARE_EQUAL",
    "rows.count / VRO_ROW_WIDTH",
    "middle * VRO_ROW_WIDTH",
    "row + VRO_ROW_FIELD_OFFSET >= rows.count",
    "row <- row + VRO_ROW_WIDTH",
    "width <- width * VRO_MERGE_PAIR_COUNT",
    "sorted: mutable darray[sview @source] = [VRO_SORTED_MARKER, \"\", \"\", \"\", \"\"]",
)
if not all(fragment in source for fragment in required_source):
    raise SystemExit("production text comparator lost its recursive specification or reference cursor invariant")
constant_source = CONSTANTS.read_text()
required_constants = (
    "const VRO_COMPARE_LESS: i32 = -1",
    "const VRO_COMPARE_EQUAL: i32 = 0",
    "const VRO_COMPARE_GREATER: i32 = 1",
    "const VRO_ROW_WIDTH: usize = 5",
    'const VRO_SORTED_MARKER: sview = "[vro-sorted]"',
    "const VRO_SORTED_MARKER_INDEX: usize = 0",
    "const VRO_FIRST_DATA_ROW_INDEX: usize = 1",
    "const VRO_ROW_ARITY_OFFSET: usize = 1",
    "const VRO_ROW_POSITION_OFFSET: usize = 2",
    "const VRO_ROW_MODE_OFFSET: usize = 3",
    "const VRO_ROW_FIELD_OFFSET: usize = 4",
    "const VRO_FIRST_ROW_INDEX: usize = 0",
    "const VRO_FIRST_BYTE_POSITION: usize = 0",
    "const VRO_BYTE_STEP: usize = 1",
    "const VRO_INITIAL_MERGE_WIDTH: usize = 1",
    "const VRO_MERGE_PAIR_COUNT: usize = 2",
    "const VRO_BINARY_SEARCH_DIVISOR: usize = 2",
)
if not all(constant in constant_source for constant in required_constants):
    raise SystemExit("view-return-origin row and comparator constants changed")
if "def vro_row() -> usize:\n            return VRO_ROW_WIDTH" not in origin_builder:
    raise SystemExit("view-return-origin row construction no longer uses the shared row width")
for raw_layout in ("rows.count / 5", "middle * 5", "row + 4", "row <- row + 5", "width * 2"):
    if raw_layout in source:
        raise SystemExit(f"view-return-origin sorter contains a raw row-layout value: {raw_layout}")

positive_names = {
    "production_comparator_refines_recursive_lexicographic_spec",
    "production_comparator_returns_only_three_way_results",
    "production_comparison_is_antisymmetric",
    "identical_text_keys_compare_equal",
    "a_text_prefix_sorts_before_its_extension",
}
negative_names = {
    "a_smaller_first_difference_is_reported_as_greater",
    "identical_keys_are_claimed_unequal",
    "a_shorter_prefix_is_claimed_greater",
    "opposite_text_orders_are_claimed_equal",
}
for name in positive_names:
    if f"def {name}(" not in positive:
        raise SystemExit(f"positive comparator theorem missing: {name}")
if "vro_text_compare_reference_swap(left, right, VRO_FIRST_BYTE_POSITION)" not in positive:
    raise SystemExit("antisymmetry theorem no longer composes the production comparator with its reference-order lemma")
if "VRO_COMPARE_LESS" not in positive or "VRO_COMPARE_EQUAL" not in positive:
    raise SystemExit("comparator theorems no longer use the production result constants")
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
    CONSTANTS,
    ORIGIN_BUILDER,
    SEMANTIC,
    CONSUMER,
]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_PROCESS_TIMEOUT_SECONDS)
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
    "scope": "production bytewise comparator refines its lexicographic specification and is antisymmetric, three-way, reflexive, and prefix ordered",
    "positive_obligations": positive_report["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
}, sort_keys=True))
