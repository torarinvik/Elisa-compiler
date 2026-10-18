"""Admit the affine checker's linear-resource exit transition against production."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check production and proof bindings without running Elisa-Proof")
ARGS = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/semantic/linear_exit_leak_policy.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
AFFINE = ROOT / "src/semantic/check_affine_use_linear.elisa"
POSITIVE = HERE / "linear_exit_leak_policy.elisa"
NEGATIVE = HERE / "linear_exit_leak_policy_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost[ \t]+)?def |^{re.escape(indent)}(?:public|private):", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


policy_text = POLICY.read_text()
if compact("""
    struct LinearExitScanStep:
        stopped: bool
        report: bool
""") not in compact(policy_text):
    raise SystemExit("production linear exit policy lost its named scan-step result")
expected_policy = {
    "previous_scan_index_spec": """
        ghost def previous_scan_index_spec(index: usize, count: usize) -> usize:
            requires index > 0 and index <= count
            return index - 1
    """,
    "previous_scan_index": """
        def previous_scan_index(index: usize, count: usize) -> usize:
            requires index > 0 and index <= count
            ensure result == previous_scan_index_spec(index, count)
            ensure result < count
            return index - 1
    """,
    "name_present_from": """
        ghost def name_present_from(names: darray[sview]&, wanted: sview, index: usize) -> bool:
            requires index <= names.count
            decreases names.count - index
            return false if index == names.count
            return true if names[index] == wanted
            return name_present_from(names, wanted, index + 1.usize())
    """,
    "name_present_spec": """
        ghost def name_present_spec(names: darray[sview]&, wanted: sview) -> bool:
            return name_present_from(names, wanted, 0)
    """,
    "name_present": """
        def name_present(names: darray[sview]&, wanted: sview) -> bool:
            ensure result == name_present_spec(names, wanted)
            index: mutable usize = 0
            while index < names.count |index|:
                decreases names.count - index
                invariant index <= names.count
                invariant name_present_from(names, wanted, index) == name_present_from(names, wanted, 0)
                if names[index] == wanted:
                    return true
                index <- index + 1
            return false
    """,
    "scan_step_stopped_spec": """
        ghost def scan_step_stopped_spec(scope_name: sview, stopped: bool, loop_only: bool) -> bool:
            return stopped or (loop_only and scope_name == "")
    """,
    "scan_step_report_spec": """
        ghost def scan_step_report_spec(scope_name: sview, stopped: bool, loop_only: bool, consumed: darray[sview]&, leaked: darray[sview]&) -> bool:
            return (
                scope_name != "" and not scan_step_stopped_spec(scope_name, stopped, loop_only) and
                not name_present_spec(consumed, scope_name) and
                not name_present_spec(leaked, scope_name)
            )
    """,
    "scan_step_spec": """
        ghost def scan_step_spec(scope_name: sview, stopped: bool, loop_only: bool, consumed: darray[sview]&, leaked: darray[sview]&) -> LinearExitScanStep:
            return LinearExitScanStep{
                stopped: scan_step_stopped_spec(scope_name, stopped, loop_only),
                report: scan_step_report_spec(scope_name, stopped, loop_only, consumed, leaked)
            }
    """,
    "scan_step": """
        def scan_step(scope_name: sview, stopped: bool, loop_only: bool, consumed: darray[sview]&, leaked: darray[sview]&) -> LinearExitScanStep can[Abort.Panic]:
            ensure result.stopped == scan_step_stopped_spec(scope_name, stopped, loop_only)
            ensure result.report == scan_step_report_spec(scope_name, stopped, loop_only, consumed, leaked)
            can Abort.Panic:
                stopped_after: bool = stopped or (loop_only and scope_name == "")
                report: bool = scope_name != "" and not stopped_after and
                    not name_present(consumed, scope_name) and
                    not name_present(leaked, scope_name)
                answer: LinearExitScanStep = LinearExitScanStep{stopped: stopped_after, report: report}
                assert answer.stopped == scan_step_stopped_spec(scope_name, stopped, loop_only)
                assert answer.report == scan_step_report_spec(scope_name, stopped, loop_only, consumed, leaked)
                return answer
    """,
}
for name, expected in expected_policy.items():
    if compact(function_section(policy_text, name)) != compact(expected):
        raise SystemExit(f"production linear exit policy changed: {name}")

semantic_text = SEMANTIC.read_text()
policy_include = 'include "./linear_exit_leak_policy.elisa"'
affine_include = 'include "./check_affine_use_linear.elisa"'
if policy_include not in semantic_text or affine_include not in semantic_text or \
        semantic_text.index(policy_include) > semantic_text.index(affine_include):
    raise SystemExit("semantic module must load the exit policy before the affine checker")

exit_scan = compact(function_section(AFFINE.read_text(), "linear_exit_leaks"))
for required in (
    "for scan_offset in 0..<in_scope.count",
    "scope_index: usize = in_scope.count - (scan_offset + 1)",
    "scope_name: sview = in_scope[scope_index]",
    "step: SemanticLinearExitLeakPolicy::LinearExitScanStep = SemanticLinearExitLeakPolicy::scan_step(scope_name, stopped, loop_only, consumed, leaked)",
    "stopped <- step.stopped",
    "leaked.push(scope_name) if step.report",
):
    if compact(required) not in exit_scan:
        raise SystemExit(f"production linear exit scan lost policy-bound transition: {required}")
if "not affine_consumed(consumed, scope_name)" in exit_scan or \
        "not affine_consumed(leaked, scope_name)" in exit_scan:
    raise SystemExit("linear exit scan must delegate consumed/leaked filtering to the proved policy")

positive_names = {
    "previous_scan_index_matches_its_spec",
    "previous_scan_index_is_in_bounds",
    "first_scan_slot_predecessor_is_zero",
    "final_scope_predecessor_stays_in_bounds",
    "scan_step_matches_its_transition_spec",
    "loop_sentinel_stops_and_is_not_reported",
    "stopped_state_is_sticky_for_outer_scope",
    "return_scan_ignores_loop_sentinel",
    "live_unconsumed_scope_is_reported",
    "consumed_scope_is_not_reported",
    "previously_reported_scope_is_not_reported_twice",
    "scope_before_loop_sentinel_remains_reportable",
}
negative_names = {
    "first_scan_slot_predecessor_is_one",
    "final_scope_predecessor_reaches_count",
    "loop_sentinel_does_not_stop_scan",
    "stopped_state_is_cleared",
    "consumed_scope_is_reported",
    "previously_reported_scope_is_reported_again",
    "loop_sentinel_is_reported_as_a_resource",
}

positive_bodies = {
    "previous_scan_index_matches_its_spec": """
        requires index > 0 and index <= count
        ensure result == true
        return SemanticLinearExitLeakPolicy::previous_scan_index(index, count) == SemanticLinearExitLeakPolicy::previous_scan_index_spec(index, count)
    """,
    "previous_scan_index_is_in_bounds": """
        requires index > 0 and index <= count
        ensure result == true
        return SemanticLinearExitLeakPolicy::previous_scan_index(index, count) < count
    """,
    "first_scan_slot_predecessor_is_zero": """
        ensure result == true
        return SemanticLinearExitLeakPolicy::previous_scan_index(1.usize(), 1.usize()) == 0.usize()
    """,
    "final_scope_predecessor_stays_in_bounds": """
        requires count > 0
        ensure result == true
        return SemanticLinearExitLeakPolicy::previous_scan_index(count, count) < count
    """,
    "scan_step_matches_its_transition_spec": """
        ensure result == true
        can Abort.Panic:
            step: SemanticLinearExitLeakPolicy::LinearExitScanStep = SemanticLinearExitLeakPolicy::scan_step(scope_name, stopped, loop_only, consumed, leaked)
            assert step.stopped == SemanticLinearExitLeakPolicy::scan_step_spec(scope_name, stopped, loop_only, consumed, leaked).stopped
            assert step.report == SemanticLinearExitLeakPolicy::scan_step_spec(scope_name, stopped, loop_only, consumed, leaked).report
            return true
    """,
    "loop_sentinel_stops_and_is_not_reported": """
        ensure result == true
        can Abort.Panic:
            step: SemanticLinearExitLeakPolicy::LinearExitScanStep = SemanticLinearExitLeakPolicy::scan_step("", false, true, [], [])
            return step.stopped and not step.report
    """,
    "stopped_state_is_sticky_for_outer_scope": """
        ensure result == true
        can Abort.Panic:
            step: SemanticLinearExitLeakPolicy::LinearExitScanStep = SemanticLinearExitLeakPolicy::scan_step("outer", true, true, [], [])
            return step.stopped and not step.report
    """,
    "return_scan_ignores_loop_sentinel": """
        ensure result == true
        can Abort.Panic:
            step: SemanticLinearExitLeakPolicy::LinearExitScanStep = SemanticLinearExitLeakPolicy::scan_step("", false, false, [], [])
            return not step.stopped and not step.report
    """,
    "live_unconsumed_scope_is_reported": """
        ensure result == true
        can Abort.Panic:
            step: SemanticLinearExitLeakPolicy::LinearExitScanStep = SemanticLinearExitLeakPolicy::scan_step("resource", false, false, [], [])
            return not step.stopped and step.report
    """,
    "consumed_scope_is_not_reported": """
        ensure result == true
        can Abort.Panic:
            step: SemanticLinearExitLeakPolicy::LinearExitScanStep = SemanticLinearExitLeakPolicy::scan_step("resource", false, false, ["resource"], [])
            return not step.report
    """,
    "previously_reported_scope_is_not_reported_twice": """
        ensure result == true
        can Abort.Panic:
            step: SemanticLinearExitLeakPolicy::LinearExitScanStep = SemanticLinearExitLeakPolicy::scan_step("resource", false, false, [], ["resource"])
            return not step.report
    """,
    "scope_before_loop_sentinel_remains_reportable": """
        ensure result == true
        can Abort.Panic:
            step: SemanticLinearExitLeakPolicy::LinearExitScanStep = SemanticLinearExitLeakPolicy::scan_step("inner", false, true, [], [])
            return not step.stopped and step.report
    """,
}
negative_bodies = {
    "first_scan_slot_predecessor_is_one": """
        ensure result == true
        return SemanticLinearExitLeakPolicy::previous_scan_index(1.usize(), 1.usize()) == 1.usize()
    """,
    "final_scope_predecessor_reaches_count": """
        requires count > 0
        ensure result == true
        return SemanticLinearExitLeakPolicy::previous_scan_index(count, count) >= count
    """,
    "loop_sentinel_does_not_stop_scan": """
        ensure result == true
        can Abort.Panic:
            step: SemanticLinearExitLeakPolicy::LinearExitScanStep = SemanticLinearExitLeakPolicy::scan_step("", false, true, [], [])
            return not step.stopped
    """,
    "stopped_state_is_cleared": """
        ensure result == true
        can Abort.Panic:
            step: SemanticLinearExitLeakPolicy::LinearExitScanStep = SemanticLinearExitLeakPolicy::scan_step("outer", true, true, [], [])
            return not step.stopped
    """,
    "consumed_scope_is_reported": """
        ensure result == true
        can Abort.Panic:
            step: SemanticLinearExitLeakPolicy::LinearExitScanStep = SemanticLinearExitLeakPolicy::scan_step("resource", false, false, ["resource"], [])
            return step.report
    """,
    "previously_reported_scope_is_reported_again": """
        ensure result == true
        can Abort.Panic:
            step: SemanticLinearExitLeakPolicy::LinearExitScanStep = SemanticLinearExitLeakPolicy::scan_step("resource", false, false, [], ["resource"])
            return step.report
    """,
    "loop_sentinel_is_reported_as_a_resource": """
        ensure result == true
        can Abort.Panic:
            step: SemanticLinearExitLeakPolicy::LinearExitScanStep = SemanticLinearExitLeakPolicy::scan_step("", false, true, [], [])
            return step.report
    """,
}


def proof_body(source: str, name: str) -> str:
    section = function_section(source, name)
    colon = section.find(":\n")
    if colon < 0:
        raise SystemExit(f"could not find proof body for {name}")
    return compact(section[colon + 2:]).replace("can Abort.Panic: ", "")


def check_claims(path: Path, expected: dict[str, str], label: str) -> None:
    source = path.read_text()
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", source))
    if actual != set(expected):
        raise SystemExit(f"{label} theorem inventory changed")
    if '../../src/semantic/linear_exit_leak_policy.elisa' not in source:
        raise SystemExit(f"{label} proof must import the production policy")
    for name in expected:
        section = function_section(source, name)
        expects_effect_handler = "can Abort.Panic:" in expected[name]
        if section.count("can Abort.Panic:") != (1 if expects_effect_handler else 0):
            raise SystemExit(f"{label} theorem must handle the policy effect: {name}")
        if proof_body(source, name) != compact(expected[name]):
            raise SystemExit(f"{label} theorem body changed: {name}")


check_claims(POSITIVE, positive_bodies, "positive")
check_claims(NEGATIVE, negative_bodies, "negative")

if ARGS.source_only:
    print(json.dumps({
        "source_bound": True,
        "positive_theorems": len(positive_bodies),
        "false_controls": len(negative_bodies),
        "proof_closure_files": len(source_include_closure([POSITIVE, NEGATIVE])),
    }, sort_keys=True))
    raise SystemExit(0)

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("linear exit leak proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"), PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POSITIVE, NEGATIVE, POLICY, SEMANTIC, AFFINE,
]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"] and not positive["findings"]
assert positive == run(POSITIVE)[1], "linear exit proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] - negative["summary"]["proven"] == len(negative_names)
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "loop-sentinel transition and linear leak reporting on return/break/continue",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
