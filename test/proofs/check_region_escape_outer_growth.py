"""Admit source-linked proof of active-region container-growth escape detection."""
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
POSITIVE = HERE / "region_escape_outer_growth.elisa"
NEGATIVE = HERE / "region_escape_outer_growth_rejected.elisa"
IMPLEMENTATION = ROOT / "src/semantic/region_escape_stores.elisa"
INTEGRATION = ROOT / "src/semantic/check_region_escape.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")


def source_function(name: str) -> str:
    source = IMPLEMENTATION.read_text()
    start = source.find(f"def {name}(")
    if start < 0:
        raise SystemExit(f"production region-growth helper is missing: {name}")
    end = source.find("\n        def ", start + len(f"def {name}("))
    return "".join(re.sub(r"#.*$", "", source[start:end if end >= 0 else None],
                          flags=re.MULTILINE).split())


growth = source_function("region_escape_outer_growth")
growth_branches = (
    "return(false,sview(\"\",0,0),sview(\"\",0,0),sview(\"\",0,0))ifnotgrowth.foundorgrowth.receiver==\"\"ornesting.count==0",
    "return(false,sview(\"\",0,0),sview(\"\",0,0),sview(\"\",0,0))ifowner_region==store_region",
    "return(false,sview(\"\",0,0),sview(\"\",0,0),sview(\"\",0,0))ifnotowner_on_stack.foundandnotowner_is_param",
    "return(growth.found,growth.operation,store_region,owner_region)",
    "return(growth.found,growth.operation,store_region,sview(\"\",0,0))ifreceiver_is_outerorreceiver_is_global",
    "return(false,sview(\"\",0,0),sview(\"\",0,0),sview(\"\",0,0))",
)
for branch in growth_branches:
    if branch not in growth:
        raise SystemExit(f"production outer-growth decision changed without updating its proof: {branch}")
if "owner_on_stack: (found: bool, position: usize)".replace(" ", "") not in growth:
    raise SystemExit("outer-growth owner no longer checks lexical region ancestry")
if "owner_is_param: bool = region_escape_is_region_param(owner_region, annotations, line)".replace(" ", "") not in growth:
    raise SystemExit("outer-growth owner no longer distinguishes caller-owned region parameters")

store = source_function("region_escape_check_store")
consumer_branch = (
    "ifouter_growth.foundandnotstore_is_arena_value.found:"
    "growth_receiver:(found:bool,receiver:sview,operation:sview)=region_escape_growth_call_info(callee)"
    "growth_family:sview=region_growth_container_family(annotations,growth_receiver.receiver,line,local_names,local_types)"
    "table.diagnostics<-table.diagnostics.push(Diagnostic{kind:DiagnosticKind.RegionNestedGrowthEscape"
)
if consumer_branch not in store:
    raise SystemExit("container-growth result no longer gates its source diagnostic")
if "detail:growth_family})grow:" not in store:
    raise SystemExit("outer-growth diagnostic no longer proceeds to the independent element-store check")

expected = {
    "outer_growth_escape_result_is_exact",
    "growing_a_container_in_its_active_region_is_safe",
    "growth_through_an_enclosing_region_owner_is_an_escape",
    "growth_through_a_caller_region_parameter_is_an_escape",
    "unknown_sibling_owner_is_not_misreported_as_an_ancestor_escape",
    "unannotated_outer_local_growth_is_an_escape",
    "unannotated_mutable_global_growth_is_an_escape",
    "unannotated_local_container_growth_is_not_an_outer_escape",
    "growth_without_an_active_region_is_not_an_outer_growth_escape",
    "outer_growth_diagnostic_gate_is_exact",
    "detected_outer_growth_on_non_arena_receiver_emits_diagnostic",
    "arena_value_receiver_skips_outer_growth_diagnostic",
    "missing_outer_growth_skips_growth_diagnostic",
}
declarations = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", POSITIVE.read_text()))
if not expected <= declarations:
    raise SystemExit("outer-growth proof lost a branch or owner-boundary law")

integration = INTEGRATION.read_text()
if 'include "./region_escape_stores.elisa"' not in integration:
    raise SystemExit("region checker no longer includes outer-growth analysis")
if "region_escape_check_store(" not in integration:
    raise SystemExit("region checker no longer invokes the proved growth/element-store analysis")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("outer-growth proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
          *source_include_closure([POSITIVE, NEGATIVE, IMPLEMENTATION, INTEGRATION])]
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
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "growing_in_the_active_region_is_an_escape"),
    ("ensure-unproven", "unknown_sibling_owner_is_an_ancestor_escape"),
    ("ensure-unproven", "region_arena_value_receiver_still_gets_growth_diagnostic"),
]
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "nested-region container-growth allocator ownership and owner classification",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [row["name"] for row in negative["findings"]],
    "sources_sha256": hashes_before,
}, sort_keys=True))
