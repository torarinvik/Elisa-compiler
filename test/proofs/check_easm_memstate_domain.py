"""Admit EASM memory-size bound proofs against a strict Elisa-proof product."""
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
POSITIVE = HERE / "easm_memstate_domain.elisa"
NEGATIVE = HERE / "easm_memstate_domain_rejected.elisa"
HELPER = ROOT / "src/backend/easm_memstate_domain.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")
environment = ENV.read_text()
if 'include "easm_memstate_domain.elisa"' not in environment:
    raise SystemExit("backend environment no longer imports the proved EASM memory-state domain")
if environment.index('include "easm_memstate_domain.elisa"') > environment.index('include "easm_model.elisa"'):
    raise SystemExit("EASM memory-state domain is imported after its consumers")
if 'include "../../src/backend/easm_memstate_domain.elisa"' not in POSITIVE.read_text():
    raise SystemExit("proof no longer imports the production memory-state domain")
helper = HELPER.read_text()
if "".join("ensure result >= left".split()) not in "".join(helper.split()) or \
        "".join("ensure result >= right".split()) not in "".join(helper.split()):
    raise SystemExit("production maximum operation no longer exposes both lower-bound monotonicity guarantees")
if "".join("ensure result == (need <= left and need <= right)".split()) not in "".join(helper.split()):
    raise SystemExit("production joined read guard no longer states the exact two-predecessor safety condition")

memory = MEMORY.read_text()
lower_bound_body = memory.split("def easm_size_guard_lower_bound(", 1)[1].split("\n\n        def ", 1)[0]
if "".join("greatest <- EasmMemStateDomain::greatest_bound(greatest, value)".split()) not in "".join(lower_bound_body.split()):
    raise SystemExit("production size-fact lower-bound fold no longer uses the proved maximum operation")
lower_bound_compact = "".join(lower_bound_body.split())
if "ensureresult>=0" not in lower_bound_compact or \
        "whileindex<facts.count|index,facts,greatest|:" not in lower_bound_compact or \
        "decreasesfacts.count-index" not in lower_bound_compact or \
        "invariantindex<=facts.count" not in lower_bound_compact or \
        "invariantgreatest>=0" not in lower_bound_compact:
    raise SystemExit("production size-fact fold no longer proves its accumulator stays a nonnegative lower bound")
wrappers = {
    "easm_memstate_join_min": "EasmMemStateDomain::join_min(left, right)",
    "easm_memstate_read_well_typed": "EasmMemStateDomain::read_well_typed(need, known_min)",
    "easm_memstate_guard_join": "EasmMemStateDomain::guard_join(left, right, need)",
}
for name, call in wrappers.items():
    body = memory.split(f"def {name}(", 1)[1].split("\n\n        def ", 1)[0]
    if f"return {call}" not in body:
        raise SystemExit(f"{name} no longer delegates to its proved memory-state operation")
if "not easm_memstate_read_well_typed(field.requires_size_at_least, easm_size_guard_lower_bound(fn.facts))" not in memory:
    raise SystemExit("production overlay-read admission no longer uses the proved memory-state read predicate")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("EASM memory-state proof requires a strict proof build")

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
    MEMORY,
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
    "join_min",
    "greatest_bound",
    "read_well_typed",
    "guard_join",
    "minimum_join_never_exceeds_left_bound",
    "minimum_join_never_exceeds_right_bound",
    "minimum_join_selects_an_incoming_bound",
    "minimum_join_is_idempotent",
    "greatest_bound_never_falls_below_left_fact",
    "greatest_bound_never_falls_below_right_fact",
    "greatest_bound_selects_an_incoming_fact",
    "greatest_bound_is_idempotent",
    "greatest_bound_is_commutative",
    "greatest_bound_is_associative",
    "greatest_bound_is_monotone_in_both_facts",
    "joined_path_read_accepts_exactly_when_each_path_has_a_covering_fact",
    "joined_read_guard_is_the_minimum_bound_read",
    "minimum_read_acceptance_implies_each_predecessor",
    "each_predecessor_bound_implies_minimum_read_acceptance",
    "minimum_join_is_commutative",
    "both_predecessors_satisfy_bound_then_join_accepts",
    "joined_guard_rejects_a_read_oversized_for_either_predecessor",
    "minimum_join_is_associative",
    "minimum_join_is_monotone_in_both_predecessors",
    "any_shared_lower_bound_is_below_the_minimum_join",
    "joined_read_guard_accepts_exactly_when_both_predecessors_cover_the_read",
    "joined_read_guard_rejects_exactly_when_a_predecessor_is_too_small",
}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["proven"] + 3 == negative["summary"]["obligations"]
false_claims = {
    "join_guard_accepts_a_read_missing_from_one_branch",
    "greatest_bound_discards_the_stronger_fact",
    "joined_path_accepts_without_a_covering_fact_on_the_right",
}
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in false_claims
}
assert not false_claims & {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "EASM path-minimum and same-path-maximum composition, nonnegative production size-fact fold, and production overlay-read predicate",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(false_claims),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
