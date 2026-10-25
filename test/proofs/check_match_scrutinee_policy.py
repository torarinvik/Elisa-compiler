"""Bind the match-scrutinee type proof to semantic rejection and pipeline admission."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/semantic/match_scrutinee_policy.elisa"
CONSUMER = ROOT / "src/semantic/check_void_match_scrutinee.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
SEMANTIC_API = ROOT / "src/semantic/semantic_api.elisa"
SEMANTIC_LATE_CHECKS = ROOT / "src/semantic/semantic_late_checks.elisa"
SEMANTIC_PIPELINE = ROOT / "src/semantic/semantic_api/full_pipeline.elisa"
SEMANTIC_DIAGNOSTICS = ROOT / "src/semantic/semantic_api/diagnostic_output.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
DRIVER_PROBES = ROOT / "src/driver/elisac_source_probes.elisa"
INCREMENTAL_GATE = ROOT / "src/driver/elisac_incremental_cache.elisa"
POSITIVE = HERE / "match_scrutinee_policy.elisa"
NEGATIVE = HERE / "match_scrutinee_policy_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking the proof product")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    generic_suffix = r"(?:\[[^\]\n]*\])?"
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}{generic_suffix}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(
        rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*{generic_suffix}\(",
        source[match.end():],
    )
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


def require_fragments(source: str, fragments: tuple[str, ...], message: str) -> None:
    if any(fragment not in source for fragment in fragments):
        raise SystemExit(message)


policy_text = POLICY.read_text()
consumer_text = CONSUMER.read_text()
semantic_text = SEMANTIC.read_text()
semantic_api_text = SEMANTIC_API.read_text()
semantic_late_checks_text = SEMANTIC_LATE_CHECKS.read_text()
semantic_pipeline_text = SEMANTIC_PIPELINE.read_text()
semantic_diagnostics_text = SEMANTIC_DIAGNOSTICS.read_text()
driver_text = DRIVER.read_text()
driver_probes_text = DRIVER_PROBES.read_text()
incremental_gate_text = INCREMENTAL_GATE.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_policy = '''
def kind_is_unmatchable(kind: Semantic::SemTypeKind) -> bool:
    ensure result == (kind == Semantic::SemTypeKind.Float or kind == Semantic::SemTypeKind.Bool)
    return match kind:
        Semantic::SemTypeKind.Float | Semantic::SemTypeKind.Bool: true
        _: false
'''
if "moduleSemanticMatchScrutineePolicy:" not in compact(policy_text):
    raise SystemExit("match-scrutinee policy module is missing")
if compact(function_section(policy_text, "kind_is_unmatchable")) != compact(expected_policy):
    raise SystemExit("unmatchable match-kind classifier changed without updating its proof")

if consumer_text.count('include "./match_scrutinee_policy.elisa"') != 1:
    raise SystemExit("match-scrutinee checker must include its proved policy exactly once")
if semantic_text.count('include "./semantic_types.elisa"') != 1 or \
        semantic_text.count('include "./check_void_match_scrutinee.elisa"') != 1 or \
        semantic_text.count('include "./semantic_late_checks.elisa"') != 1:
    raise SystemExit("semantic types, match checker, and late pipeline must each be included exactly once")
if semantic_late_checks_text.count('include "./semantic_api.elisa"') != 1 or \
        semantic_late_checks_text.count('include "./semantic_api/full_pipeline.elisa"') != 1 or \
        semantic_late_checks_text.count('include "./semantic_api/diagnostic_output.elisa"') != 1:
    raise SystemExit("semantic API, full pipeline, and diagnostic output must each be included exactly once")
if not (semantic_text.index('include "./semantic_types.elisa"') <
        semantic_text.index('include "./check_void_match_scrutinee.elisa"') <
        semantic_text.index('include "./semantic_late_checks.elisa"')) or \
        not (semantic_late_checks_text.index('include "./semantic_api.elisa"') <
             semantic_late_checks_text.index('include "./semantic_api/full_pipeline.elisa"')):
    raise SystemExit("match policy must follow semantic types and precede its public pipeline")

if compact(function_section(consumer_text, "match_scrutinee_is_unmatchable")) != compact('''
def match_scrutinee_is_unmatchable(scrutinee_type: InferType) -> bool:
    can Abort.Panic:
        return SemanticMatchScrutineePolicy::kind_is_unmatchable(scrutinee_type.kind)
'''):
    raise SystemExit("semantic match guard no longer delegates to the proved type-kind policy")

expression_walk = compact(function_section(consumer_text, "walk_expression_for_void_match_scrutinee"))
require_fragments(expression_walk, (
    'Expr.Match(scrutinee,arms,line)',
    'match_judged_type:InferType=infer_expression_type(match_scrutinee_without_store(scrutinee),var_types,type_names,table)',
    'kind:DiagnosticKind.MatchScrutineeNotMatchable',
    'notmatch_arms_have_error_pattern(arms)andmatch_scrutinee_is_unmatchable(match_judged_type)',
    'table<-walk_expression_for_void_match_scrutinee(scrutinee,table,var_types,type_names)',
    'table<-walk_statements_for_void_match_scrutinee(arm.body,table,var_types,type_names)',
), "expression match path no longer applies the proved guard to the unwrapped scrutinee")

statement_walk = compact(function_section(consumer_text, "walk_statements_for_void_match_scrutinee"))
require_fragments(statement_walk, (
    'Stmt.Match(scrutinee,arms,line)',
    'stmt_judged_type:InferType=infer_expression_type(match_scrutinee_without_store(scrutinee),var_types,type_names,table)',
    'kind:DiagnosticKind.MatchScrutineeNotMatchable',
    'notmatch_arms_have_error_pattern(arms)andmatch_scrutinee_is_unmatchable(stmt_judged_type)',
    'table<-walk_expression_for_void_match_scrutinee(scrutinee,table,var_types,type_names)',
    'table<-walk_expression_for_void_match_scrutinee(arm.guard,table,var_types,type_names)',
    'table<-walk_statements_for_void_match_scrutinee(arm.body,table,var_types,type_names)',
), "statement match path no longer applies the proved guard and recursively checks its arms")
if "match_scrutinee_type.kind==SemTypeKind.Float" in expression_walk or \
        "match_scrutinee_type.kind==SemTypeKind.Bool" in expression_walk or \
        "stmt_judged_type.kind==SemTypeKind.Float" in statement_walk or \
        "stmt_judged_type.kind==SemTypeKind.Bool" in statement_walk:
    raise SystemExit("match diagnostic sites bypass the proved type-kind policy")

declaration_walk = compact(function_section(consumer_text, "check_void_match_scrutinee_declarations"))
require_fragments(declaration_walk, (
    'Decl.Func(name,params,return_type,body,effects,decorators,line)',
    'table<-walk_statements_for_void_match_scrutinee(body,table,var_types,type_names)',
    'Decl.Module(module_name,body,line):table<-check_void_match_scrutinee_declarations(body,table)',
    'Decl.Scoped(body,line):table<-check_void_match_scrutinee_declarations(body,table)',
), "match-scrutinee traversal no longer reaches function and nested declarations")
entry = compact(function_section(consumer_text, "check_void_match_scrutinee"))
if "table<-check_void_match_scrutinee_declarations(declarations,table)" not in entry:
    raise SystemExit("public match-scrutinee checker no longer enters its declaration traversal")

pipeline = compact(function_section(semantic_pipeline_text, "check_full_into_pipeline"))
if pipeline.count("check_void_match_scrutinee(loop_view.top_decls,table)") != 1 or \
        pipeline.count('PhaseTimer::minor("sem:check_void_match_scrutinee")') != 1:
    raise SystemExit("public semantic pipeline no longer runs the match-scrutinee checker exactly once")

diagnostics_wrapper = compact(function_section(semantic_diagnostics_text,
                                                "check_full_diagnostics_with_incremental_snapshot"))
diagnostics_api = compact(function_section(semantic_diagnostics_text,
                                            "check_full_diagnostics_with_incremental_snapshot_and_lookup_context"))
if "check_full_diagnostics_with_incremental_snapshot_and_lookup_context[" not in diagnostics_wrapper or \
        "check_full_into_with_incremental_snapshot_and_lookup_context[" not in diagnostics_api:
    raise SystemExit("driver-facing semantic diagnostics no longer enter the full semantic pipeline")
driver_probe_gate = compact(function_section(driver_probes_text, "run_semantic_gate_with_snapshot"))
require_fragments(driver_probe_gate, (
    "Semantic::check_full_diagnostics_with_incremental_snapshot[",
    "report_semantic_gate_diagnostics[semantic_gate]",
    "returnsemantic_errors",
), "driver semantic gate no longer counts emitted semantic errors from the full checker")
diagnostic_reporter = compact(function_section(driver_probes_text, "report_semantic_gate_diagnostics"))
require_fragments(diagnostic_reporter, (
    "ifseverity==1:",
    "semantic_errors<-semantic_errors+1",
    "report_diagnostic(diagnostic)",
), "driver diagnostics no longer increment the semantic error count for error-severity rows")
incremental_gate = compact(function_section(incremental_gate_text, "run_semantic_gate_incremental"))
require_fragments(incremental_gate, (
    "returnrun_semantic_gate_incremental_with_session[",
), "incremental semantic gate no longer enters its session-aware checker")
incremental_session_gate = compact(function_section(
    incremental_gate_text, "run_semantic_gate_incremental_with_session"))
require_fragments(incremental_session_gate, (
    "semantic_errors:mutablei64=0",
    "semantic_errors<-run_semantic_gate_with_lookup_context[",
    "returnsemantic_errors",
), "incremental semantic gate no longer returns the checked diagnostic count")

driver_main = compact(function_section(driver_text, "main"))
if "returnrun_compile_request_with_session(" not in driver_main:
    raise SystemExit("driver main no longer delegates source compilation to the gated request path")
driver = compact(function_section(driver_text, "run_compile_request_with_session"))
driver_order = (
    "expanded_semantic_errors:mutablei64=0",
    "expanded_semantic_errors<-run_semantic_gate_incremental_with_session[",
    "return1ifexpanded_semantic_errors>0",
    "semantic_gate_already_run<-true",
    "pymodule_semantic_errors:mutablei64=0",
    "pymodule_semantic_errors<-run_semantic_gate_incremental_with_session[",
    "return1ifpymodule_semantic_errors>0",
    "semantic_gate_already_run<-true",
    "ifnotsemantic_gate_already_run:semantic_errors:mutablei64=0",
    "semantic_errors<-run_semantic_gate_incremental_with_session[",
    "return1ifsemantic_errors>0",
    "returnrun_llvm_compile_request_with_cleanup(",
)
driver_positions: list[int] = []
driver_cursor = 0
for fragment in driver_order:
    position = driver.find(fragment, driver_cursor)
    if position < 0:
        raise SystemExit("compiler driver no longer requires a clean semantic gate before backend emission")
    driver_positions.append(position)
    driver_cursor = position + len(fragment)
if driver_positions != sorted(driver_positions):
    raise SystemExit("backend emission moved before the error-rejecting semantic gate")

if 'include "../../src/semantic/semantic_types.elisa"' not in positive_text or \
        'include "../../src/semantic/match_scrutinee_policy.elisa"' not in positive_text or \
        'include "./match_scrutinee_policy.elisa"' not in negative_text:
    raise SystemExit("match-scrutinee fixtures must import the production type and policy")
positive_names = {
    "unmatchable_kind_classifier_is_exact",
    "float_and_bool_kinds_are_unmatchable",
    "integer_string_char_and_named_kinds_are_not_in_this_classifier",
    "void_stays_with_its_separate_scrutinee_diagnostic",
}
negative_names = {
    "false_claim_float_scrutinee_is_matchable",
    "false_claim_bool_scrutinee_is_matchable",
    "false_claim_integer_scrutinee_is_unmatchable",
}
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("match-scrutinee proof declaration inventory changed")

positive_claims = {
    "unmatchable_kind_classifier_is_exact": 'SemanticMatchScrutineePolicy::kind_is_unmatchable(kind)==(kind==Semantic::SemTypeKind.Floatorkind==Semantic::SemTypeKind.Bool)',
    "float_and_bool_kinds_are_unmatchable": 'SemanticMatchScrutineePolicy::kind_is_unmatchable(Semantic::SemTypeKind.Float)andSemanticMatchScrutineePolicy::kind_is_unmatchable(Semantic::SemTypeKind.Bool)',
    "integer_string_char_and_named_kinds_are_not_in_this_classifier": 'notSemanticMatchScrutineePolicy::kind_is_unmatchable(Semantic::SemTypeKind.Int)andnotSemanticMatchScrutineePolicy::kind_is_unmatchable(Semantic::SemTypeKind.String)andnotSemanticMatchScrutineePolicy::kind_is_unmatchable(Semantic::SemTypeKind.Char)andnotSemanticMatchScrutineePolicy::kind_is_unmatchable(Semantic::SemTypeKind.Named)',
    "void_stays_with_its_separate_scrutinee_diagnostic": 'notSemanticMatchScrutineePolicy::kind_is_unmatchable(Semantic::SemTypeKind.Void)',
}
for name, claim in positive_claims.items():
    section = compact(function_section(positive_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"positive proof {name} no longer establishes its source-bound claim")
negative_claims = {
    "false_claim_float_scrutinee_is_matchable": 'notSemanticMatchScrutineePolicy::kind_is_unmatchable(Semantic::SemTypeKind.Float)',
    "false_claim_bool_scrutinee_is_matchable": 'notSemanticMatchScrutineePolicy::kind_is_unmatchable(Semantic::SemTypeKind.Bool)',
    "false_claim_integer_scrutinee_is_unmatchable": 'SemanticMatchScrutineePolicy::kind_is_unmatchable(Semantic::SemTypeKind.Int)',
}
for name, claim in negative_claims.items():
    section = compact(function_section(negative_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"false-claim control {name} no longer asserts the rejected claim")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive": len(positive_names),
                      "false_claim_controls": len(negative_names)}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("match-scrutinee policy proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POLICY, CONSUMER,
    SEMANTIC, SEMANTIC_API, SEMANTIC_LATE_CHECKS, SEMANTIC_PIPELINE,
    SEMANTIC_DIAGNOSTICS, DRIVER, DRIVER_PROBES, INCREMENTAL_GATE,
    POSITIVE, NEGATIVE, *source_closure,
]))
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
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "match-scrutinee policy proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_after == hashes_before, "match-scrutinee proof inputs changed during admission"
