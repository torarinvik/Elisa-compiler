"""Admission gate for the imported Boolean ownership-domain laws, not compiler flow."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROVER = ROOT.parent / "wasmbrowser-proof"
BIN = Path(os.environ.get("ELISA_PROOF_BIN", str(PROVER / "build/elisa-proof-ownership-flow"))).resolve(strict=True)
if not __debug__:
    raise SystemExit("run without Python -O")
if any(path.stat().st_mtime_ns > BIN.stat().st_mtime_ns for path in (PROVER / "src").rglob("*.elisa")):
    raise SystemExit("proof executable is older than prover source; rebuild it")
inputs = [BIN, Path(__file__), ROOT / "src/semantic/ownership_flow_domain.elisa",
          HERE / "ownership_flow_domain.elisa", HERE / "ownership_flow_domain_rejected.elisa",
          HERE / "ownership_reachable_join.elisa", HERE / "ownership_loop_head.elisa",
          HERE / "ownership_loop_head_rejected.elisa", HERE / "ownership_for_head.elisa",
          HERE / "ownership_for_head_rejected.elisa", ROOT / "src/semantic/protocol_owner_domain.elisa",
          HERE / "protocol_owner_eligibility.elisa", HERE / "protocol_owner_eligibility_rejected.elisa",
          HERE / "protocol_module_authority.elisa", HERE / "protocol_module_authority_rejected.elisa",
          HERE / "protocol_family_identity.elisa", HERE / "protocol_family_identity_rejected.elisa",
          HERE / "derived_update_policy.elisa", HERE / "derived_update_policy_rejected.elisa",
          HERE / "derived_rule_selection.elisa", HERE / "derived_rule_selection_rejected.elisa",
          HERE / "qualified_type_application.elisa", HERE / "qualified_type_application_rejected.elisa",
          HERE / "derived_snapshot_knowledge.elisa", HERE / "derived_snapshot_knowledge_rejected.elisa",
          HERE / "derived_result_refutation.elisa", HERE / "derived_result_refutation_rejected.elisa",
          HERE / "derived_dependency_join.elisa", HERE / "derived_dependency_join_rejected.elisa"]
hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}

def run(name):
    process = subprocess.run([str(BIN), "--json", str(HERE / name)], capture_output=True, text=True, timeout=30)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    assert not report["trust"]["trusted_assumptions"]
    return process.returncode, report

code, positive = run("ownership_flow_domain.elisa")
assert code == 0 and positive["status"] == "proved" and positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"] == 36
assert positive == run("ownership_flow_domain.elisa")[1], "proof reports changed across repeats"
algebraic_names = {"possible_commutative", "possible_idempotent", "possible_associative",
              "possible_empty_identity", "known_commutative", "known_idempotent",
              "known_associative"}
assert not positive["findings"]
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {"join_possible", "join_known", "can_move", "possible_preserves_consumed",
        "unknown_stays_unknown", "unknown_blocks_move", "unreachable_blocks_move",
        "live_owner_can_move", "consumed_blocks_move"} <= verified
assert algebraic_names <= verified
assert {"join_reachable_possible", "join_reachable_known"} <= verified
assert len(verified) == 18
assert all(row.get("verified") for row in positive["declaration_details"] if row["kind"] == "function")
code, negative = run("ownership_flow_domain_rejected.elisa")
assert code == 1 and negative["status"] == "failed"
false_names = {"false_join_discards_consumed", "false_unknown_is_known",
               "false_consumed_can_move", "false_unknown_can_move", "false_join_drops_peer",
               "false_join_changes_operator", "false_known_uses_or"}
assert {finding["name"] for finding in negative["findings"]} == false_names
assert all(finding["kind"] == "ensure-unproven" for finding in negative["findings"])
assert not false_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
code, reachable = run("ownership_reachable_join.elisa")
assert code == 0 and reachable["status"] == "proved"
assert reachable["summary"]["proven"] == reachable["summary"]["obligations"] == 16
assert reachable == run("ownership_reachable_join.elisa")[1]
assert not reachable["findings"]
code, loop = run("ownership_loop_head.elisa")
assert code == 0 and loop["status"] == loop["verification_state"] == "proved"
assert loop["summary"]["proven"] == loop["summary"]["obligations"] == 20
assert loop == run("ownership_loop_head.elisa")[1]
assert not loop["findings"]
assert {"entry_path_remains_possible", "consumed_back_edge_is_retained", "dead_back_edge_preserves_entry",
        "dead_back_edge_preserves_knowledge", "unknown_back_edge_loses_knowledge"} <= {row["name"] for row in loop["declaration_details"] if row.get("verified")}
code, loop_rejected = run("ownership_loop_head_rejected.elisa")
loop_false_names = {"dead_back_edge_can_flip_entry", "unknown_back_edge_grants_knowledge"}
assert code == 1 and loop_rejected["status"] == "failed"
assert {finding["name"] for finding in loop_rejected["findings"]} == loop_false_names
assert all(finding["kind"] == "ensure-unproven" for finding in loop_rejected["findings"])
assert not loop_false_names & {row["name"] for row in loop_rejected["declaration_details"] if row.get("verified")}
code, for_head = run("ownership_for_head.elisa")
assert code == 0 and for_head["status"] == for_head["verification_state"] == "proved"
assert for_head["summary"]["proven"] == for_head["summary"]["obligations"] == 14
assert for_head == run("ownership_for_head.elisa")[1]
assert not for_head["findings"]
assert {"repeated_consume_blocks_move", "returning_body_preserves_move"} <= {row["name"] for row in for_head["declaration_details"] if row.get("verified")}
code, for_rejected = run("ownership_for_head_rejected.elisa")
assert code == 1 and for_rejected["status"] == "failed"
assert {finding["name"] for finding in for_rejected["findings"]} == {"repeated_consume_grants_move"}
assert all(finding["kind"] == "ensure-unproven" for finding in for_rejected["findings"])
code, protocol_owner = run("protocol_owner_eligibility.elisa")
assert code == 0 and protocol_owner["status"] == protocol_owner["verification_state"] == "proved"
assert protocol_owner["summary"]["proven"] == protocol_owner["summary"]["obligations"] == 28
assert protocol_owner == run("protocol_owner_eligibility.elisa")[1]
assert not protocol_owner["findings"]
assert all(row.get("verified") for row in protocol_owner["declaration_details"] if row["kind"] == "function")
code, protocol_rejected = run("protocol_owner_eligibility_rejected.elisa")
assert code == 1 and protocol_rejected["status"] == "failed"
protocol_false_names = {"borrowed_alias_grants_ownership", "different_family_grants_ownership"}
assert {finding["name"] for finding in protocol_rejected["findings"]} == protocol_false_names
assert all(finding["kind"] == "ensure-unproven" for finding in protocol_rejected["findings"])
code, authority = run("protocol_module_authority.elisa")
assert code == 0 and authority["status"] == authority["verification_state"] == "proved"
assert authority["summary"]["proven"] == authority["summary"]["obligations"] == 26
assert authority == run("protocol_module_authority.elisa")[1]
assert not authority["findings"]
assert all(row.get("verified") for row in authority["declaration_details"] if row["kind"] == "function")
code, authority_rejected = run("protocol_module_authority_rejected.elisa")
assert code == 1 and authority_rejected["status"] == "failed"
authority_false_names = {"peer_module_has_authority", "root_owns_every_module", "one_legal_state_is_enough"}
assert {finding["name"] for finding in authority_rejected["findings"]} == authority_false_names
assert all(finding["kind"] == "ensure-unproven" for finding in authority_rejected["findings"])
code, family_identity = run("protocol_family_identity.elisa")
assert code == 0 and family_identity["status"] == family_identity["verification_state"] == "proved"
assert family_identity["summary"]["proven"] == family_identity["summary"]["obligations"] == 10
assert family_identity == run("protocol_family_identity.elisa")[1]
assert not family_identity["findings"]
assert all(row.get("verified") for row in family_identity["declaration_details"] if row["kind"] == "function")
code, family_rejected = run("protocol_family_identity_rejected.elisa")
assert code == 1 and family_rejected["status"] == "failed"
assert {finding["name"] for finding in family_rejected["findings"]} == {"same_state_ordinal_merges_families"}
assert all(finding["kind"] == "ensure-unproven" for finding in family_rejected["findings"])
code, derived_update = run("derived_update_policy.elisa")
assert code == 0 and derived_update["status"] == derived_update["verification_state"] == "proved"
assert derived_update["summary"]["proven"] == derived_update["summary"]["obligations"] == 16
assert derived_update == run("derived_update_policy.elisa")[1]
assert not derived_update["findings"]
assert all(row.get("verified") for row in derived_update["declaration_details"] if row["kind"] == "function")
code, derived_rejected = run("derived_update_policy_rejected.elisa")
assert code == 1 and derived_rejected["status"] == "failed"
derived_false_names = {"unknown_singleton_proves_state", "changed_predicate_preserves_input"}
assert {finding["name"] for finding in derived_rejected["findings"]} == derived_false_names
assert all(finding["kind"] == "ensure-unproven" for finding in derived_rejected["findings"])
code, selection = run("derived_rule_selection.elisa")
assert code == 0 and selection["status"] == selection["verification_state"] == "proved"
assert selection["summary"]["proven"] == selection["summary"]["obligations"] == 12
assert selection == run("derived_rule_selection.elisa")[1]
assert not selection["findings"]
assert all(row.get("verified") for row in selection["declaration_details"] if row["kind"] == "function")
code, selection_rejected = run("derived_rule_selection_rejected.elisa")
assert code == 1 and selection_rejected["status"] == "failed"
assert {finding["name"] for finding in selection_rejected["findings"]} == {"same_spelling_is_authority", "unresolved_rule_is_authority"}
assert all(finding["kind"] == "ensure-unproven" for finding in selection_rejected["findings"])
code, qualified = run("qualified_type_application.elisa")
assert code == 0 and qualified["status"] == qualified["verification_state"] == "proved"
assert qualified["summary"]["proven"] == qualified["summary"]["obligations"] == 10
assert qualified == run("qualified_type_application.elisa")[1]
assert not qualified["findings"]
assert all(row.get("verified") for row in qualified["declaration_details"] if row["kind"] == "function")
code, qualified_rejected = run("qualified_type_application_rejected.elisa")
assert code == 1 and qualified_rejected["status"] == "failed"
assert {finding["name"] for finding in qualified_rejected["findings"]} == {"shadowed_module_skips_index", "missing_nominal_skips_index"}
assert all(finding["kind"] == "ensure-unproven" for finding in qualified_rejected["findings"])
code, snapshot = run("derived_snapshot_knowledge.elisa")
assert code == 0 and snapshot["status"] == snapshot["verification_state"] == "proved"
assert snapshot["summary"]["proven"] == snapshot["summary"]["obligations"] == 12
assert snapshot == run("derived_snapshot_knowledge.elisa")[1]
assert not snapshot["findings"]
assert all(row.get("verified") for row in snapshot["declaration_details"] if row["kind"] == "function")
code, snapshot_rejected = run("derived_snapshot_knowledge_rejected.elisa")
assert code == 1 and snapshot_rejected["status"] == "failed"
assert {finding["name"] for finding in snapshot_rejected["findings"]} == {"constant_branch_erases_unknown_atom", "exhausted_budget_is_evidence"}
assert all(finding["kind"] == "ensure-unproven" for finding in snapshot_rejected["findings"])
code, refutation = run("derived_result_refutation.elisa")
assert code == 0 and refutation["status"] == refutation["verification_state"] == "proved"
assert refutation["summary"]["proven"] == refutation["summary"]["obligations"] == 12
assert refutation == run("derived_result_refutation.elisa")[1]
assert not refutation["findings"]
assert all(row.get("verified") for row in refutation["declaration_details"] if row["kind"] == "function")
code, refutation_rejected = run("derived_result_refutation_rejected.elisa")
assert code == 1 and refutation_rejected["status"] == "failed"
assert {finding["name"] for finding in refutation_rejected["findings"]} == {"undecided_means_contradiction", "true_predicate_is_contradiction"}
assert all(finding["kind"] == "ensure-unproven" for finding in refutation_rejected["findings"])
code, dependency = run("derived_dependency_join.elisa")
assert code == 0 and dependency["status"] == dependency["verification_state"] == "proved"
assert dependency["summary"]["proven"] == dependency["summary"]["obligations"] == 26
assert dependency == run("derived_dependency_join.elisa")[1]
assert not dependency["findings"]
assert all(row.get("verified") for row in dependency["declaration_details"] if row["kind"] == "function")
code, dependency_rejected = run("derived_dependency_join_rejected.elisa")
assert code == 1 and dependency_rejected["status"] == "failed"
assert {finding["name"] for finding in dependency_rejected["findings"]} == {"one_known_operand_is_enough", "one_unchanged_operand_is_enough"}
assert all(finding["kind"] == "ensure-unproven" for finding in dependency_rejected["findings"])
assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({"admitted": True, "scope": "imported Boolean ownership-domain laws only",
                  "proved": 36, "obligations": 36, "replayed": 36,
                  "reachable_join_report_proved": 16,
                  "loop_head_report_replayed": 20, "for_head_report_replayed": 14,
                  "for_false_claims_rejected": ["repeated_consume_grants_move"],
                  "protocol_owner_report_replayed": 28,
                  "protocol_owner_false_claims_rejected": sorted(protocol_false_names),
                  "protocol_authority_report_replayed": 26,
                  "protocol_authority_false_claims_rejected": sorted(authority_false_names),
                  "protocol_family_identity_report_replayed": 10,
                  "protocol_family_false_claims_rejected": ["same_state_ordinal_merges_families"],
                  "derived_dependency_join_report_replayed": 26,
                  "derived_result_refutation_report_replayed": 12,
                  "derived_snapshot_knowledge_report_replayed": 12,
                  "qualified_type_application_report_replayed": 10,
                  "derived_rule_selection_report_replayed": 12,
                  "derived_update_policy_report_replayed": 16,
                  "derived_update_false_claims_rejected": sorted(derived_false_names),
                  "loop_false_claims_rejected": sorted(loop_false_names),
                  "open_declarations": [], "false_claims_rejected": sorted(false_names),
                  "sources_sha256": hashes}, sort_keys=True))
