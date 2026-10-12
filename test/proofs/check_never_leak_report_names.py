"""Admit source-linked proofs of the never-leak report label tables."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
POSITIVE = HERE / "never_leak_report_names.elisa"
NEGATIVE = HERE / "never_leak_report_names_rejected.elisa"
CODES = ROOT / "src/semantic/never_leak_codes.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
ANALYZER = ROOT / "src/semantic/check_never_leak.elisa"
HELPER = ROOT / "src/driver/never_leak_report_names.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
CATEGORY_WRAPPER = ROOT / "src/driver/elisac_never_leak.elisa"
ACC_WRAPPER = CATEGORY_WRAPPER
VT_WRAPPER = ROOT / "src/driver/elisac_never_leak_threading.elisa"
PHRASE_WRAPPER = ROOT / "src/driver/elisac_never_leak_report.elisa"
STAT_REPORTER = CATEGORY_WRAPPER
MODE_REPORTERS = (
    PHRASE_WRAPPER,
    ROOT / "src/driver/elisac_never_leak_accumulator.elisa",
    VT_WRAPPER,
    ROOT / "src/driver/elisac_never_leak_push_loop.elisa",
)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")

CATEGORIES = {
    "NEVER_LEAK_CHAIN": (1, "chain"),
    "NEVER_LEAK_PLAIN": (2, "plain"),
    "NEVER_LEAK_BORROW_EXEMPT": (3, "borrow-exempt"),
    "NEVER_LEAK_OVERLAP": (4, "overlap"),
    "NEVER_LEAK_LOOP": (5, "loop"),
    "NEVER_LEAK_ACCUMULATOR": (6, "accumulator"),
    "NEVER_LEAK_VALUE_THREAD": (7, "value-thread"),
    "NEVER_LEAK_PUSH_LOOP": (8, "push-loop"),
}
ACCUMULATOR_REASONS = {
    "NEVER_LEAK_ACC_OK": (0, ""),
    "NEVER_LEAK_ACC_READ_INSIDE": (1, "-read-inside"),
    "NEVER_LEAK_ACC_WRITTEN_AFTER": (2, "-written-after"),
    "NEVER_LEAK_ACC_NOT_SCALAR": (3, "-not-scalar"),
    "NEVER_LEAK_ACC_ESCAPES": (4, "-escape"),
    "NEVER_LEAK_ACC_SHAPE": (5, "-shape"),
}
VALUE_THREAD_REASONS = {
    "NEVER_LEAK_VT_OK": (0, ""),
    "NEVER_LEAK_VT_BORROW": (1, "-borrow"),
    "NEVER_LEAK_VT_BORROWED_FIELD": (2, "-borrowed-field"),
    "NEVER_LEAK_VT_GLOBAL": (3, "-global"),
    "NEVER_LEAK_VT_ARENA": (4, "-arena"),
    "NEVER_LEAK_VT_EFFECT_ONLY": (5, "-effect-only"),
    "NEVER_LEAK_VT_SHAPE": (6, "-shape"),
}
REASON_NONE = {"NEVER_LEAK_REASON_NONE": (0, "")}
UNKNOWN_CATEGORY = {"NEVER_LEAK_CATEGORY_UNKNOWN": (0, "")}


def require_codes(expected):
    text = CODES.read_text()
    actual = {
        name: int(value)
        for name, value in re.findall(r"(?m)^\s*const ([A-Z0-9_]+): u8 = ([0-9]+)$", text)
    }
    for name, (value, _) in expected.items():
        if actual.get(name) != value:
            raise SystemExit(f"semantic code {name} changed: expected {value}, got {actual.get(name)}")


def require_table(function_name, cases, fallback):
    text = HELPER.read_text()
    definition = re.search(
        rf"(?m)^        def {re.escape(function_name)}\([^\n]*\n(.*?)(?=^        def |\Z)",
        text,
        re.DOTALL,
    )
    if not definition:
        raise SystemExit(f"production label function {function_name} is missing")
    arms = re.findall(
        r'(?m)^\s*Semantic::([A-Z0-9_]+) -> "([^"\\]*)"$', definition.group(1)
    )
    default = re.search(r'(?m)^\s*_ -> "([^"\\]*)"$', definition.group(1))
    if arms != [(name, label) for name, (_, label) in cases.items()]:
        raise SystemExit(f"{function_name} does not match the complete named-code table")
    if default is None or default.group(1) != fallback:
        raise SystemExit(f"{function_name} changed its legacy fallback")


require_codes(CATEGORIES)
require_codes(ACCUMULATOR_REASONS)
require_codes(VALUE_THREAD_REASONS)
require_codes(REASON_NONE)
require_codes(UNKNOWN_CATEGORY)
require_table("category_name", CATEGORIES, "loop")
require_table("accumulator_reason_name", ACCUMULATOR_REASONS, "-shape")
require_table("value_thread_reason_name", VALUE_THREAD_REASONS, "-shape")
if 'return ": error: " if mode == NeverLeakEnvValues::NL_ENV_MODE_ERROR else ": warning: "' not in HELPER.read_text():
    raise SystemExit("severity prefix must match the named error mode and warning fallback")
if "acc_reason: mutable u8 = NEVER_LEAK_REASON_NONE" not in ANALYZER.read_text():
    raise SystemExit("NeverLeakFinding must initialize its generic reason with the named none code")


def require_proof_spec(function_name, production_function, cases, fallback):
    text = POSITIVE.read_text()
    definition = re.search(
        rf"(?m)^def {re.escape(function_name)}\([^\n]*\n(.*?)(?=^def |\Z)",
        text,
        re.DOTALL,
    )
    if not definition or f"NeverLeakReportNames::{production_function}(" not in definition.group(1):
        raise SystemExit(f"proof {function_name} is not bound to its production function")
    arms = re.findall(
        r'(?m)^\s*Semantic::([A-Z0-9_]+) -> "([^"\\]*)"$', definition.group(1)
    )
    default = re.search(r'(?m)^\s*_ -> "([^"\\]*)"$', definition.group(1))
    if arms != [(name, label) for name, (_, label) in cases.items()]:
        raise SystemExit(f"proof {function_name} changed its complete expected code table")
    if default is None or default.group(1) != fallback:
        raise SystemExit(f"proof {function_name} changed its expected fallback")


require_proof_spec(
    "category_name_matches_the_complete_code_table",
    "category_name", CATEGORIES, "loop",
)
require_proof_spec(
    "accumulator_reason_name_matches_the_complete_code_table",
    "accumulator_reason_name", ACCUMULATOR_REASONS, "-shape",
)
require_proof_spec(
    "value_thread_reason_name_matches_the_complete_code_table",
    "value_thread_reason_name", VALUE_THREAD_REASONS, "-shape",
)

semantic_text = SEMANTIC.read_text()
if not (
    semantic_text.index('include "./never_leak_codes.elisa"')
    < semantic_text.index('include "./check_never_leak_types.elisa"')
):
    raise SystemExit("semantic code constants must be included before never-leak analyzers")
driver_text = DRIVER.read_text()
if not (
    driver_text.index('include "../semantic/semantic.elisa"')
    < driver_text.index('include "./never_leak_report_names.elisa"')
    < driver_text.index('include "./elisac_never_leak.elisa"')
):
    raise SystemExit("driver must include the production label table after Semantic and before wrappers")

for file, expected in (
    (CATEGORY_WRAPPER, "return NeverLeakReportNames::category_name(category)"),
    (ACC_WRAPPER, "return NeverLeakReportNames::accumulator_reason_name(reason)"),
    (VT_WRAPPER, "return NeverLeakReportNames::value_thread_reason_name(reason)"),
    (PHRASE_WRAPPER, "return NeverLeakReportNames::category_phrase(finding.category, finding.escapes)"),
):
    if expected not in file.read_text():
        raise SystemExit(f"driver wrapper in {file.name} no longer delegates to the proved table")
for file in MODE_REPORTERS:
    report_text = file.read_text()
    if "mode == 2" in report_text or "mode == 2 else" in report_text:
        raise SystemExit(f"{file.name} reintroduced the raw never-leak error mode code")
    if "NeverLeakReportNames::severity_prefix(mode)" not in report_text:
        raise SystemExit(f"{file.name} no longer uses the source-linked severity policy")
if not all(call in STAT_REPORTER.read_text() for call in (
    "nl_category_name(finding.category)",
    "nl_acc_reason_name(reason)",
    "nl_vt_reason_name(reason)",
)):
    raise SystemExit("never-leak stats output no longer uses the proved label wrappers")

for proof in (POSITIVE, NEGATIVE):
    proof_text = proof.read_text()
    for include in (
        '../../src/semantic/binding_identity_types.elisa',
        '../../src/semantic/never_leak_codes.elisa',
        '../../src/driver/never_leak_report_names.elisa',
    ):
        if f'include "{include}"' not in proof_text:
            raise SystemExit(f"{proof.name} must include production source {include}")

source_files = source_include_closure([
    POSITIVE, NEGATIVE, SEMANTIC, ANALYZER, DRIVER, CATEGORY_WRAPPER, VT_WRAPPER,
    PHRASE_WRAPPER, *MODE_REPORTERS,
])
try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("never-leak report-name proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    *source_files,
]
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
expected_proofs = {
    "category_name_matches_the_complete_code_table",
    "accumulator_reason_name_matches_the_complete_code_table",
    "value_thread_reason_name_matches_the_complete_code_table",
}
assert expected_proofs <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == {
    "chain_category_is_plain", "accumulator_escape_is_written_after", "borrowed_field_is_global"
}
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "never-leak category and reason labels used by production stats output",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(row["name"] for row in negative["findings"]),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
