"""Admit the noninterference proof for Stage1's SMT option switches."""
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
PROJECTION = ROOT / "src/driver/stage1_semantic_option_projection.elisa"
SOURCE_PROBES = ROOT / "src/driver/elisac_source_probes.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
POSITIVE = HERE / "stage1_semantic_option_noninterference.elisa"
NEGATIVE = HERE / "stage1_semantic_option_noninterference_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")

projection_text = PROJECTION.read_text()
source_probes_text = SOURCE_PROBES.read_text()
driver_text = DRIVER.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
fields = (
    "enforce_unsafe_permissions", "flow_strict", "runtime_std", "flow_warn",
    "enable_smt", "warn_discarded", "enforce_progress", "enforce_extern_contracts",
    "enforce_raw_unsafe", "emit_proof_hole", "region_stack_cap",
    "enforce_global_permissions", "enforce_mutable_global_grants", "carrier_surface",
)
if 'include "../../src/driver/stage1_semantic_option_projection.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer imports the production Stage1 projection")
if 'include "./stage1_semantic_option_noninterference.elisa"' not in negative_text:
    raise SystemExit("negative controls no longer import the positive noninterference proof")
if "ensure result.enable_smt == (smt_environment_enabled or smt_header)" not in projection_text:
    raise SystemExit("production SMT policy no longer combines its environment and header observations")
if "const STAGE1_REGION_STACK_CAP: i64 = 64" not in projection_text:
    raise SystemExit("Stage1 region stack cap changed without updating its named policy constant")
if "ensure result.region_stack_cap == STAGE1_REGION_STACK_CAP" not in projection_text:
    raise SystemExit("Stage1 region stack cap is no longer covered by the projection contract")
if 'include "./stage1_semantic_option_projection.elisa"' not in source_probes_text:
    raise SystemExit("Stage1 source probes no longer include the proved semantic-option projection")
if 'include "./elisac_source_probes.elisa"' not in driver_text:
    raise SystemExit("compiler driver no longer includes the production source-probe boundary")
expected_projection_call = (
    "returnstage1_semantic_options_from_observations("
    "source_has_strict_header(src_ptr,source_len),"
    "runtime_std_enabled(src_ptr,source_len),"
    'env_flag_enabled("ELISA_STAGE1_SMT"),'
    "source_has_smt_header(src_ptr,source_len),"
    'env_flag_enabled("ELISA_STAGE1_STRICT_EXTERNS"),'
    'source_has_header(src_ptr,source_len,"strict-externs"),'
    "source_has_unsafe_header(src_ptr,source_len),"
    "source_has_proofhole_header(src_ptr,source_len),"
    "source_has_global_header(src_ptr,source_len),"
    'env_flag_enabled("ELISA_STAGE1_PERMISSIVE"),'
    "carrier_surface_applies()"
    ")"
)
stage1_start = source_probes_text.find("def stage1_semantic_options(src_ptr: u8&, source_len: usize)")
stage1_end = source_probes_text.find("\ndef run_semantic_gate_with_snapshot(", stage1_start)
if stage1_start < 0 or stage1_end < 0:
    raise SystemExit("production Stage1 semantic-option boundary is missing")
stage1_body = "".join(source_probes_text[stage1_start:stage1_end].split())
if expected_projection_call not in stage1_body:
    raise SystemExit("Stage1 source/environment observations no longer feed the proved projection in order")
if "Semantic::incremental_semantic_options_from_values(" in stage1_body:
    raise SystemExit("Stage1 production bypasses the proved option projection")
if not all(
    f"ensure result.{field} ==" in projection_text
    for field in fields
    if field != "enforce_mutable_global_grants"
):
    raise SystemExit("production projection no longer specifies every option output")
if "ensure result.enforce_mutable_global_grants != permissive_environment_enabled" not in projection_text:
    raise SystemExit("production projection no longer specifies every option output")
if "def same_non_smt_options(" not in positive_text or "def smt_sources_change_only_the_smt_option(" not in positive_text:
    raise SystemExit("positive noninterference theorem is missing")

positive_names = {
    "same_non_smt_options",
    "smt_sources_change_only_the_smt_option",
}
for name in positive_names:
    if f"def {name}(" not in positive_text:
        raise SystemExit(f"positive theorem missing: {name}")
negative_names = {
    "an_environment_smt_switch_also_enables_strict_flow",
    "a_header_smt_switch_is_ignored",
}
for name in negative_names:
    if f"def {name}(" not in negative_text:
        raise SystemExit(f"negative control missing: {name}")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("Stage1 option noninterference proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != product_manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")


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
    DRIVER,
    SOURCE_PROBES,
    *include_closure([POSITIVE, NEGATIVE]),
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
assert positive == run(POSITIVE)[1], "Stage1 noninterference report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product_manifest
print(json.dumps({
    "admitted": True,
    "scope": "the SMT source and environment observations change only enable_smt",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
