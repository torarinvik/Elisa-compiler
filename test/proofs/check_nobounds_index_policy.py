"""Bind NoBoundsChecks range-evidence proofs to the semantic checker source."""
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
                    help="check production and proof bindings without invoking Elisa-Proof")
ARGS = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/semantic/nobounds_index_policy.elisa"
CHECKER = ROOT / "src/semantic/check_nobounds_index.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "nobounds_index_policy.elisa"
NEGATIVE = HERE / "nobounds_index_policy_rejected.elisa"
PROOF_TIMEOUT_SECONDS = 120

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost[ \t]+)?def |^{re.escape(indent)}(?:public|private):", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def proof_body(source: str, name: str) -> str:
    section = function_section(source, name)
    colon = section.find(":\n")
    if colon < 0:
        raise SystemExit(f"could not find proof body for {name}")
    return compact(section[colon + 2:]).replace("canAbort.Panic:", "")


policy_text = POLICY.read_text()
checker_text = CHECKER.read_text()
semantic_text = SEMANTIC.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_policy = {
    "matching_range_evidence_spec": """
        ghost def matching_range_evidence_spec(is_darray_parameter: bool, receiver: sview, index_name: sview, evidence_receiver: sview, evidence_index: sview) -> bool can[Abort.Panic]:
            return is_darray_parameter and receiver != "" and index_name != "" and receiver == evidence_receiver and index_name == evidence_index
    """,
    "matching_range_evidence": """
        def matching_range_evidence(is_darray_parameter: bool, receiver: sview, index_name: sview, evidence_receiver: sview, evidence_index: sview) -> bool can[Abort.Panic]:
            ensure result == matching_range_evidence_spec(is_darray_parameter, receiver, index_name, evidence_receiver, evidence_index)
            can Abort.Panic:
                return is_darray_parameter and receiver != "" and index_name != "" and receiver == evidence_receiver and index_name == evidence_index
    """,
    "should_report_unproven_spec": """
        ghost def should_report_unproven_spec(is_darray_parameter: bool, has_matching_range_evidence: bool) -> bool:
            return is_darray_parameter and not has_matching_range_evidence
    """,
    "should_report_unproven": """
        def should_report_unproven(is_darray_parameter: bool, has_matching_range_evidence: bool) -> bool:
            ensure result == should_report_unproven_spec(is_darray_parameter, has_matching_range_evidence)
            return is_darray_parameter and not has_matching_range_evidence
    """,
}
for name, expected in expected_policy.items():
    if compact(function_section(policy_text, name)) != compact(expected):
        raise SystemExit(f"production NoBoundsChecks policy changed: {name}")

if semantic_text.count('include "./nobounds_index_policy.elisa"') != 1 or \
        semantic_text.count('include "./check_nobounds_index.elisa"') != 1 or \
        semantic_text.index('include "./nobounds_index_policy.elisa"') > semantic_text.index('include "./check_nobounds_index.elisa"'):
    raise SystemExit("semantic root must load the proved policy exactly once before its consumer")

if "in_loop" in checker_text:
    raise SystemExit("NoBoundsChecks must not treat arbitrary loop membership as evidence")

range_section = compact(function_section(checker_text, "nb_loop_range_evidence"))
for required in (
    "return (\"\", \"\") if:\n    variables.count != 1\n    bind != \"\"",
    "operator!=TokenKind.RangeLt",
    "zero:(found:bool,value:i64)=signed_int_literal(lower)",
    "zero.value!=0",
    "Expr.Field(object,field,_)iffield==\"count\"",
    "receiver!=\"\"andreceiver!=variables[0]andnotnb_name_shadowed(receiver,shadowed_names)and(anynameindarray_paramswherename==receiver)and(anynameinimmutable_paramswherename==receiver)",
):
    if compact(required) not in range_section:
        raise SystemExit(f"counted-range recognizer lost required guard: {required}")

walk_section = compact(function_section(checker_text, "nb_walk"))
expr_section = compact(function_section(checker_text, "nb_expr"))
shadow_section = compact(function_section(checker_text, "nb_statements_write_evidence"))
for required in (
    "if nb_statements_write_evidence(statements, evidence_index, evidence_receiver, shadowed_names)",
    "SemanticNoBoundsIndexPolicy::matching_range_evidence(is_darray_param, object_name, index_name, evidence_receiver, evidence_index)",
    "SemanticNoBoundsIndexPolicy::should_report_unproven(is_darray_param, has_evidence)",
    "is_darray_param: bool = object_name != \"\" and (any p in darray_params where p == object_name)",
    "has_evidence: bool = not nb_name_shadowed(object_name, shadowed_names) and SemanticNoBoundsIndexPolicy::matching_range_evidence(is_darray_param, object_name, index_name, evidence_receiver, evidence_index)",
    "evidence.index_name if evidence.index_name != \"\" else (\"\" if shadows_outer else scan_index)",
    "block_shadows: bool = binding == scan_index or binding == scan_receiver",
    "nb_expr(arm.guard, darray_params, immutable_params, \"\", \"\", fn_name",
    "nb_walk(arm.body, darray_params, immutable_params, \"\", \"\", fn_name",
    "shadows_outer: bool = loop_variable == evidence_index or loop_variable == evidence_receiver",
    "nb_loop_range_evidence(iterable, variables, bind, darray_params, immutable_params, shadowed_names)",
    "Expr.Catch(guarded, arms, catch_line)",
    "nb_loop_range_evidence(iterable, [loop_variable], \"\", darray_params, immutable_params, shadowed_names)",
    "nb_walk(recovery, darray_params, immutable_params, evidence_index, evidence_receiver, fn_name",
    "block_index: sview = \"\" if nb_statements_write_evidence(statements, evidence_index, evidence_receiver, shadowed_names) else evidence_index",
    "return true if (target_name == index_name or target_name == receiver_name) and not nb_name_shadowed(target_name, scoped_shadowed)",
    "shadowed_names.push(name)",
    "if name == scan_index or name == scan_receiver",
    "then_shadowed: mutable darray[sview] = [name for name in shadowed_names]",
    "for_shadowed.push(variable)",
    "block_shadowed.push(binding) if binding != \"\"",
    "collect_pattern_binding_names(arm.pattern, arm_bindings)",
    "for binder in arm_bindings: arm_shadowed.push(binder)",
):
    if compact(required) not in walk_section + expr_section + shadow_section:
        raise SystemExit(f"NoBoundsChecks evidence flow lost a fail-closed guard: {required}")

var_decl_value = walk_section.find(compact("table <- nb_expr(value, darray_params, immutable_params, scan_index, scan_receiver, fn_name, line.line, table, shadowed_names)"))
var_decl_shadow = walk_section.find(compact("shadowed_names.push(name)"))
if var_decl_value < 0 or var_decl_shadow < var_decl_value:
    raise SystemExit("a local name must shadow a parameter only after its initializer is checked")

for variant in (
    "Expr.StaticEffectCall(", "Expr.Slice(", "Expr.Move(", "Expr.RegionNew(",
    "Expr.Catch(", "Expr.GetElse(", "Expr.Refinement(", "Expr.Lambda(", "Expr.Block(",
):
    if variant not in expr_section:
        raise SystemExit(f"NoBoundsChecks expression traversal omits {variant}")
if expr_section.count("Expr.GetElse(") != 1 or "Expr.Refinement(base,condition,refinement_line)|Expr.GetElse(" in expr_section:
    raise SystemExit("NoBoundsChecks must traverse GetElse recovery statements with their AST statement type")

if 'include "../../src/semantic/nobounds_index_policy.elisa"' not in positive_text or \
        'include "../../src/semantic/nobounds_index_policy.elisa"' not in negative_text:
    raise SystemExit("both proof fixtures must import the exact production policy")

positive_bodies = {
    "range_evidence_decision_matches_its_spec": """
        ensure result == true
        can Abort.Panic:
            return SemanticNoBoundsIndexPolicy::matching_range_evidence(is_darray_parameter, receiver, index_name, evidence_receiver, evidence_index) == SemanticNoBoundsIndexPolicy::matching_range_evidence_spec(is_darray_parameter, receiver, index_name, evidence_receiver, evidence_index)
    """,
    "report_decision_matches_its_spec": """
        ensure result == true
        return SemanticNoBoundsIndexPolicy::should_report_unproven(is_darray_parameter, has_evidence) == SemanticNoBoundsIndexPolicy::should_report_unproven_spec(is_darray_parameter, has_evidence)
    """,
    "exact_read_only_range_evidence_accepts_index": """
        ensure result == true
        can Abort.Panic:
            return SemanticNoBoundsIndexPolicy::matching_range_evidence(true, "items", "i", "items", "i")
    """,
    "different_receiver_does_not_match_range_evidence": """
        ensure result == true
        can Abort.Panic:
            return not SemanticNoBoundsIndexPolicy::matching_range_evidence(true, "other", "i", "items", "i")
    """,
    "different_index_does_not_match_range_evidence": """
        ensure result == true
        can Abort.Panic:
            return not SemanticNoBoundsIndexPolicy::matching_range_evidence(true, "items", "j", "items", "i")
    """,
    "non_parameter_does_not_match_range_evidence": """
        ensure result == true
        can Abort.Panic:
            return not SemanticNoBoundsIndexPolicy::matching_range_evidence(false, "items", "i", "items", "i")
    """,
    "unproven_parameter_index_is_reported": """
        ensure result == true
        return SemanticNoBoundsIndexPolicy::should_report_unproven(true, false)
    """,
    "proven_parameter_index_is_not_reported": """
        ensure result == true
        return not SemanticNoBoundsIndexPolicy::should_report_unproven(true, true)
    """,
    "non_parameter_index_is_not_reported": """
        ensure result == true
        return not SemanticNoBoundsIndexPolicy::should_report_unproven(false, false)
    """,
}
negative_bodies = {
    "wrong_receiver_is_accepted_as_evidence": """
        ensure result == true
        can Abort.Panic:
            return SemanticNoBoundsIndexPolicy::matching_range_evidence(true, "other", "i", "items", "i")
    """,
    "wrong_index_is_accepted_as_evidence": """
        ensure result == true
        can Abort.Panic:
            return SemanticNoBoundsIndexPolicy::matching_range_evidence(true, "items", "j", "items", "i")
    """,
    "arbitrary_loop_permission_suppresses_diagnostic": """
        ensure result == true
        return not SemanticNoBoundsIndexPolicy::should_report_unproven(true, false)
    """,
    "unproven_parameter_index_is_silently_accepted": """
        ensure result == true
        return not SemanticNoBoundsIndexPolicy::should_report_unproven(true, false)
    """,
}


def check_claims(source: str, expected: dict[str, str], label: str) -> None:
    names = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", source))
    if names != set(expected):
        raise SystemExit(f"{label} proof theorem inventory changed")
    for name, body in expected.items():
        section = function_section(source, name)
        has_handler = "can Abort.Panic:" in body
        if section.count("can Abort.Panic:") != (1 if has_handler else 0):
            raise SystemExit(f"{label} proof effect handler changed: {name}")
        if proof_body(source, name) != compact(body).replace("canAbort.Panic:", ""):
            raise SystemExit(f"{label} proof body changed: {name}")


check_claims(positive_text, positive_bodies, "positive")
check_claims(negative_text, negative_bodies, "negative")

if ARGS.source_only:
    print(json.dumps({
        "source_bound": True,
        "positive_theorems": len(positive_bodies),
        "false_controls": len(negative_bodies),
        "proof_closure_files": len(source_include_closure([POSITIVE, NEGATIVE, CHECKER])),
    }, sort_keys=True))
    raise SystemExit(0)

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("NoBoundsChecks policy proof requires a strict proof build")

compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if manifest.get("compiler", {}).get("source", {}).get("revision") != compiler_head:
    raise SystemExit("proof product compiler pin is stale; source-only gate passed but replay is unavailable")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, CHECKER])
inputs = list(dict.fromkeys([
    BIN, MANIFEST, PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SEMANTIC, *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == len(positive_bodies)
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "NoBoundsChecks proof report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == set(negative_bodies)
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest
print(json.dumps({
    "admitted": True,
    "positive_theorems": len(positive_bodies),
    "false_controls": len(negative_bodies),
    "proof_closure_files": len(source_closure),
    "product_compile_mode": manifest["compile_mode"],
    "compiler_revision": compiler_head,
}, sort_keys=True))
