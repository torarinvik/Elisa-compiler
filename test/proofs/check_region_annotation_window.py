"""Source-bind the lower/upper line-window proofs to semantic safety consumers."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
SOURCE = ROOT / "src/semantic/region_annotation_order.elisa"
INTEGRATION = ROOT / "src/semantic/semantic.elisa"
PIPELINE_SOURCE = ROOT / "src/semantic/semantic_api.elisa"
DESTROYED = ROOT / "src/semantic/check_destroyed_region.elisa"
HANDLER = ROOT / "src/semantic/check_handler_capture_escape.elisa"
AUTO_REGION = ROOT / "src/semantic/auto_region_wrap.elisa"
POSITIVE = HERE / "region_annotation_window.elisa"
NEGATIVE = HERE / "region_annotation_window_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")
if not MANIFEST.is_file():
    raise SystemExit(f"missing proof build manifest: {MANIFEST}")


def compact(text: str) -> str:
    return "".join(line.split("#", 1)[0] for line in text.splitlines()).replace(" ", "").replace("\t", "").replace("\n", "")


def function_chunk(text: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}\s*\(", text)
    if not match:
        raise SystemExit(f"missing production function {name}")
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\s*\(", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return "\n".join(line for line in text[match.start():end].splitlines()
                      if not line.lstrip().startswith("#"))


source = SOURCE.read_text()
integration = INTEGRATION.read_text()
pipeline_source = PIPELINE_SOURCE.read_text()
destroyed = DESTROYED.read_text()
handler = HANDLER.read_text()
auto_region = AUTO_REGION.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

sortedness = function_chunk(source, "region_annotations_line_sorted")
for fragment in (
    "false return if annotations.count == 0",
    "first_line: u32 = annotations[0].line",
    "last_line: u32 = annotations[annotations.count - 1].line",
    "sorted: mutable bool = true",
    "for index in 1..<annotations.count |sorted, annotations|:",
    "sorted <- false if annotations[index].line < annotations[index - 1].line",
    "region_annotation_sorted_value <- sorted",
    "return region_annotation_sorted_value can Global.Read",
    "if base != (region_annotation_sorted_base can Global.Read) or annotations.count != (region_annotation_sorted_count can Global.Read) or first_line != (region_annotation_sorted_first can Global.Read) or last_line != (region_annotation_sorted_last can Global.Read):",
    "region_annotation_sorted_base <- base",
    "region_annotation_sorted_count <- annotations.count",
    "region_annotation_sorted_first <- first_line",
    "region_annotation_sorted_last <- last_line",
):
    if compact(fragment) not in compact(sortedness):
        raise SystemExit(f"line-sorted cache changed without updating the proof assumptions: {fragment}")

start = compact(function_chunk(source, "region_annotation_window_start"))
for fragment in (
    "0 return if not (region_annotations_line_sorted(annotations) can Global{Read,Write})",
    "lower: mutable usize = 0",
    "upper: mutable usize = annotations.count",
    "while lower < upper |lower, upper, annotations, low|:",
    "middle: usize = lower + (upper - lower) / 2",
    "if annotations[middle].line < low:",
    "lower <- middle + 1",
    "upper <- middle",
    "return lower",
):
    if compact(fragment) not in start:
        raise SystemExit(f"lower-bound production search changed without updating its proof: {fragment}")

end = compact(function_chunk(source, "region_annotation_window_end"))
for fragment in (
    "annotations.count return if not (region_annotations_line_sorted(annotations) can Global{Read,Write})",
    "lower: mutable usize = 0",
    "upper: mutable usize = annotations.count",
    "while lower < upper |lower, upper, annotations, high|:",
    "middle: usize = lower + (upper - lower) / 2",
    "if annotations[middle].line <= high:",
    "lower <- middle + 1",
    "upper <- middle",
    "return lower",
):
    if compact(fragment) not in end:
        raise SystemExit(f"upper-bound production search changed without updating its proof: {fragment}")

forget = compact(function_chunk(source, "region_annotations_forget_sorted"))
if "region_annotation_sorted_base<-0" not in forget or "region_annotation_sorted_count<-0" not in forget:
    raise SystemExit("line-sort memo invalidation no longer clears its identity key")
if source.count("region_annotations_forget_sorted() can Global.Write") != 0:
    raise SystemExit("memo invalidation must be owned by the semantic consumer, not hidden in this module")
if destroyed.count("region_annotations_forget_sorted() can Global.Write") != 2:
    raise SystemExit("destroyed-region analysis must invalidate both file and scoped-lambda annotation arrays")
if handler.count("region_annotations_forget_sorted() can Global.Write") != 1:
    raise SystemExit("handler-capture analysis must clear a previous file's sortedness memo")
handler_entry = function_chunk(handler, "check_handler_capture_escape")
handler_reset = handler_entry.find("region_annotations_forget_sorted() can Global.Write")
handler_queries = handler_entry.find("hce_check_declarations(")
if handler_reset < 0 or handler_queries < 0 or handler_reset > handler_queries:
    raise SystemExit("handler-capture analysis must invalidate before querying the current file's annotations")
if 'include "./region_annotation_order.elisa"' not in integration:
    raise SystemExit("semantic facade no longer includes the line-window implementation")
def assert_auto_region_reset_order(pipeline: str) -> None:
    handler_phase = pipeline.find(compact("check_handler_capture_escape(loop_view, table)"))
    if handler_phase < 0:
        raise ValueError("semantic pipeline no longer runs the handler cache reset")
    for consumer_call in (
        "check_container_literal_region(loop_view, table)",
        "check_defer_rules(loop_view, table)",
    ):
        consumer_phase = pipeline.find(compact(consumer_call))
        if consumer_phase < 0 or handler_phase > consumer_phase:
            raise ValueError(f"handler cache reset must precede auto-region consumer {consumer_call}")


pipeline = compact(function_chunk(pipeline_source, "check_full_into_pipeline"))
try:
    assert_auto_region_reset_order(pipeline)
except ValueError as error:
    raise SystemExit(str(error)) from error
if "region_annotation_window_start(annotations, function_line)" not in destroyed or \
        "region_annotation_window_end(annotations, use_line)" not in destroyed:
    raise SystemExit("destroyed-region safety analysis no longer uses the proved range endpoints")
if "region_annotation_window_start(annotations, line)" not in handler or \
        "region_annotation_window_end(annotations, line)" not in handler:
    raise SystemExit("handler-capture safety analysis no longer uses the proved range endpoints")
if "region_annotation_line_window(annotations, line)" not in auto_region:
    raise SystemExit("auto-region wrapping no longer uses the proved line window")

# A future pipeline reorder must not silently put an auto-region query before the
# per-file cache reset. Check the rejection path with a one-step source mutation.
reset_call = compact("check_handler_capture_escape(loop_view, table)")
container_call = compact("check_container_literal_region(loop_view, table)")
without_reset = pipeline.replace(reset_call, "", 1)
container_end = without_reset.find(container_call) + len(container_call)
mutated_pipeline = without_reset[:container_end] + reset_call + without_reset[container_end:]
try:
    assert_auto_region_reset_order(mutated_pipeline)
except ValueError:
    pass
else:
    raise SystemExit("pipeline-order rejection control no longer catches reset-after-consumer order")

positive_names = {
    "lower_bound_midpoint_stays_inside",
    "upper_bound_midpoint_stays_inside",
    "lower_bound_advance_preserves_first_ge_cut",
    "lower_bound_retreat_preserves_first_ge_cut",
    "upper_bound_advance_preserves_first_gt_cut",
    "upper_bound_retreat_preserves_first_gt_cut",
    "the_initial_full_interval_contains_any_valid_cut",
    "unsorted_fallback_window_covers_every_row",
    "same_cache_identity_can_hide_interior_reordering",
}
negative_names = {
    "false_midpoint_can_reach_high",
    "false_advance_can_cross_the_boundary",
    "false_retreat_can_discard_the_boundary",
    "false_advance_does_not_shrink_the_interval",
    "false_retreat_does_not_shrink_the_interval",
    "false_same_cache_identity_preserves_sort_order",
}
declarations = lambda text: set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", text))
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("region annotation window proof inventory changed")
negative_fragments = {
    "false_midpoint_can_reach_high": (
        "middle: usize = low + (high - low) / 2",
        "return middle == high",
    ),
    "false_advance_can_cross_the_boundary": (
        "next_low: usize = middle + 1",
        "return next_low > cut",
    ),
    "false_retreat_can_discard_the_boundary": (
        "next_high: usize = middle",
        "return cut <= next_high",
    ),
    "false_advance_does_not_shrink_the_interval": (
        "next_low: usize = low",
        "return high - next_low < high - low",
    ),
    "false_retreat_does_not_shrink_the_interval": (
        "next_high: usize = high",
        "return next_high - low < high - low",
    ),
    "false_same_cache_identity_preserves_sort_order": (
        "old_base: i64 = address",
        "new_base: i64 = address",
        "old_count: i64 = 3",
        "new_count: i64 = 3",
        "old_first: i64 = 10",
        "old_middle: i64 = 11",
        "old_last: i64 = 12",
        "new_first: i64 = 10",
        "new_middle: i64 = 9",
        "new_last: i64 = 12",
        "old_sorted == new_sorted",
    ),
}
for name, fragments in negative_fragments.items():
    negative_case = compact(function_chunk(negative_text, name))
    if any(compact(fragment) not in negative_case for fragment in fragments):
        raise SystemExit(f"negative control {name} no longer states its intended false claim")
for fragment in (
    "middle: usize = low + (high - low) / 2",
    "middle < cut and cut <= high",
    "next_low: usize = middle + 1",
    "cut <= middle and middle < high",
    "next_high: usize = middle",
    "high - next_low < high - low",
    "next_high - low < high - low",
    "return start == 0 and stop == count",
    "old_base: i64 = address",
    "new_base: i64 = address",
    "old_count: i64 = 3",
    "new_count: i64 = 3",
    "old_first: i64 = 10",
    "old_middle: i64 = 11",
    "old_last: i64 = 12",
    "new_first: i64 = 10",
    "new_middle: i64 = 9",
    "new_last: i64 = 12",
    "old_sorted and not new_sorted",
):
    if compact(fragment) not in compact(positive_text):
        raise SystemExit(f"line-window proof lost midpoint, cut-point, or progress evidence: {fragment}")
try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("region annotation window proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [*source_include_closure([POSITIVE, NEGATIVE]), BIN, MANIFEST, MANIFEST_CHECKSUM,
          PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance, Path(__file__),
          HERE / "proof_product_gate.py", SOURCE, INTEGRATION, PIPELINE_SOURCE, DESTROYED, HANDLER, AUTO_REGION,
          POSITIVE, NEGATIVE]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


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
assert positive == run(POSITIVE)[1], "region annotation proof report changed across identical runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "false_midpoint_can_reach_high"),
    ("ensure-unproven", "false_advance_can_cross_the_boundary"),
    ("ensure-unproven", "false_retreat_can_discard_the_boundary"),
    ("ensure-unproven", "false_advance_does_not_shrink_the_interval"),
    ("ensure-unproven", "false_retreat_does_not_shrink_the_interval"),
    ("ensure-unproven", "false_same_cache_identity_preserves_sort_order"),
]
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest, "proof product provenance changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "scalar lower/upper-bound interval arithmetic, unsorted full-range fallback, conditional memo-key collision witness, and semantic safety-consumer bindings",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [row["name"] for row in negative["findings"]],
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
