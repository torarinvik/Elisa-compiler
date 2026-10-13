"""Admit the source-linked EASM layout arithmetic proof against a strict product."""
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
POSITIVE = HERE / "easm_layout_arithmetic.elisa"
NEGATIVE = HERE / "easm_layout_arithmetic_rejected.elisa"
HELPER = ROOT / "src/backend/easm_layout_arithmetic.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
PROVENANCE = ROOT / "src/backend/easm_verify_provenance.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"
INTEGRATION_FIXTURE = ROOT / "test/breadth/easm_layout_extent_overflow_smoke.elisa"
DECIMAL_FIXTURE = ROOT / "test/breadth/easm_checked_decimal_parse_smoke.elisa"
STDIN_DRIVER = ROOT / "test/breadth/easm_verify_stdin.elisa"
INTEGRATION_SMOKE = ROOT / "test/parity/easm_layout_extent_overflow_smoke.sh"

if not __debug__:
    raise SystemExit("run without Python -O")
if 'include "easm_layout_arithmetic.elisa"' not in ENV.read_text():
    raise SystemExit("backend environment no longer imports the proved EASM layout arithmetic")
if ENV.read_text().index('include "easm_memstate_domain.elisa"') > ENV.read_text().index('include "easm_layout_arithmetic.elisa"'):
    raise SystemExit("EASM layout arithmetic is imported before the shared greatest-bound domain")
if ENV.read_text().index('include "easm_layout_arithmetic.elisa"') > ENV.read_text().index('include "easm_model.elisa"'):
    raise SystemExit("EASM layout arithmetic is imported after the model that uses it")
if 'include "../../src/backend/easm_layout_arithmetic.elisa"' not in POSITIVE.read_text():
    raise SystemExit("proof no longer imports the production layout arithmetic")
for proof_source in (POSITIVE, NEGATIVE):
    proof_text = proof_source.read_text()
    domain_import = 'include "../../src/backend/easm_memstate_domain.elisa"'
    layout_import = 'include "../../src/backend/easm_layout_arithmetic.elisa"'
    if domain_import not in proof_text or layout_import not in proof_text or \
            proof_text.index(domain_import) > proof_text.index(layout_import):
        raise SystemExit(f"{proof_source.name} must import the shared max domain before layout arithmetic")

provenance = PROVENANCE.read_text()
layout_body = provenance.split("def layout_size_checked(layout: Layout)", 1)[1].split(
    "def layout_field_width(", 1
)[0]
required_layout_fragments = [
    "EasmLayoutArithmetic::include_field_extent(largest, field.offset, field.width)",
    "return (false, 0) if not next_extent.valid",
    "largest <- next_extent.value",
    "EasmLayoutArithmetic::declared_size(layout.size, layout.stride)",
    "return (true, declared) if declared > 0",
    "return (true, largest)",
]
if not all(fragment in layout_body for fragment in required_layout_fragments):
    raise SystemExit("EASM layout sizing no longer uses the proved checked extent-accumulation transition")
layout_positions = [layout_body.index(fragment) for fragment in required_layout_fragments]
if layout_positions != sorted(layout_positions):
    raise SystemExit("EASM layout sizing reordered or bypassed the checked extent-accumulation transition")
if "field_extent_checked(field.offset, field.width)" in layout_body or "keep_larger(largest" in layout_body:
    raise SystemExit("EASM layout sizing bypasses the proved checked extent-accumulation transition")
helper = HELPER.read_text()
required_extent_fragments = (
    "const I64_MAX: i64 = 9223372036854775807",
    "def field_extent_checked(offset: i64, width: i64)",
    "return (false, 0) if offset < 0 or width < 0",
    "return (false, 0) if width > I64_MAX - offset",
    "return (true, offset + width)",
    "ensure offset >= 0 and width >= 0 implies result.valid == (width <= I64_MAX - offset)",
    "ensure result.valid implies result.value == offset + width",
    "ensure not result.valid implies result.value == 0",
)
if not all(fragment in helper for fragment in required_extent_fragments):
    raise SystemExit("EASM field extent helper no longer checks representability before addition")
if "return EasmMemStateDomain::greatest_bound(current, candidate)" not in helper:
    raise SystemExit("EASM layout bound no longer delegates to the proved greatest-bound domain")
max_body = helper.split("def keep_larger(current: i64, candidate: i64)", 1)[1].split(
    "# Fold one checked field extent", 1
)[0]
if "ensure result >= current" not in max_body or "ensure result >= candidate" not in max_body:
    raise SystemExit("EASM layout maximum no longer exports both upper-bound guarantees")
required_accumulator_fragments = (
    "def include_field_extent(current: i64, offset: i64, width: i64)",
    "ensure result.valid == field_extent_checked(offset, width).valid",
    "ensure not result.valid implies result.value == 0",
    "ensure result.valid implies result.value == keep_larger(current, field_extent_checked(offset, width).value)",
    "ensure result.valid implies result.value >= current",
    "ensure result.valid implies result.value >= field_extent_checked(offset, width).value",
    "return (false, 0) if not extent.valid",
    "return (true, keep_larger(current, extent.value))",
)
if not all(fragment in helper for fragment in required_accumulator_fragments):
    raise SystemExit("EASM field extent accumulator no longer proves fail-closed max-bound preservation")
accumulator_body = helper.split("def include_field_extent(current: i64, offset: i64, width: i64)", 1)[1]
ordered_accumulator_fragments = (
    "extent: (valid: bool, value: i64) = field_extent_checked(offset, width)",
    "return (false, 0) if not extent.valid",
    "return (true, keep_larger(current, extent.value))",
)
accumulator_positions = [accumulator_body.index(fragment) for fragment in ordered_accumulator_fragments]
if accumulator_positions != sorted(accumulator_positions):
    raise SystemExit("EASM field extent accumulator no longer checks validity before updating the maximum")
checked_extent_body = helper.split("def field_extent_checked(offset: i64, width: i64)", 1)[1].split(
    "def keep_larger(", 1
)[0]
ordered_guard_fragments = (
    "return (false, 0) if offset < 0 or width < 0",
    "return (false, 0) if width > I64_MAX - offset",
    "return (true, offset + width)",
)
if [checked_extent_body.index(fragment) for fragment in ordered_guard_fragments] != sorted(
    checked_extent_body.index(fragment) for fragment in ordered_guard_fragments
):
    raise SystemExit("EASM field extent addition is no longer dominated by its nonnegative overflow guards")
if "def field_extent(" in helper:
    raise SystemExit("unchecked scalar field extent API was reintroduced")
memory_text = MEMORY.read_text()
if "total: (valid: bool, value: i64) = layout_size_checked(layout)" not in memory_text:
    raise SystemExit("layout verification no longer consumes validity-bearing inferred size")
if "field.offset + field.width" in memory_text or "field.offset + field.width" in provenance:
    raise SystemExit("EASM layout bounds bypass checked field extents")
if '"layout-field-extent-overflow"' not in MEMORY.read_text() or '"layout-field-extent-overflow"' not in provenance:
    raise SystemExit("layout verification or guest-overlay resolution no longer rejects overflowing extents")
if "offset: -1, width: 0" not in provenance:
    raise SystemExit("guest-overlay resolution no longer returns an invalid-layout sentinel")
if "return checked.value if checked.valid else -1" not in provenance:
    raise SystemExit("legacy layout-size API no longer returns a fail-closed sentinel for invalid extents")

fixture_text = INTEGRATION_FIXTURE.read_text()
required_fixture_fragments = (
    "offset: 9223372036854775807",
    "offset: 9223372036854775804",
    '"layout-field-extent-overflow"',
    "layout_size_checked(inferred)",
    "Easm::layout_size(inferred) != -1",
    "Easm::resolve_guest_overlay_access(explicit, \"near_tail\", 8, overlay_issues)",
    "boundary_size.value != 9223372036854775807",
    "can Memory.Allocate, Abort.Panic:",
)
if not all(fragment in fixture_text for fragment in required_fixture_fragments):
    raise SystemExit("EASM extent integration fixture lost overflow, inference, guest-overlay, or boundary controls")
stdin_driver_text = STDIN_DRIVER.read_text()
if "issues: darray[Easm::Issue] = parsed.issues" not in stdin_driver_text:
    raise SystemExit("EASM stdin driver no longer reports parse-time extent issues")
smoke_text = INTEGRATION_SMOKE.read_text()
required_smoke_fragments = (
    "assert_stage1_fresh.sh",
    "-O${optimization}",
    "easm_checked_decimal_parse_smoke",
    "malformed-required-size",
    "overflow-required-size",
    "overflow-field-extent",
    "layout-field-extent-overflow",
    "control_artifacts.sh",
)
if not all(fragment in smoke_text for fragment in required_smoke_fragments):
    raise SystemExit("EASM extent smoke no longer checks fresh Stage1 O0/O2 API and stdin rejection paths")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("EASM layout proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
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
    HELPER,
    ENV,
    PROVENANCE,
    MEMORY,
    INTEGRATION_FIXTURE,
    DECIMAL_FIXTURE,
    STDIN_DRIVER,
    INTEGRATION_SMOKE,
]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
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
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
expected = {
    "declared_size",
    "field_extent_checked",
    "keep_larger",
    "include_field_extent",
    "positive_explicit_size_precedes_stride",
    "positive_stride_is_used_when_size_is_not_positive",
    "nonpositive_size_and_stride_have_no_declared_extent",
    "max_extent_keeps_a_bound_at_least_as_large_as_each_input",
    "max_extent_is_one_of_the_two_inputs",
    "layout_max_uses_the_proved_greatest_bound",
    "valid_field_extent_is_nonnegative",
    "ordinary_field_extent_is_exact",
    "exact_i64_max_field_extent_is_valid",
    "nonnegative_field_extent_matches_i64_representability",
    "negative_field_extent_inputs_are_rejected",
    "i64_max_offset_plus_u64_width_is_rejected",
    "i64_max_minus_three_offset_plus_u64_width_is_rejected",
    "successful_field_accumulation_dominates_both_inputs",
    "successful_field_accumulation_is_the_least_common_upper_bound",
    "maximum_offset_overflow_is_rejected_by_accumulation",
}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["proven"] + 5 == negative["summary"]["obligations"]
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "stride_overrides_a_positive_explicit_size"),
    ("ensure-unproven", "overflowing_field_extent_is_accepted"),
    ("ensure-unproven", "first_unrepresentable_field_extent_is_accepted"),
    ("ensure-unproven", "a_valid_small_field_can_shrink_the_existing_layout_bound"),
    ("ensure-unproven", "a_common_upper_bound_can_be_smaller_than_a_successful_field_accumulation"),
]
assert {"stride_overrides_a_positive_explicit_size", "overflowing_field_extent_is_accepted",
        "first_unrepresentable_field_extent_is_accepted",
        "a_valid_small_field_can_shrink_the_existing_layout_bound",
        "a_common_upper_bound_can_be_smaller_than_a_successful_field_accumulation"}.isdisjoint({
    row["name"] for row in negative["declaration_details"] if row.get("verified")
})

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "EASM layout-size precedence, exact checked extents, and shared least-upper-bound accumulation",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": ["stride_overrides_a_positive_explicit_size", "overflowing_field_extent_is_accepted",
                              "first_unrepresentable_field_extent_is_accepted",
                              "a_valid_small_field_can_shrink_the_existing_layout_bound",
                              "a_common_upper_bound_can_be_smaller_than_a_successful_field_accumulation"],
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
