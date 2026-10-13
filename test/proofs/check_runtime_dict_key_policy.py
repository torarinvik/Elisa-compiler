"""Bind dictionary-key spelling proofs to semantic extraction and diagnostics."""
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
POLICY = ROOT / "src/semantic/runtime_dict_key_policy.elisa"
CONSUMER = ROOT / "src/semantic/check_runtime_dict_key.elisa"
RESOLVER = ROOT / "src/semantic/resolve_types_infer.elisa"
RESOLVER_OPERATORS = ROOT / "src/semantic/resolve_types_operators.elisa"
RESOLVER_INITIALIZERS = ROOT / "src/semantic/resolve_types_initializers.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
SEMANTIC_PASSES = ROOT / "src/semantic/semantic_parallel_passes.elisa"
POSITIVE = HERE / "runtime_dict_key_policy.elisa"
NEGATIVE = HERE / "runtime_dict_key_policy_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking the proof product")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


def require_fragments(source: str, fragments: tuple[str, ...], message: str) -> None:
    if any(fragment not in source for fragment in fragments):
        raise SystemExit(message)


policy_text = POLICY.read_text()
consumer_text = CONSUMER.read_text()
resolver_text = RESOLVER.read_text()
resolver_operators_text = RESOLVER_OPERATORS.read_text()
resolver_initializers_text = RESOLVER_INITIALIZERS.read_text()
semantic_text = SEMANTIC.read_text()
semantic_passes_text = SEMANTIC_PASSES.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_resolved_classifier = '''
def is_unhashable_resolved_key_spelling(key_spelling: sview) -> bool:
    ensure when key_spelling:
        "sview" | "dstr" | "f32" | "f64" -> result
        _ -> not result
    return match key_spelling:
        "sview" | "dstr" | "f32" | "f64": true
        _: false
'''
expected_declared_classifier = '''
def requires_declared_key_spelling_check(key_spelling: sview) -> bool:
    ensure when key_spelling:
        "sview" | "dstr" -> result
        _ -> not result
    return match key_spelling:
        "sview" | "dstr": true
        _: false
'''
expected_display = '''
def diagnostic_spelling(declared_spelling: sview) -> sview:
    ensure when declared_spelling:
        "dstr" -> result == "darray[u8]"
        _ -> result == declared_spelling
    return match declared_spelling:
        "dstr": "darray[u8]"
        _: declared_spelling
'''
if "moduleSemanticRuntimeDictKeyPolicy:" not in compact(policy_text):
    raise SystemExit("runtime dictionary-key policy module is missing")
if compact(function_section(policy_text, "is_unhashable_resolved_key_spelling")) != compact(expected_resolved_classifier):
    raise SystemExit("resolved unhashable-key classifier changed without updating its proof")
if compact(function_section(policy_text, "requires_declared_key_spelling_check")) != compact(expected_declared_classifier):
    raise SystemExit("normalized declared-key classifier changed without updating its proof")
if compact(function_section(policy_text, "diagnostic_spelling")) != compact(expected_display):
    raise SystemExit("dictionary-key diagnostic spelling changed without updating its proof")

if resolver_text.count('include "./runtime_dict_key_policy.elisa"') != 1:
    raise SystemExit("semantic type resolver must include the proved dictionary-key policy exactly once")
if 'include "./runtime_dict_key_policy.elisa"' in consumer_text:
    raise SystemExit("dictionary-key policy must be imported once through the semantic type resolver")
if semantic_text.count('include "./check_runtime_dict_key.elisa"') != 1:
    raise SystemExit("semantic root must include the dictionary-key checker exactly once")
if semantic_text.count('include "./resolve_types_infer.elisa"') != 1 or \
        semantic_text.index('include "./resolve_types_infer.elisa"') > semantic_text.index('include "./check_runtime_dict_key.elisa"'):
    raise SystemExit("dictionary-key policy must be loaded before both semantic consumers")
pass_dispatch = compact(function_section(semantic_passes_text, "par_pass_call"))
if "elifpass_id==95:table<-check_runtime_dict_key(loop_view.top_decls,table)" not in pass_dispatch:
    raise SystemExit("semantic pass dispatcher no longer invokes the dictionary-key checker")

if compact(function_section(resolver_text, "dict_key_type_unsupported")) != compact('''
def dict_key_type_unsupported(key_spelling: sview) -> bool:
    can Abort.Panic:
        return SemanticRuntimeDictKeyPolicy::is_unhashable_resolved_key_spelling(key_spelling)
'''):
    raise SystemExit("resolved dictionary-key validation no longer delegates to the proved four-spelling policy")
read_key_validation = compact(function_section(resolver_operators_text, "check_operator_operands_inner"))
if 'kind:DiagnosticKind.RuntimeDictKeyUnsupported' not in read_key_validation or \
        'ifdict_key_type_unsupported(read_key_spelling)' not in read_key_validation:
    raise SystemExit("resolved key policy no longer guards dictionary index-read diagnostics")
write_key_validation = compact(function_section(resolver_initializers_text, "check_variable_initializers"))
if 'kind:DiagnosticKind.RuntimeDictKeyUnsupported' not in write_key_validation or \
        'ifdict_key_type_unsupported(key_spelling)' not in write_key_validation:
    raise SystemExit("resolved key policy no longer guards dictionary index-target diagnostics")
if compact(function_section(consumer_text, "dict_key_spelling_unsupported")) != compact('''
def dict_key_spelling_unsupported(key_spelling: sview) -> bool:
    can Abort.Panic:
        return SemanticRuntimeDictKeyPolicy::requires_declared_key_spelling_check(key_spelling)
'''):
    raise SystemExit("normalized dictionary-key use filtering no longer delegates to the proved two-spelling policy")
if compact(function_section(consumer_text, "dict_reported_spelling")) != compact('''
def dict_reported_spelling(declared_spelling: sview) -> sview:
    can Abort.Panic:
        return SemanticRuntimeDictKeyPolicy::diagnostic_spelling(declared_spelling)
'''):
    raise SystemExit("dictionary-key diagnostics no longer delegate spelling conversion to the proved policy")

argument_extractor = compact(function_section(consumer_text, "dict_type_argument_at"))
require_fragments(argument_extractor, (
    'Expr.IndexN(head,arguments,index_n_line)',
    'sview("",0,0)returnifident_name_of(head)!="dict"orarguments.count<=position',
    'returnident_name_of(arguments[position])',
    'Expr.Unary(operator,operand,unary_line):returndict_type_argument_at(operand,position)',
    'Expr.Paren(inner,paren_line):returndict_type_argument_at(inner,position)',
), "proved key classifier is disconnected from dict type argument extraction")

index_report = compact(function_section(consumer_text, "dict_key_check_index_target"))
require_fragments(index_report, (
    'key_spelling:sview=parallel_lookup_first(names,keys,indexed_name)',
    'returnifindexed_name==""',
    'returnifkey_spelling==""',
    'kind:DiagnosticKind.RuntimeDictKeyUnsupported',
    'expected:dict_reported_spelling(key_spelling)',
    'actual:dict_reported_spelling(parallel_lookup_first(names,values,indexed_name))',
), "proved key and display policies no longer construct the runtime dictionary diagnostic")

expression_walk = compact(function_section(consumer_text, "dict_key_check_expression"))
require_fragments(expression_walk, (
    'Expr.Index(object,index,line):table<-dict_key_check_index_target(object,line.line,names,keys,values,table)',
    'table<-dict_key_check_expression(object,names,keys,values,table)',
    'table<-dict_key_check_expression(index,names,keys,values,table)',
    'Expr.Binary(left,operator,right,line)',
    'Expr.Unary(operator,operand,unary_line):table<-dict_key_check_expression(operand,names,keys,values,table)',
    'Expr.Paren(inner,paren_line):table<-dict_key_check_expression(inner,names,keys,values,table)',
), "dictionary-key proof is disconnected from expression indexing and recursive operands")

statement_walk = compact(function_section(consumer_text, "dict_key_check_statements"))
require_fragments(statement_walk, (
    'Stmt.Expr(expression,line):table<-dict_key_check_expression(expression,names,keys,values,table)',
    'Stmt.VarDecl(name,type_expression,value,line):table<-dict_key_check_expression(value,names,keys,values,table)',
    'Stmt.Assign(target,operator,value,line)',
    'Expr.Index(assign_object,assign_index,assign_line)',
    'table<-dict_key_check_index_target(assign_object,line.line,names,keys,values,table)',
    'table<-dict_key_check_expression(assign_index,names,keys,values,table)',
    'table<-dict_key_check_expression(value,names,keys,values,table)',
    'Stmt.If(condition,then_body,else_body,line)',
    'Stmt.While(condition,body,line)',
    'Stmt.For(bind,variables,iterable,body,line)',
    'Stmt.Block(block_kind,clause,binding,body,line)',
    'Stmt.Match(scrutinee,arms,line)',
), "dictionary-key proof no longer covers index reads, index targets, or statement traversal")

local_collector = compact(function_section(consumer_text, "dict_key_collect_locals"))
require_fragments(local_collector, (
    'Stmt.VarDecl(name,type_expression,value,line)',
    'local_key:sview=dict_type_argument_at(type_expression,0)',
    'ifdict_key_spelling_unsupported(local_key):names.push(name)keys.push(local_key)values.push(dict_type_argument_at(type_expression,1))',
    'Stmt.If(condition,then_body,else_body,line)',
    'Stmt.While(condition,body,line)',
    'Stmt.For(bind,variables,iterable,body,line)',
    'Stmt.Block(block_kind,clause,binding,body,line)',
), "proved key policy no longer tracks declared local dictionary bindings")

declaration_walk = compact(function_section(consumer_text, "check_runtime_dict_key_decls"))
require_fragments(declaration_walk, (
    'Decl.Func(name,params,return_type,body,effects,decorators,line)',
    'param_key:sview=dict_type_argument_at(param.type_expression,0)',
    'ifdict_key_spelling_unsupported(param_key):names.push(param.name)keys.push(param_key)values.push(dict_type_argument_at(param.type_expression,1))',
    'dict_key_collect_locals(body,names,keys,values)',
    'table<-dict_key_check_statements(body,names,keys,values,table)ifnames.count>0',
    'Decl.Module(module_name,body,line):table<-check_runtime_dict_key_decls(body,table)',
    'Decl.Scoped(body,line):table<-check_runtime_dict_key_decls(body,table)',
), "dictionary-key proof no longer covers parameter/local bindings and nested declarations")
checker_entry = compact(function_section(consumer_text, "check_runtime_dict_key"))
if "table<-check_runtime_dict_key_decls(declarations,table)" not in checker_entry:
    raise SystemExit("semantic dictionary-key entry point no longer invokes its traversal")

if 'include "../../src/semantic/runtime_dict_key_policy.elisa"' not in positive_text or \
        'include "./runtime_dict_key_policy.elisa"' not in negative_text:
    raise SystemExit("dictionary-key proof fixtures must import the production policy")
positive_names = {
    "resolved_key_classifier_is_exact",
    "declared_spelling_check_is_exact",
    "diagnostic_spelling_is_exact_for_every_input",
}
negative_names = {
    "false_claim_cstr_is_an_unhashable_resolved_key",
    "false_claim_f64_requires_a_declared_spelling_check",
    "false_claim_dstr_keeps_its_declared_diagnostic_spelling",
}
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("dictionary-key proof inventory changed")

positive_claims = {
    "resolved_key_classifier_is_exact": 'SemanticRuntimeDictKeyPolicy::is_unhashable_resolved_key_spelling(spelling)==(spelling=="sview"orspelling=="dstr"orspelling=="f32"orspelling=="f64")',
    "declared_spelling_check_is_exact": 'SemanticRuntimeDictKeyPolicy::requires_declared_key_spelling_check(spelling)==(spelling=="sview"orspelling=="dstr")',
    "diagnostic_spelling_is_exact_for_every_input": 'SemanticRuntimeDictKeyPolicy::diagnostic_spelling(spelling)==("darray[u8]"ifspelling=="dstr"elsespelling)',
}
for name, claim in positive_claims.items():
    section = compact(function_section(positive_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"positive proof {name} no longer establishes its source-bound claim")
negative_claims = {
    "false_claim_cstr_is_an_unhashable_resolved_key": 'SemanticRuntimeDictKeyPolicy::is_unhashable_resolved_key_spelling("cstr")',
    "false_claim_f64_requires_a_declared_spelling_check": 'SemanticRuntimeDictKeyPolicy::requires_declared_key_spelling_check("f64")',
    "false_claim_dstr_keeps_its_declared_diagnostic_spelling": 'SemanticRuntimeDictKeyPolicy::diagnostic_spelling("dstr")=="dstr"',
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
    raise SystemExit("dictionary-key spelling proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POLICY, CONSUMER,
    SEMANTIC, SEMANTIC_PASSES, RESOLVER, RESOLVER_OPERATORS,
    RESOLVER_INITIALIZERS, POSITIVE, NEGATIVE, *source_closure,
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
assert positive == run(POSITIVE)[1], "dictionary-key policy proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_after == hashes_before, "dictionary-key proof inputs changed during admission"
