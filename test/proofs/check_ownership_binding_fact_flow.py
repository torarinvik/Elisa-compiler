"""Admit direct proofs of the source BindingId fact join and consume operations."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from proof_product_gate import require_current_product, source_include_closure

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = ROOT.parent / "elisa-proof"
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
PROOF_PROCESS_TIMEOUT_SECONDS = 60
if not __debug__:
    raise SystemExit("run without Python -O")
proof = HERE / "ownership_binding_fact_flow.elisa"
rejected = HERE / "ownership_binding_fact_flow_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
FACADE = ROOT / "src/semantic/semantic.elisa"
CONTROL_FLOW = ROOT / "src/semantic/ownership_control_flow.elisa"
semantic_sources = [ROOT / "src/semantic/binding_identity_types.elisa",
                    ROOT / "src/semantic/ownership_flow_domain.elisa",
                    ROOT / "src/semantic/ownership_binding_flow.elisa",
                    CONTROL_FLOW,
                    FACADE]
inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
          HERE / "proof_product_gate.py", Path(__file__), proof, rejected, *semantic_sources]
inputs.extend(source_include_closure([proof, rejected]))
hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}

def compact(source):
    return "".join(source.split())

binding_flow_source = compact(semantic_sources[2].read_text())
unknown_fact_contract = (
    "defownership_binding_unknown(id:BindingId,reachable:bool)->OwnershipBindingFact:"
    "ensureownership_binding_ids_equal(result.binding_id,id)"
    "ensureresult.reachable==reachable"
    "ensurenotresult.known"
    "ensureresult.may_live==reachable"
    "ensureresult.may_consumed==reachable"
    "returnOwnershipBindingFact{binding_id:id,reachable:reachable,known:false,may_live:reachable,may_consumed:reachable}"
)
if unknown_fact_contract not in binding_flow_source:
    raise SystemExit("unknown ownership facts no longer have the fail-closed source contract")

unknown_vector_contract = (
    "defownership_bindings_unknown(facts:mutabledarray[OwnershipBindingFact]&,reachable:bool)->voidcan[Abort.Panic]:"
    "ensureforallfact_indexin0..<facts.count:notfacts[fact_index].known"
    "andfacts[fact_index].reachable==reachable"
    "andfacts[fact_index].may_live==reachable"
    "andfacts[fact_index].may_consumed==reachable"
    "index:mutableusize=0"
    "whileindex<facts.count|index,facts|:"
    "decreasesfacts.count-index"
    "invariantindex<=facts.count"
    "invariantforallfact_indexin0..<index:notfacts[fact_index].known"
    "andfacts[fact_index].reachable==reachable"
    "andfacts[fact_index].may_live==reachable"
    "andfacts[fact_index].may_consumed==reachable"
    "fact:OwnershipBindingFact=facts[index]"
    "facts[index]<-ownership_binding_unknown(fact.binding_id,reachable)"
    "index<-index+1"
)
if unknown_vector_contract not in binding_flow_source:
    raise SystemExit("the ownership fallback no longer proves its all-rows loop invariant")

unknown_flow_source = compact(CONTROL_FLOW.read_text())
unknown_flow_contract = (
    "defownership_flow_unknown(flow:mutableOwnershipFrontier&)->voidcan[Abort.Panic]:"
    "ensurenotflow.coverage_complete"
    "flow.coverage_complete<-false"
    "ownership_bindings_unknown(&flow.facts,flow.reachable)"
)
if unknown_flow_contract not in unknown_flow_source:
    raise SystemExit("ownership flow fallback no longer establishes its whole-array unknown invariant")
facade_source = FACADE.read_text()
if 'include "./ownership_binding_flow.elisa"' not in facade_source or \
        'include "./ownership_control_flow.elisa"' not in facade_source or \
        facade_source.index('include "./ownership_binding_flow.elisa"') > facade_source.index('include "./ownership_control_flow.elisa"'):
    raise SystemExit("the source-bound unknown-fact contract must load before its control-flow consumer")
if 'include "../../src/semantic/ownership_binding_flow.elisa"' not in proof.read_text():
    raise SystemExit("positive ownership proof no longer includes the production fact-flow laws")
if 'include "./ownership_binding_fact_flow.elisa"' not in rejected.read_text():
    raise SystemExit("negative controls no longer extend the source-linked positive proof")

def declarations(path):
    return re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text())

expected_positive = {"matching_binding_join_is_componentwise", "foreign_left_binding_is_rejected",
                     "foreign_right_binding_is_rejected", "foreign_left_serial_is_rejected",
                     "foreign_right_serial_is_rejected", "invalid_identity_join_is_rejected",
                     "eligible_binding_is_consumed_once", "arbitrary_binding_fact_cannot_be_accepted_twice",
                     "failed_consumption_preserves_every_fact",
                     "unreachable_binding_cannot_be_consumed", "unknown_binding_cannot_be_consumed",
                     "accepted_consume_requires_every_move_precondition",
                     "consume_predicate_matches_exact_move_eligibility",
                     "accepted_consume_marks_arbitrary_eligible_fact_consumed",
                     "invalid_owner_cannot_be_consumed",
                     "unknown_fallback_preserves_identity_and_marks_both_possibilities",
                     "unknown_fallback_never_authorizes_consumption",
                     "unknown_fallback_clears_every_fact"}
expected_false = {"foreign_binding_can_join_as_known", "foreign_serial_binding_can_join_as_known",
                  "foreign_right_serial_binding_can_join_as_known", "foreign_fact_can_replace_join_target",
                  "consumed_binding_can_be_consumed_again", "arbitrary_binding_fact_can_be_accepted_twice",
                  "accepted_consume_may_leave_fact_live", "unknown_reachable_binding_can_be_consumed",
                  "unreachable_unknown_binding_can_be_live"}
positive_names = declarations(proof)
negative_names = declarations(rejected)
if len(positive_names) != len(set(positive_names)) or set(positive_names) != expected_positive:
    raise SystemExit("positive ownership proof declaration inventory changed")
if len(negative_names) != len(set(negative_names)) or set(negative_names) != expected_false:
    raise SystemExit("ownership false-claim declaration inventory changed")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error


def run(path):
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_PROCESS_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(proof)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(proof)[1], "proof report changed across repeats"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert expected_positive <= verified
assert all(row.get("verified") for row in positive["declaration_details"] if row["kind"] == "function")

code, negative = run(rejected)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == expected_false
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not expected_false & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product_manifest, "proof product or source tree changed during replay"
print(json.dumps({"admitted": True,
                  "scope": "BindingId-indexed joins, one-shot consume, and fail-closed unknown-state transitions; not CFG discovery or ownership legality",
                  "positive_obligations": positive["summary"]["proven"],
                  "independently_replayed": positive["replay"]["replayed"],
                  "false_claims_rejected": sorted(expected_false),
                  "sources_sha256": hashes}))
