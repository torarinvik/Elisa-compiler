"""Bind the iterator-alias proof to the production resolver and invalidation pass."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


argument_parser = argparse.ArgumentParser()
argument_parser.add_argument("--source-only", action="store_true",
                             help="check production and proof bindings without running Elisa-Proof")
ARGS = argument_parser.parse_args()
from source_guard_compat import expand_return_if_blocks
ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
MODULE = ROOT / "src/semantic/iterator_alias_resolution.elisa"
POLICY = ROOT / "src/semantic/iterator_mutation_policy.elisa"
CHECKER = ROOT / "src/semantic/check_mutate_while_iterating.elisa"
CALL_LOWERING = ROOT / "src/backend/codegen_stmt_expr_calls.elisa"
SEMANTIC_ROOT = ROOT / "src/semantic/semantic.elisa"
SEMANTIC_API = ROOT / "src/semantic/semantic_api.elisa"
POSITIVE = HERE / "semantic_iterator_alias_invalidation.elisa"
NEGATIVE = HERE / "semantic_iterator_alias_invalidation_rejected.elisa"

POSITIVE_SHAPES = {
    "production_mutation_policy_matches_its_spec": """def production_mutation_policy_matches_its_spec(method: sview) -> bool:
    ensure result == true
    return SemanticIteratorMutationPolicy::forbidden_during_iteration(method) == SemanticIteratorMutationPolicy::forbidden_during_iteration_spec(method)
""",
    "resize_is_forbidden_during_iteration": """def resize_is_forbidden_during_iteration() -> bool:
    ensure result == true
    return SemanticIteratorMutationPolicy::forbidden_during_iteration("resize")
""",
    "production_resolver_refines_its_recursive_spec": """def production_resolver_refines_its_recursive_spec(alias_names: darray[sview]&, alias_targets: darray[sview]&, name: sview) -> bool:
    ensure result == true
    return SemanticIteratorAliasResolution::resolve(alias_names, alias_targets, name) == SemanticIteratorAliasResolution::resolve_from(alias_names, alias_targets, name, alias_names.count)
""",
    "direct_alias_resolves_to_the_iterated_source": """def direct_alias_resolves_to_the_iterated_source() -> bool:
    ensure result == true
    alias_names: darray[sview] = ["alias"]
    alias_targets: darray[sview] = ["xs"]
    return SemanticIteratorAliasResolution::resolve(alias_names, alias_targets, "alias") == "xs"
""",
    "two_alias_hops_resolve_to_the_iterated_source": """def two_alias_hops_resolve_to_the_iterated_source() -> bool:
    ensure result == true
    alias_names: darray[sview] = ["alias2", "alias"]
    alias_targets: darray[sview] = ["alias1", "xs"]
    return SemanticIteratorAliasResolution::resolve(alias_names, alias_targets, "alias2") == "xs"
""",
    "unrelated_alias_resolves_to_its_own_target": """def unrelated_alias_resolves_to_its_own_target() -> bool:
    ensure result == true
    alias_names: darray[sview] = ["other_alias"]
    alias_targets: darray[sview] = ["ys"]
    return SemanticIteratorAliasResolution::resolve(alias_names, alias_targets, "other_alias") == "ys"
""",
    "a_name_without_an_alias_resolves_to_itself": """def a_name_without_an_alias_resolves_to_itself() -> bool:
    ensure result == true
    alias_names: darray[sview] = ["other_alias"]
    alias_targets: darray[sview] = ["ys"]
    return SemanticIteratorAliasResolution::resolve(alias_names, alias_targets, "xs") == "xs"
""",
    "a_self_alias_cycle_fails_closed": """def a_self_alias_cycle_fails_closed() -> bool:
    ensure result == true
    alias_names: darray[sview] = ["alias"]
    alias_targets: darray[sview] = ["alias"]
    return SemanticIteratorAliasResolution::resolve(alias_names, alias_targets, "alias") == ""
""",
    "a_two_name_alias_cycle_fails_closed": """def a_two_name_alias_cycle_fails_closed() -> bool:
    ensure result == true
    alias_names: darray[sview] = ["alias", "other_alias"]
    alias_targets: darray[sview] = ["other_alias", "alias"]
    return SemanticIteratorAliasResolution::resolve(alias_names, alias_targets, "alias") == ""
""",
    "an_unresolved_alias_cycle_is_a_possible_iterator_source": """def an_unresolved_alias_cycle_is_a_possible_iterator_source() -> bool:
    ensure result == true
    alias_names: darray[sview] = ["alias", "other_alias"]
    alias_targets: darray[sview] = ["other_alias", "alias"]
    resolved: sview = SemanticIteratorAliasResolution::resolve(alias_names, alias_targets, "alias")
    return SemanticIteratorAliasResolution::may_name(resolved, "xs")
""",
    "multiple_targets_for_one_alias_resolve_to_unknown": """def multiple_targets_for_one_alias_resolve_to_unknown() -> bool:
    ensure result == true
    alias_names: darray[sview] = ["alias", "alias"]
    alias_targets: darray[sview] = ["ys", "xs"]
    return SemanticIteratorAliasResolution::resolve(alias_names, alias_targets, "alias") == ""
""",
    "an_ambiguous_alias_is_a_possible_iterator_source": """def an_ambiguous_alias_is_a_possible_iterator_source() -> bool:
    ensure result == true
    alias_names: darray[sview] = ["alias", "alias"]
    alias_targets: darray[sview] = ["ys", "xs"]
    resolved: sview = SemanticIteratorAliasResolution::resolve(alias_names, alias_targets, "alias")
    return SemanticIteratorAliasResolution::may_name(resolved, "xs")
""",
}
NEGATIVE_SHAPES = {
    "resize_is_allowed_during_iteration": """def resize_is_allowed_during_iteration() -> bool:
    ensure result == true
    return not SemanticIteratorMutationPolicy::forbidden_during_iteration("resize")
""",
    "a_relocating_method_on_a_direct_alias_is_safe_during_the_source_walk": """def a_relocating_method_on_a_direct_alias_is_safe_during_the_source_walk() -> bool:
    ensure result == true
    alias_names: darray[sview] = ["alias"]
    alias_targets: darray[sview] = ["xs"]
    return SemanticIteratorAliasResolution::resolve(alias_names, alias_targets, "alias") != "xs"
""",
    "an_unresolved_alias_cycle_cannot_name_the_iterated_source": """def an_unresolved_alias_cycle_cannot_name_the_iterated_source() -> bool:
    ensure result == true
    alias_names: darray[sview] = ["alias", "other_alias"]
    alias_targets: darray[sview] = ["other_alias", "alias"]
    resolved: sview = SemanticIteratorAliasResolution::resolve(alias_names, alias_targets, "alias")
    return not SemanticIteratorAliasResolution::may_name(resolved, "xs")
""",
    "an_ambiguous_alias_cannot_name_the_iterated_source": """def an_ambiguous_alias_cannot_name_the_iterated_source() -> bool:
    ensure result == true
    alias_names: darray[sview] = ["alias", "alias"]
    alias_targets: darray[sview] = ["ys", "xs"]
    resolved: sview = SemanticIteratorAliasResolution::resolve(alias_names, alias_targets, "alias")
    return not SemanticIteratorAliasResolution::may_name(resolved, "xs")
""",
}


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in expand_return_if_blocks(source).splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost )?def {re.escape(name)}(?:\[[^\n]*?\])?\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost )?def [A-Za-z_][A-Za-z0-9_]*(?:\[[^\n]*?\])?\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*(?:ghost )?def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


for path, shapes in ((POSITIVE, POSITIVE_SHAPES), (NEGATIVE, NEGATIVE_SHAPES)):
    if declarations(path) != set(shapes):
        raise SystemExit(f"iterator-alias theorem inventory changed in {path.name}")
    source = path.read_text()
    for name, expected in shapes.items():
        if compact(function_section(source, name)) != compact(expected):
            raise SystemExit(f"iterator-alias theorem changed its exact claim: {name}")

if 'include "../../src/semantic/iterator_alias_resolution.elisa"' not in POSITIVE.read_text():
    raise SystemExit("iterator-alias proof no longer imports the production resolver")
if 'include "../../src/semantic/iterator_mutation_policy.elisa"' not in POSITIVE.read_text():
    raise SystemExit("iterator-alias proof no longer imports the production mutation policy")
if 'include "./semantic_iterator_alias_invalidation.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("iterator-alias false control no longer inherits the positive claims")

module_text = MODULE.read_text()
expected_module = {
    "direct_target_found_from": """ghost def direct_target_found_from(alias_names: darray[sview]&, alias_targets: darray[sview]&, name: sview, index: usize) -> bool:
    requires index <= alias_names.count
    decreases alias_names.count - index
    return false if index == alias_names.count
    return true if index < alias_targets.count and alias_names[index] == name
    return direct_target_found_from(alias_names, alias_targets, name, index + 1)
""",
    "direct_target_value_from": """ghost def direct_target_value_from(alias_names: darray[sview]&, alias_targets: darray[sview]&, name: sview, index: usize) -> sview:
    requires index <= alias_names.count
    decreases alias_names.count - index
    return "" if index == alias_names.count
    return alias_targets[index] if index < alias_targets.count and alias_names[index] == name
    return direct_target_value_from(alias_names, alias_targets, name, index + 1)
""",
    "direct_target_from": """def direct_target_from(alias_names: darray[sview]&, alias_targets: darray[sview]&, name: sview, index: usize) -> (found: bool, target: sview):
    requires index <= alias_names.count
    decreases alias_names.count - index
    ensure result.found == direct_target_found_from(alias_names, alias_targets, name, index)
    ensure result.found implies result.target == direct_target_value_from(alias_names, alias_targets, name, index)
    return (false, sview("", 0, 0)) if index == alias_names.count
    return (true, alias_targets[index]) if index < alias_targets.count and alias_names[index] == name
    return direct_target_from(alias_names, alias_targets, name, index + 1)
""",
    "direct_target": """def direct_target(alias_names: darray[sview]&, alias_targets: darray[sview]&, name: sview) -> (found: bool, target: sview):
    ensure result.found == direct_target_found_from(alias_names, alias_targets, name, 0)
    ensure result.found implies result.target == direct_target_value_from(alias_names, alias_targets, name, 0)
    return direct_target_from(alias_names, alias_targets, name, 0)
""",
    "ambiguous_from": """ghost def ambiguous_from(alias_names: darray[sview]&, name: sview, index: usize, seen: bool) -> bool:
    requires index <= alias_names.count
    decreases alias_names.count - index
    return false if index == alias_names.count
    return true if alias_names[index] == name and seen
    next_seen: bool = seen or alias_names[index] == name
    return ambiguous_from(alias_names, name, index + 1, next_seen)
""",
    "ambiguous_from_runtime": """def ambiguous_from_runtime(alias_names: darray[sview]&, name: sview, index: usize, seen: bool) -> bool:
    requires index <= alias_names.count
    decreases alias_names.count - index
    ensure result == ambiguous_from(alias_names, name, index, seen)
    return false if index == alias_names.count
    return true if alias_names[index] == name and seen
    next_seen: bool = seen or alias_names[index] == name
    return ambiguous_from_runtime(alias_names, name, index + 1, next_seen)
""",
    "ambiguous": """def ambiguous(alias_names: darray[sview]&, name: sview) -> bool:
    ensure result == ambiguous_from(alias_names, name, 0, false)
    return ambiguous_from_runtime(alias_names, name, 0, false)
""",
    "resolve_from": """ghost def resolve_from(alias_names: darray[sview]&, alias_targets: darray[sview]&, name: sview, remaining: usize) -> sview:
    requires remaining <= alias_names.count
    decreases remaining
    return "" if ambiguous_from(alias_names, name, 0, false)
    return name if not direct_target_found_from(alias_names, alias_targets, name, 0)
    return "" if direct_target_value_from(alias_names, alias_targets, name, 0) == name
    return "" if remaining == 0
    return resolve_from(alias_names, alias_targets, direct_target_value_from(alias_names, alias_targets, name, 0), remaining - 1)
""",
    "resolve_runtime_from": """def resolve_runtime_from(alias_names: darray[sview]&, alias_targets: darray[sview]&, name: sview, remaining: usize) -> sview:
    requires remaining <= alias_names.count
    decreases remaining
    ensure result == resolve_from(alias_names, alias_targets, name, remaining)
    return sview("", 0, 0) if ambiguous(alias_names, name)
    target: (found: bool, target: sview) = direct_target(alias_names, alias_targets, name)
    return name if not target.found
    return sview("", 0, 0) if target.target == name
    return sview("", 0, 0) if remaining == 0
    return resolve_runtime_from(alias_names, alias_targets, target.target, remaining - 1)
""",
    "resolve": """def resolve(alias_names: darray[sview]&, alias_targets: darray[sview]&, name: sview) -> sview:
    ensure result == resolve_from(alias_names, alias_targets, name, alias_names.count)
    return resolve_runtime_from(alias_names, alias_targets, name, alias_names.count)
""",
    "may_name": """def may_name(resolved: sview, source: sview) -> bool:
    ensure result == (resolved == "" or resolved == source)
    return resolved == "" or resolved == source
""",
}
for name, expected in expected_module.items():
    if compact(function_section(module_text, name)) != compact(expected):
        raise SystemExit(f"production alias resolver no longer matches its proved model: {name}")

checker_text = CHECKER.read_text()
checker_compact = compact(checker_text)
if checker_text.count('include "./iterator_alias_resolution.elisa"') != 1:
    raise SystemExit("iterator invalidation must include the proof-refined alias resolver exactly once")
if checker_text.count('include "./iterator_mutation_policy.elisa"') != 1:
    raise SystemExit("iterator invalidation must include the proof-refined mutation policy exactly once")
policy_text = POLICY.read_text()
policy_compact = compact(policy_text)
if compact('ghost def forbidden_during_iteration_spec(method: sview) -> bool: return method == "push" or method == "extend" or method == "insert" or method == "append" or method == "reserve" or method == "clear" or method == "truncate" or method == "resize"') not in policy_compact:
    raise SystemExit("iterator mutation specification lost a classified method")
if compact('def forbidden_during_iteration(method: sview) -> bool: ensure result == forbidden_during_iteration_spec(method) return method == "push" or method == "extend" or method == "insert" or method == "append" or method == "reserve" or method == "clear" or method == "truncate" or method == "resize"') not in policy_compact:
    raise SystemExit("production iterator mutation classifier no longer refines its independent specification")
if declarations(POSITIVE) != set(POSITIVE_SHAPES):
    raise SystemExit("iterator mutation theorem inventory changed")
if declarations(NEGATIVE) != set(NEGATIVE_SHAPES):
    raise SystemExit("iterator mutation false-control inventory changed")
mutation = compact(function_section(checker_text, "iter_direct_mutation_method"))
for fragment in (
    "alias_names:darray[sview]&",
    "alias_targets:darray[sview]&",
    "forbidden:bool=SemanticIteratorMutationPolicy::forbidden_during_iteration(method_name)",
    "receiver_name:sview=ident_name_of(receiver)",
    "ifreceiver_name!=\"\":resolved_receiver:sview=SemanticIteratorAliasResolution::resolve(alias_names,alias_targets,receiver_name)receiver_is_place<-SemanticIteratorAliasResolution::may_name(resolved_receiver,container)",
    "method_namereturnifforbiddenandreceiver_is_place",
):
    if fragment not in mutation:
        raise SystemExit(f"production iterator check lost the proved alias-mutator path: {fragment}")

resize_lowering = compact(function_section(CALL_LOWERING.read_text(), "emit_statement_expr_calls"))
resize_start = resize_lowering.find('push_method=="resize"')
resize_end = resize_lowering.find('push_method=="extend"', resize_start)
resize_arm = resize_lowering[resize_start:resize_end] if resize_start >= 0 and resize_end > resize_start else ""
if not all(fragment in resize_arm for fragment in (
        "rz_more:LLVMValueRef=LLVMBuildICmp(builder,36,rz_cur,rz_n,\"resize.more\")",
        "LLVMBuildCondBr(builder,rz_more,rz_push_block,rz_after)",
        "emit_darray_push(rz_slot",
        "LLVMBuildBr(builder,rz_cond)",
)):
    raise SystemExit("DArray resize no longer grows by the push path covered by iterator mutation policy")

if "SemanticIteratorAliasResolution::resolve(alias_names,alias_targets,raw)" not in compact(function_section(checker_text, "iter_arg_container_name")):
    raise SystemExit("mutable-reference call detection no longer uses the proved alias resolver")
unknown_alias = compact(function_section(checker_text, "iter_arg_has_unresolved_alias"))
if "resolved==\"\"andSemanticIteratorAliasResolution::direct_target(alias_names,alias_targets,raw).found" not in unknown_alias:
    raise SystemExit("mutable-reference call detection no longer treats alias cycles as unknown")
call_check = compact(function_section(checker_text, "iter_call_argument_hits_place"))
if "argument_root==containeroriter_arg_has_unresolved_alias(normalized,alias_names,alias_targets)" not in call_check:
    raise SystemExit("mutable-reference calls no longer fail closed for cyclic aliases")
direct_call_check = compact(function_section(checker_text, "iter_direct_call_passes_container_by_ref"))
recursive_call_check = compact(function_section(checker_text, "iter_call_passes_container_by_ref"))
if "iter_call_argument_hits_place(argument,place,container,alias_names,alias_targets)" not in direct_call_check or \
        "iter_direct_call_passes_container_by_ref(expression,place,container,alias_names,alias_targets,table)" not in recursive_call_check:
    raise SystemExit("mutable-reference alias checks no longer flow through the recursive expression walker")
alias_collection = compact(function_section(checker_text, "iter_collect_aliases"))
if "Stmt.Match(scrutinee,arms,match_line):forarminarms|names,targets|:iter_collect_aliases(arm.body,names,targets)" not in alias_collection:
    raise SystemExit("aliases inside match arms are no longer collected for invalidation checks")
if "Stmt.Assign(target,operator,value,line):alias_name:sview=ident_name_of(storage_view_strip_paren_move(target))iter_collect_alias_binding(alias_name,value,names,targets)ifoperator==TokenKind.Assignoroperator==TokenKind.LArrow" not in alias_collection:
    raise SystemExit("rebinding assignments are no longer included in the conservative alias set")
alias_binding = compact(function_section(checker_text, "iter_alias_value_target"))
if compact("Expr.Ident(_, _):ident_name_of(stripped)") not in alias_binding:
    raise SystemExit("bare reference-value copies are no longer included in the conservative alias set")
if 'include "./check_mutate_while_iterating.elisa"' not in SEMANTIC_ROOT.read_text():
    raise SystemExit("semantic root no longer includes the iterator invalidation pass")
if compact(SEMANTIC_API.read_text()).count("table<-check_mutate_while_iterating(loop_view,table)") != 1:
    raise SystemExit("semantic pipeline must execute iterator invalidation exactly once")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({
        "source_bound": True,
        "positive_theorems": len(POSITIVE_SHAPES),
        "false_controls": len(NEGATIVE_SHAPES),
        "proof_closure_files": len(source_closure),
    }, sort_keys=True))
    raise SystemExit(0)

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("iterator-alias proof requires a strict proof build")
stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
manifest = BIN.with_name(BIN.name + ".manifest.json")
inputs = list(dict.fromkeys([
    BIN, manifest, manifest.with_name(manifest.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", MODULE, CHECKER,
    SEMANTIC_ROOT, SEMANTIC_API, POSITIVE, NEGATIVE, *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert process.returncode == 0, report
    return process.returncode, report


positive_rc, positive_report = replay(POSITIVE)
negative_rc, negative_report = replay(NEGATIVE)
for path in inputs:
    if hashlib.sha256(path.read_bytes()).hexdigest() != hashes_before[str(path)]:
        raise SystemExit(f"proof replay modified an input artifact: {path}")
print(json.dumps({
    "source_bound": True,
    "positive_theorems": positive_report["summary"]["proved_theorems"],
    "false_controls": negative_report["summary"]["rejected_theorems"],
    "proof_closure_files": len(source_closure),
}, sort_keys=True))
